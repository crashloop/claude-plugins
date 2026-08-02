import pytest
from pathlib import Path
from hoolint.config import load_config


def test_defaults_load_without_project_file(tmp_path):
    cfg = load_config(tmp_path)
    ids = [r["id"] for r in cfg.rules]
    assert "verbose-comments" in ids
    assert cfg.settings["stand_down_after"] == 2


def test_judged_rules_are_advisory(tmp_path):
    """A rule gated by `local_llm` must not block the stop.

    Measured over three runs on 97 ambiguous spans, that judge confirmed at 0.55
    precision and gave 11% of spans a different verdict between runs, including
    opposite stable verdicts on two byte-identical comments. See
    docs/measurements/2026-08-01-verbose-comments-judge.md.
    """
    judged = [r for r in load_config(tmp_path).rules
              if any(s["strategy"] == "local_llm" for s in r.get("stage", []))]
    assert judged, "no judged rule found: this pin is watching nothing"
    for rule in judged:
        assert rule["severity"] == "warn", f"{rule['id']} blocks on an LLM verdict"


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


def test_unknown_mode_raises_at_config_load(tmp_path):
    """A typo in modes must fail loudly. Silently never running is a silent pass."""
    (tmp_path / "hoolint.toml").write_text(
        '[[rule]]\nid = "r"\nglobs = ["*.py"]\nmodes = ["sesion"]\n'
    )
    with pytest.raises(ValueError, match="unknown mode"):
        load_config(tmp_path)


def test_empty_modes_list_raises_at_config_load(tmp_path):
    """An empty list would disable the rule everywhere while looking configured."""
    (tmp_path / "hoolint.toml").write_text(
        '[[rule]]\nid = "r"\nglobs = ["*.py"]\nmodes = []\n'
    )
    with pytest.raises(ValueError, match="non-empty list"):
        load_config(tmp_path)


def test_readme_rule_examples_stay_runnable():
    """Every documented rule must parse and name a registered strategy.

    The README carries opt-in rules as copy-paste TOML. Nothing else executes
    them, so a renamed strategy would leave working prose that silently fails on
    the first user who pastes it.
    """
    import re
    import tomllib
    from hoolint.strategies import STRATEGIES
    readme = (Path(__file__).parents[2] / "README.md").read_text()
    documented = [r for block in re.findall(r"```toml\n(.*?)```", readme, re.S)
                  for r in tomllib.loads(block).get("rule", [])]
    assert documented, "no rule examples found: the extraction pattern broke"
    for rule in documented:
        assert rule["globs"], f"{rule['id']}: no globs"
        for stage in rule.get("stage", []):
            assert stage["strategy"] in STRATEGIES, \
                f"{rule['id']}: unknown strategy {stage['strategy']!r}"
