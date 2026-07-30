import pytest

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


def test_companion_custom_message_replaces_the_default(tmp_path):
    """The documented `message` key must reach the finding, not just the default."""
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py"])
    stage = {"requires": "CHANGELOG.md", "message": "public API changed without a CHANGELOG"}
    out = CompanionStrategy().run(None, stage, ctx)
    assert out[0].message == "public API changed without a CHANGELOG"


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


def test_companion_chained_after_a_stage_raises(tmp_path):
    """Generators never filter. Returning [] here would silently discard the earlier stage."""
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py"])
    with pytest.raises(ValueError, match="cannot follow another stage"):
        CompanionStrategy().run([], {"requires": "CHANGELOG.md"}, ctx)


def test_change_size_chained_after_a_stage_raises(tmp_path):
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.py", "c.py"])
    with pytest.raises(ValueError, match="cannot follow another stage"):
        ChangeSizeStrategy().run([], {"max_files": 2}, ctx)


def test_change_size_under_limit_is_silent(tmp_path):
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.py"])
    assert ChangeSizeStrategy().run(None, {"max_files": 5}, ctx) == []


def test_change_size_over_limit_is_flagged(tmp_path):
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.py", "c.py"])
    out = ChangeSizeStrategy().run(None, {"max_files": 2}, ctx)
    assert len(out) == 1
    assert "3" in out[0].message


def test_change_size_custom_message_replaces_the_default(tmp_path):
    """The documented `message` key must reach the finding, not just the default."""
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.py", "c.py"])
    stage = {"max_files": 2, "message": "too much at once"}
    assert ChangeSizeStrategy().run(None, stage, ctx)[0].message == "too much at once"


def test_change_size_emits_exactly_once_across_matched_files(tmp_path):
    """The check describes the whole change set, so it must not repeat per file."""
    from hoolint.config import Config
    from hoolint.engine import run

    files = []
    for i in range(5):
        p = tmp_path / f"f{i}.py"
        p.write_text("x = 1\n")
        files.append(p)
    cfg = Config(rules=[{"id": "blast-radius", "globs": ["**/*.py"], "severity": "warn",
                         "stage": [{"strategy": "change_size", "max_files": 2}]}],
                 settings={})
    out = run(cfg, files, tmp_path, "git")
    assert len(out) == 1, f"expected one set-level finding, got {len(out)}"


def test_change_size_counts_the_whole_change_set_not_the_glob_subset(tmp_path):
    """Blast radius is about the whole change, even when the rule's globs are narrow."""
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.md", "c.md", "d.md"])
    out = ChangeSizeStrategy().run(None, {"max_files": 3}, ctx)
    assert len(out) == 1
    assert "4" in out[0].message


def test_metadata_rule_works_under_a_symlinked_root(tmp_path):
    """An unresolved path under a symlinked root must not break every metadata rule.

    The engine admits a file on its resolved form but keeps the original, and the session
    journal records the path the tool reported. Under a symlinked project directory the two
    spellings differ, and a bare relative_to turned the whole feature into "rule failed".
    """
    from hoolint.config import Config
    from hoolint.engine import run

    real = tmp_path / "real"
    (real / "src").mkdir(parents=True)
    (real / "src" / "a.py").write_text("x = 1\n")
    link = tmp_path / "link"
    link.symlink_to(real)

    cfg = Config(rules=[{"id": "api-changelog", "globs": ["**/*.py"], "severity": "warn",
                         "stage": [{"strategy": "companion",
                                    "requires": "CHANGELOG.md"}]}],
                 settings={})
    out = run(cfg, [link / "src" / "a.py"], real, "git")
    assert len(out) == 1
    assert "rule failed" not in out[0].message
    assert out[0].file == "src/a.py"
