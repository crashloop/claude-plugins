import pytest
from hoolint.config import Config
from hoolint.engine import run
from hoolint.findings import Finding
from hoolint.strategies import STRATEGIES

RULE = {
    "id": "verbose-comments", "globs": ["**/*.py"], "severity": "block",
    "stage": [{"strategy": "regex",
               "pattern": r"(?m)(^[ \t]*# [^\n]*\n){3,}",
               "exclude": [r"(?i)(copyright|SPDX-License|licensed under)",
                           r"(?i)# *(noqa|type: *ignore|pylint|pragma)"],
               "message": "more than 2 consecutive comment lines"}],
}


def test_regex_rule_finds_span_and_sets_severity(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("x = 1\n# one\n# two\n# three\ny = 2\n")
    cfg = Config(rules=[RULE], settings={})
    found = run(cfg, [f], tmp_path, "session")
    assert len(found) == 1
    assert (found[0].start_line, found[0].end_line) == (2, 4)
    assert found[0].severity == "block"


def test_non_matching_glob_skipped(tmp_path):
    f = tmp_path / "m.md"
    f.write_text("# one\n# two\n# three\n")
    cfg = Config(rules=[RULE], settings={})
    assert run(cfg, [f], tmp_path, "session") == []


def test_excluded_spans_dropped(tmp_path):
    """License headers and pragma runs never reach the next stage."""
    f = tmp_path / "m.py"
    f.write_text("# Copyright 2026 Someone\n# All rights reserved.\n"
                 "# Licensed under MIT\nx = 1\n")
    cfg = Config(rules=[RULE], settings={})
    assert run(cfg, [f], tmp_path, "session") == []


def test_file_outside_root_is_skipped_not_fatal(tmp_path):
    """A journalled path outside the project must not crash the run."""
    outside = tmp_path.parent / "elsewhere.py"
    outside.write_text("# a\n# b\n# c\n")
    root = tmp_path / "proj"
    root.mkdir()
    cfg = Config(rules=[RULE], settings={})
    assert run(cfg, [outside], root, "session") == []


def test_malformed_rule_missing_id_does_not_crash_guard(tmp_path):
    """The exception guard must survive the very rule it's meant to catch: no 'id'."""
    f = tmp_path / "m.py"
    f.write_text("x = 1\n")
    cfg = Config(rules=[{"globs": ["**/*.py"], "stage": []}], settings={})
    found = run(cfg, [f], tmp_path, "session")
    assert len(found) == 1
    assert found[0].rule_id == "<unknown-rule>"
    assert "KeyError" in found[0].message


TRAILING_BLANK_RULE = {
    "id": "trailing-blank", "globs": ["**/*.py"], "severity": "warn",
    "stage": [{"strategy": "regex", "pattern": r"x\n\n\n", "message": "trailing blanks"}],
}


def test_regex_span_with_trailing_blank_lines_counts_all_lines(tmp_path):
    """A span with trailing blank lines must count every line, not collapse them."""
    f = tmp_path / "m.py"
    f.write_text("x\n\n\n")
    cfg = Config(rules=[TRAILING_BLANK_RULE], settings={})
    found = run(cfg, [f], tmp_path, "session")
    assert len(found) == 1
    assert (found[0].start_line, found[0].end_line) == (1, 3)


@pytest.fixture
def fake_strategy():
    """Register a fake stage strategy for one test, then remove it so it can't leak."""
    registered = []

    def _register(name: str, strat) -> None:
        STRATEGIES[name] = strat
        registered.append(name)

    yield _register
    for name in registered:
        del STRATEGIES[name]


class _SkipFilterStrategy:
    """Generator strategy that always disarms blocking via ctx.skip_filter."""

    def run(self, candidates, stage, ctx):
        ctx.skip_filter("could not compile filter pattern")
        if candidates is not None:
            return candidates
        return [Finding(rule_id=ctx.rule_id, file=str(ctx.path.relative_to(ctx.root)),
                        start_line=1, end_line=1, span_text="x", message="found",
                        severity=ctx.severity)]


def test_skip_filter_demotes_block_finding_to_warn(tmp_path, fake_strategy):
    """A rule whose filter stage calls skip_filter must ship its findings as warn."""
    fake_strategy("skip-demo", _SkipFilterStrategy())
    rule = {"id": "skip-demo-rule", "globs": ["**/*.py"], "severity": "block",
            "stage": [{"strategy": "skip-demo"}]}
    f = tmp_path / "m.py"
    f.write_text("x = 1\n")
    cfg = Config(rules=[rule], settings={})
    found = run(cfg, [f], tmp_path, "session")
    assert len(found) == 1
    assert found[0].severity == "warn"
    assert "could not compile filter pattern" in found[0].notes


OR_RULE = {
    "id": "or-rule", "globs": ["**/*.py"], "severity": "warn",
    "stage": [
        {"strategy": "regex", "pattern": r"(?m)^# A\n", "message": "found A"},
        {"strategy": "regex", "pattern": r"(?m)^# B\n", "op": "or", "message": "found B"},
    ],
}


def test_or_stage_unions_candidates_by_fingerprint(tmp_path):
    """An op="or" stage adds its own generator findings to the prior stage's, deduped."""
    f = tmp_path / "m.py"
    f.write_text("# A\n# B\n")
    cfg = Config(rules=[OR_RULE], settings={})
    found = run(cfg, [f], tmp_path, "session")
    fingerprints = {f_.fingerprint for f_ in found}
    assert len(found) == 2
    assert len(fingerprints) == 2
    assert {f_.span_text for f_ in found} == {"# A\n", "# B\n"}
