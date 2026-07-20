"""Load packaged defaults and merge the project's hoolint.toml per rule id."""
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


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
    return Config(rules=list(rules.values()), settings=settings)
