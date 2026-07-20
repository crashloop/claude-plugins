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
