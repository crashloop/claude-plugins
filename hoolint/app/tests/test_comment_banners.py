"""The shipped `comment-banners` rule, and the exclusion it earns next door.

Measured on structurella (`docs/measurements/2026-08-01-verbose-comments-judge.md`):
the banner-block pattern matched 39 of the 59 spans the judge confirmed and 1 of
the 53 it cleared. A regex therefore does two thirds of the judge's work on this
rule at no cost, and the judge keeps the spans that are genuinely ambiguous.
"""
from hoolint.config import load_config
from hoolint.engine import run

RULE = "# " + "=" * 40


def _check(tmp_path, body):
    f = tmp_path / "m.py"
    f.write_text(body)
    return run(load_config(tmp_path), [f], tmp_path, "git")


def test_rule_title_rule_is_flagged_as_a_banner(tmp_path):
    found = _check(tmp_path, f"{RULE}\n# User CRUD audit tests\n{RULE}\n\n\n"
                             "def f():\n    pass\n")
    assert [f.rule_id for f in found] == ["comment-banners"]
    assert found[0].severity == "warn"


def test_indented_dash_banners_count_too(tmp_path):
    """Both fill characters and both nesting levels appear in real code."""
    body = ("def f():\n    # " + "-" * 30 + "\n    # Pattern: base call\n"
            "    # " + "-" * 30 + "\n    return 1\n")
    assert [f.rule_id for f in _check(tmp_path, body)] == ["comment-banners"]


def test_real_content_between_the_rules_is_not_a_banner(tmp_path):
    """The judge cleared these: the lines between the rules carry a reference or
    a constraint the code cannot express. Neither rule should fire."""
    found = _check(tmp_path, f"{RULE}\n"
        "# Extra action constants (project-specific, not in the shared library).\n"
        "# Registered via AUDIT_TRAIL_EXTRA_ACTIONS in settings/base.py.\n"
        f"{RULE}\n\n\nX = 1\n")
    assert found == []


def test_verbose_comments_leaves_banner_spans_to_this_rule(tmp_path):
    """Without the exclude, a banner is judged as well as pattern-matched, which
    is the LLM call this rule exists to avoid."""
    found = _check(tmp_path, f"{RULE}\n# Section\n{RULE}\n\n\nX = 1\n")
    assert "verbose-comments" not in {f.rule_id for f in found}


def test_an_ordinary_comment_block_is_not_a_banner(tmp_path):
    """Three prose lines are verbose-comments' business, not this rule's."""
    found = _check(tmp_path, "# first line of prose\n# second line of prose\n"
                             "# third line of prose\nX = 1\n")
    assert "comment-banners" not in {f.rule_id for f in found}
