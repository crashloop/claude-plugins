from pathlib import Path
from hoolint.config import Config
from hoolint.engine import run

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
