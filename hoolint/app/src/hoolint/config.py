"""Load packaged defaults and merge the project's hoolint.toml per rule id."""
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


VALID_MODES = ("session", "git")


@dataclass
class Config:
    rules: list[dict]
    settings: dict


def load_config(project_root: Path, extra_rules: list[dict] | None = None) -> Config:
    """Merge defaults <- project hoolint.toml <- extra_rules, per rule id.

    Args:
        project_root: Directory containing an optional hoolint.toml.
        extra_rules: Custom rules (from hoolint_rules/) merged last.
    """
    base = tomllib.loads(
        (resources.files("hoolint") / "defaults.toml").read_text())
    proj_file = project_root / "hoolint.toml"
    proj = tomllib.loads(proj_file.read_text()) if proj_file.exists() else {}
    rules = {r["id"]: r for r in base.get("rule", [])}
    for r in [*proj.get("rule", []), *(extra_rules or [])]:
        rules[r["id"]] = r  # wholesale override or add
    rules = {rid: r for rid, r in rules.items() if r.get("enabled", True)}
    settings = {**base.get("settings", {}), **proj.get("settings", {})}
    for r in rules.values():
        modes = r.get("modes")
        if modes is None:
            continue
        if not isinstance(modes, list) or not modes:
            raise ValueError(
                f"rule {r['id']}: modes must be a non-empty list of {list(VALID_MODES)}")
        unknown = [m for m in modes if m not in VALID_MODES]
        if unknown:
            raise ValueError(
                f"rule {r['id']}: unknown mode(s) {unknown}; valid modes are "
                f"{list(VALID_MODES)}")
    return Config(rules=list(rules.values()), settings=settings)
