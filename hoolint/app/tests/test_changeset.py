import pytest
from pathlib import Path

from hoolint.strategies.base import Context
from hoolint.strategies.changeset_ import CompanionStrategy


def _ctx(tmp_path, name, changed_names):
    """Build a Context as the engine would, with a synthetic change set."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n")
    changed = []
    for n in changed_names:
        p = tmp_path / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n")
        changed.append(p)
    return Context(path=path, root=tmp_path, mode="git", settings={},
                   rule_id="companion-rule", severity="warn",
                   changed=changed, matched=[path])


def test_fixed_target_missing_is_flagged(tmp_path):
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py"])
    out = CompanionStrategy().run(None, {"requires": "CHANGELOG.md"}, ctx)
    assert len(out) == 1
    assert "CHANGELOG.md" in out[0].message
    assert out[0].file == "src/api.py"      # anchored to the changed file
    assert out[0].severity == "warn"        # takes the rule's severity


def test_fixed_target_present_is_silent(tmp_path):
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py", "CHANGELOG.md"])
    assert CompanionStrategy().run(None, {"requires": "CHANGELOG.md"}, ctx) == []


def test_derived_target_missing_is_flagged(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"tests/test_\1.py"}
    out = CompanionStrategy().run(None, stage, ctx)
    assert len(out) == 1
    assert "tests/test_foo.py" in out[0].message


def test_derived_target_present_is_silent(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py", "tests/test_foo.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"tests/test_\1.py"}
    assert CompanionStrategy().run(None, stage, ctx) == []


def test_derived_pattern_that_does_not_match_is_silent(tmp_path):
    """A rule whose glob is wider than its pattern must not flag unrelated files."""
    ctx = _ctx(tmp_path, "docs/guide.py", ["docs/guide.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"tests/test_\1.py"}
    assert CompanionStrategy().run(None, stage, ctx) == []


def test_mutually_exclusive_config_raises(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    stage = {"requires": "CHANGELOG.md", "requires_from": "a", "requires_to": "b"}
    with pytest.raises(ValueError, match="mutually exclusive"):
        CompanionStrategy().run(None, stage, ctx)


def test_incomplete_derived_config_raises(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    with pytest.raises(ValueError, match="requires_from and requires_to"):
        CompanionStrategy().run(None, {"requires_from": r"src/(.*)\.py"}, ctx)


def test_derived_path_escaping_the_root_raises(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"../outside/\1.py"}
    with pytest.raises(ValueError, match="escapes the project root"):
        CompanionStrategy().run(None, stage, ctx)


def test_companion_ignores_incoming_candidates(tmp_path):
    """Generators never filter. A non-None candidate list means a misconfigured stage."""
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py"])
    assert CompanionStrategy().run([], {"requires": "CHANGELOG.md"}, ctx) == []
