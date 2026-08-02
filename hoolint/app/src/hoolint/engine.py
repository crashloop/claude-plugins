"""Run rules over files: stages sequence cheap-to-expensive per file."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from hoolint.config import Config, VALID_MODES
from hoolint.findings import Finding
from hoolint.strategies import STRATEGIES
from hoolint.strategies.base import Context


def _admits(rule: dict, path: Path, root_r: Path) -> bool:
    """Whether a rule's file scope covers this path.

    Args:
        rule: The rule, for its `globs` and optional `exclude_globs`.
        path: A changed file, resolved or not.
        root_r: The already-resolved project root.

    Returns:
        True if the path is inside the root, matches a glob, and matches no exclusion.
    """
    resolved = path.resolve()
    if not resolved.is_relative_to(root_r):
        return False
    rel = resolved.relative_to(root_r)
    return (any(rel.full_match(g) for g in rule["globs"])
            and not any(rel.full_match(g) for g in rule.get("exclude_globs", [])))


def _run_rule(rule: dict, files: list[Path], root: Path, mode: str,
              settings: dict) -> list[Finding]:
    root_r = root.resolve()
    matched = [f for f in files if _admits(rule, f, root_r)]
    out: list[Finding] = []
    for path in matched:
        ctx = Context(path=path, root=root, mode=mode, settings=settings,
                      rule_id=rule["id"], severity=rule.get("severity", "warn"),
                      changed=files, matched=matched)
        cands: list[Finding] | None = None
        for stage in rule.get("stage", []):
            strat = STRATEGIES[stage["strategy"]]
            if cands is not None and stage.get("op") == "or":
                fresh = strat.run(None, stage, ctx)
                merged = {c.fingerprint: c for c in [*cands, *fresh]}
                cands = list(merged.values())
            else:
                cands = strat.run(cands, stage, ctx)
        for c in cands or []:
            c.notes.extend(n for n in ctx.notes if n not in c.notes)
            if ctx.filter_skipped and c.severity == "block":
                c.severity = "warn"
        out.extend(cands or [])
    return out


def _guarded(rule: dict, files: list[Path], root: Path, mode: str,
             settings: dict) -> list[Finding]:
    """One bad rule degrades to a note; it never kills the whole check."""
    try:
        return _run_rule(rule, files, root, mode, settings)
    except Exception as exc:                     # noqa: BLE001 - deliberate
        return [Finding(rule_id=rule.get("id", "<unknown-rule>"), file="",
                        start_line=0, end_line=0, span_text="", severity="warn",
                        message=f"rule failed, skipped: {exc!r}")]


def run(cfg: Config, files: list[Path], root: Path, mode: str) -> list[Finding]:
    """Execute all rules that apply to this mode; rules run in parallel, stages sequentially."""
    applicable = [r for r in cfg.rules if mode in r.get("modes", list(VALID_MODES))]
    # ponytail: thread pool; process pool only if CPU-bound rules dominate
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(_guarded, r, files, root, mode, cfg.settings)
                   for r in applicable]
        return [f for fut in futures for f in fut.result()]
