"""hoolint CLI: check, waive (trust and warmup added by later tasks)."""
import argparse
import json
import sys
import tomllib
from pathlib import Path

import tomlkit

from hoolint import changes, journal, state, waivers   # trust added in Task 11
from hoolint.config import load_config
from hoolint.engine import run as engine_run
from hoolint.findings import Finding

WAIVE_HINT = (
    'Fix each finding. Only if the user explicitly sanctioned this code may you '
    'dismiss it: hoolint waive <fingerprint> --reason "user asked for X on <date/turn>". '
    'The reason must record that sanction — waivers are committed team policy, not '
    'your opinion about the rule.')


def _format(f: Finding) -> str:
    line = f"[{f.fingerprint}] {f.file}:{f.start_line}-{f.end_line} {f.rule_id}: {f.message}"
    if f.needs_judgment:
        line += f"\n  judge: {f.judgment_prompt}"
    for n in f.notes:
        line += f"\n  note: {n}"
    return line


def _system_message(text: str) -> None:
    """Stop-hook stdout is discarded unless it is a structured response."""
    print(json.dumps({"systemMessage": text}))


def _cmd_check(args: argparse.Namespace) -> int:
    """Run rules over the session journal or a git diff and report findings.

    Args:
        args: Parsed CLI namespace for the `check` subcommand.

    Returns:
        Session mode: 2 if a block finding survives, 0 otherwise.
        Git mode: 1 if a block finding exists (or the check itself is
        broken), 0 otherwise.
    """
    root = Path(args.root).resolve()
    cfg = load_config(root)
    session_id = "default"
    if args.mode == "session":
        hook = json.load(sys.stdin) if not sys.stdin.isatty() else {}
        session_id = hook.get("session_id", "default")
        # Files still blocked last run stay in scope even if nothing was edited.
        seen = {p: None for p in journal.files(root, session_id)}
        seen.update({p: None for p in state.blocked_files(root) if p.exists()})
        files = list(seen)
    else:
        ref = args.ref or cfg.settings.get("git_ref", "auto")
        try:
            files = changes.git_changed(root, ref)
        except RuntimeError as exc:
            # A broken check must not silently report success in a pipeline.
            print(f"hoolint: git change detection failed: {exc}", file=sys.stderr)
            return 1

    found = engine_run(cfg, files, root, args.mode)
    try:
        waived = waivers.load(root)
    except tomllib.TOMLDecodeError as exc:
        msg = f"hoolint: {waivers.FILE} is malformed, ignoring this check: {exc}"
        if args.mode == "git":
            print(msg, file=sys.stderr)
            return 1  # broken config must not silently pass a pipeline check
        _system_message(msg)
        return 0  # an incompletely-configured install reports but never blocks
    found = [f for f in found if f.fingerprint not in waived]
    blocks = [f for f in found if f.severity == "block"]
    warns = [f for f in found if f.severity == "warn"]

    if args.mode == "git":
        for f in found:
            print(_format(f))
        return 1 if blocks else 0

    if not blocks:
        journal.clear(root, session_id)
        state.record_findings(root, [f.record() for f in found])
        if warns:
            _system_message("hoolint:\n" + "\n".join(_format(f) for f in warns))
        return 0

    same, consecutive = state.bump(root, [f.record() for f in blocks],
                                   [str(root / f.file) for f in blocks])
    limit = cfg.settings.get("stand_down_after", 2)
    if same > limit or consecutive > limit:
        state.record_findings(root, [f.record() for f in found])
        journal.clear(root, session_id)
        report = "\n".join(_format(f) for f in blocks)
        _system_message(
            f"hoolint stand-down after {consecutive} consecutive blocked stops "
            f"— these need a human decision:\n{report}")
        return 0
    print(f"hoolint: {len(blocks)} blocking finding(s).", file=sys.stderr)
    for f in blocks:
        print(_format(f), file=sys.stderr)
    print(WAIVE_HINT, file=sys.stderr)
    return 2


def _cmd_waive(args: argparse.Namespace) -> int:
    """Record a committed waiver, or prune waivers a full check no longer finds.

    Args:
        args: Parsed CLI namespace for the `waive` subcommand.

    Returns:
        0 on success; 1 if the fingerprint was not in the last check's
        finding set.
    """
    root = Path(args.root).resolve()
    if args.prune:
        cfg = load_config(root)
        try:
            # Same broken-ref case as check --mode git; see there for the repro.
            files = changes.git_changed(root, "HEAD")
        except RuntimeError as exc:
            print(f"hoolint: git change detection failed: {exc}", file=sys.stderr)
            return 1
        live = engine_run(cfg, files, root, "git")
        try:
            dropped = waivers.prune(root, {f.fingerprint for f in live})
        except tomlkit.exceptions.ParseError as exc:
            print(f"hoolint: {waivers.FILE} is malformed, cannot prune: {exc}",
                  file=sys.stderr)
            return 1
        print(f"pruned {dropped} waiver(s) whose span no longer matches")
        return 0
    record = state.finding_record(root, args.fingerprint)
    if record is None:
        print(f"refusing: {args.fingerprint} was not reported by the last check. "
              "Waivers are only for findings hoolint actually surfaced.",
              file=sys.stderr)
        return 1
    waivers.add(root, Finding.from_record(record), args.reason)
    print(f"waived {args.fingerprint} (review lands in the PR diff)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """hoolint CLI entry point: dispatches to the `check` and `waive` subcommands.

    Args:
        argv: Argument vector to parse; defaults to `sys.argv[1:]`.

    Returns:
        The subcommand's exit code.
    """
    p = argparse.ArgumentParser(prog="hoolint")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--mode", choices=["session", "git"], default="session")
    c.add_argument("--ref", default=None)   # None -> settings["git_ref"]
    c.add_argument("--root", default=".")
    c.set_defaults(fn=_cmd_check)
    w = sub.add_parser("waive")
    w.add_argument("fingerprint", nargs="?")
    w.add_argument("--reason")
    w.add_argument("--prune", action="store_true")
    w.add_argument("--root", default=".")
    w.set_defaults(fn=_cmd_waive)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
