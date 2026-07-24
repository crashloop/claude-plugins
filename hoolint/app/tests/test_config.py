from pathlib import Path
from hoolint.config import load_config


def test_defaults_load_without_project_file(tmp_path):
    cfg = load_config(tmp_path)
    ids = [r["id"] for r in cfg.rules]
    assert "verbose-comments" in ids
    assert cfg.settings["stand_down_after"] == 2


def test_project_overrides_wholesale_and_disables(tmp_path):
    (tmp_path / "hoolint.toml").write_text(
        '[settings]\nstand_down_after = 5\n'
        '[[rule]]\nid = "verbose-comments"\nenabled = false\n'
        '[[rule]]\nid = "my-rule"\nglobs = ["*.md"]\nseverity = "warn"\n'
    )
    cfg = load_config(tmp_path)
    ids = [r["id"] for r in cfg.rules]
    assert "verbose-comments" not in ids
    assert "my-rule" in ids
    assert cfg.settings["stand_down_after"] == 5


def test_extra_rules_merge_last_and_override_project(tmp_path):
    """Custom rules (the Task 11 trust path) merge after project rules and
    override a same-id rule wholesale."""
    (tmp_path / "hoolint.toml").write_text(
        '[[rule]]\nid = "verbose-comments"\nseverity = "warn"\n'
    )
    extra = [{"id": "verbose-comments", "severity": "block", "globs": ["*.py"]},
             {"id": "custom-rule", "severity": "warn", "globs": ["*.md"]}]
    cfg = load_config(tmp_path, extra_rules=extra)
    by_id = {r["id"]: r for r in cfg.rules}
    assert by_id["verbose-comments"]["severity"] == "block"  # extra wins over project
    assert "custom-rule" in by_id
