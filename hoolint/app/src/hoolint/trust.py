"""Opt-in gate for custom Python rules: no drive-by code execution.

Trust binds to the content of hoolint_rules/, not to the directory. A grant is
consent to run code the user reviewed, not to run whatever later lands there.
"""
import hashlib
import os
import tomllib
from pathlib import Path

import tomlkit

TRUST_HINT = "custom rules present, not loaded — run `hoolint trust`"


def _config_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "hoolint" / "trusted.toml"


def rules_digest(root: Path) -> str:
    """Digest over every file in hoolint_rules/, recursively.

    Covers all file types (not just *.py) so an imported helper or a data
    sidecar can't be swapped post-grant without revoking trust. Excludes
    __pycache__ since it's regenerated, not reviewed content.

    Args:
        root: Project root directory.
    """
    rules_dir = root / "hoolint_rules"
    h = hashlib.sha256()
    if not rules_dir.is_dir():
        return h.hexdigest()
    files = [
        p for p in rules_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.relative_to(rules_dir).parts
    ]
    for p in sorted(files, key=lambda p: p.relative_to(rules_dir).as_posix()):
        h.update(p.relative_to(rules_dir).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def is_trusted(root: Path) -> bool:
    """Whether root's hoolint_rules/ content matches a recorded grant.

    Args:
        root: Project root directory.
    """
    f = _config_file()
    if not f.exists():
        return False
    try:
        granted = tomllib.loads(f.read_text()).get("projects", {})
    except tomllib.TOMLDecodeError:
        return False  # a corrupt trust store must never be treated as trusted
    return granted.get(str(root.resolve())) == rules_digest(root)


def grant(root: Path) -> None:
    """Record a content digest of root's hoolint_rules/ as trusted.

    Args:
        root: Project root directory.
    """
    f = _config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = tomllib.loads(f.read_text()) if f.exists() else {}
    except tomllib.TOMLDecodeError:
        data = {}  # corrupt store: start fresh rather than aborting the grant
    projects = data.get("projects", {})
    projects[str(root.resolve())] = rules_digest(root)
    f.write_text(tomlkit.dumps({"projects": projects}))


def load_custom_rules(root: Path) -> tuple[list[dict], str | None]:
    """Load hoolint_rules/*.py if the project is trusted.

    A file that raises on exec degrades to a notice rather than crashing the
    check; a file with no module-level `rule` dict is silently skipped.

    Args:
        root: Project root directory.

    Returns:
        (rules, notice): notice is a user-facing string when rules were
        skipped or a file failed to load, else None.
    """
    rules_dir = root / "hoolint_rules"
    if not rules_dir.is_dir():
        return [], None
    if not is_trusted(root):
        return [], TRUST_HINT
    rules = []
    failed = []
    for py in sorted(rules_dir.glob("*.py")):
        ns: dict = {}
        try:
            exec(compile(py.read_text(), str(py), "exec"), ns)  # trusted by user
        except (Exception, SystemExit) as exc:
            # SystemExit (e.g. sys.exit(), argparse.error()) is a BaseException,
            # not Exception; caught explicitly so a buggy rule can't kill the check.
            failed.append(f"{py.name}: {exc}")
            continue
        if isinstance(ns.get("rule"), dict):
            rules.append(ns["rule"])
    notice = f"hoolint: error loading custom rule(s): {'; '.join(failed)}" if failed else None
    return rules, notice
