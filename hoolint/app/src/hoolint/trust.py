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
    """Digest over every rule file's name and bytes.

    Args:
        root: Project root directory.
    """
    rules_dir = root / "hoolint_rules"
    h = hashlib.sha256()
    for py in sorted(rules_dir.glob("*.py")) if rules_dir.is_dir() else []:
        h.update(py.name.encode())
        h.update(py.read_bytes())
    return h.hexdigest()


def is_trusted(root: Path) -> bool:
    """Whether root's hoolint_rules/ content matches a recorded grant.

    Args:
        root: Project root directory.
    """
    f = _config_file()
    if not f.exists():
        return False
    granted = tomllib.loads(f.read_text()).get("projects", {})
    return granted.get(str(root.resolve())) == rules_digest(root)


def grant(root: Path) -> None:
    """Record a content digest of root's hoolint_rules/ as trusted.

    Args:
        root: Project root directory.
    """
    f = _config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    data = tomllib.loads(f.read_text()) if f.exists() else {}
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
        except Exception as exc:
            failed.append(f"{py.name}: {exc}")
            continue
        if isinstance(ns.get("rule"), dict):
            rules.append(ns["rule"])
    notice = f"hoolint: error loading custom rule(s): {'; '.join(failed)}" if failed else None
    return rules, notice
