from hoolint.config import Config
from hoolint.engine import run

LINKS = {"id": "doc-broken-links", "globs": ["**/*.md"], "severity": "warn",
         "stage": [{"strategy": "doc_links"}]}
REFS = {"id": "doc-drift", "globs": ["**/*.md"], "severity": "warn",
        "stage": [{"strategy": "doc_refs"}]}


def test_broken_relative_link_flagged(tmp_path):
    (tmp_path / "ok.md").write_text("x")
    md = tmp_path / "doc.md"
    md.write_text("[good](ok.md) [bad](missing.md) [web](https://x.io)\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert [f.span_text for f in found] == ["missing.md"]


def test_missing_backticked_path_flagged(tmp_path):
    (tmp_path / "real.py").write_text("x = 1\n")
    md = tmp_path / "doc.md"
    md.write_text("See `real.py` and `gone/old.py` for details.\n")
    found = run(Config(rules=[REFS], settings={}), [md], tmp_path, "git")
    assert [f.span_text for f in found] == ["gone/old.py"]


def test_titled_link_to_existing_file_not_flagged(tmp_path):
    (tmp_path / "real.md").write_text("x")
    md = tmp_path / "doc.md"
    md.write_text('[x](real.md "the title")\n')
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert found == []


def test_titled_link_to_missing_file_flagged_without_title(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text('[x](missing.md "the title")\n')
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert [f.span_text for f in found] == ["missing.md"]


def test_broken_reference_style_link_flagged(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("[x][ref]\n\n[ref]: missing.md\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert [f.span_text for f in found] == ["missing.md"]


def test_valid_reference_style_link_not_flagged(tmp_path):
    (tmp_path / "real.md").write_text("x")
    md = tmp_path / "doc.md"
    md.write_text("[x][ref]\n\n[ref]: real.md\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert found == []


def test_reference_use_with_no_definition_flagged_as_undefined(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("[x][ref]\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert len(found) == 1
    assert found[0].span_text == "ref"
    assert "undefined" in found[0].message


def test_definition_line_itself_not_flagged(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("[ref]: whatever.md\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert found == []


def test_link_inside_fenced_block_not_flagged(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("```\n[bad](missing.md)\n```\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert found == []


def test_shortcut_reference_in_prose_not_flagged(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("See [TODO] later and item [3] below.\nThe list [note] is fine.\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert found == []


def test_shortcut_reference_with_matching_definition_still_not_flagged(tmp_path):
    """Shortcut refs are no longer a supported use, even when a definition exists."""
    (tmp_path / "real.md").write_text("x")
    md = tmp_path / "doc.md"
    md.write_text("A note on [label] here.\n\n[label]: real.md\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert found == []


def test_collapsed_reference_style_link_resolves(tmp_path):
    (tmp_path / "real.md").write_text("x")
    md = tmp_path / "doc.md"
    md.write_text("[text][]\n\n[text]: real.md\n")
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert found == []


def test_prose_brackets_do_not_bury_real_broken_link(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text(
        "# Notes\n"
        "See [TODO] later and item [3] below.\n"
        "The list [a, b, c] is fine.\n"
        "A real broken [link](gone.md) here.\n"
        "Check [the docs][guide] for more.\n"
        "Priority [P1] and [note] tags.\n"
    )
    found = run(Config(rules=[LINKS], settings={}), [md], tmp_path, "git")
    assert len(found) == 2
    messages = {f.span_text: f.message for f in found}
    assert messages["gone.md"] == "broken relative link: gone.md"
    assert messages["guide"] == "undefined reference: [guide]"


EM_DASH = {"id": "em-dashes", "globs": ["**/*.md"], "severity": "warn",
           "stage": [{"strategy": "prose_pattern", "pattern": "—",
                      "message": "em dash"}]}


def test_em_dash_in_prose_flagged(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("The rule is simple — no em dashes.\n")
    found = run(Config(rules=[EM_DASH], settings={}), [md], tmp_path, "git")
    assert len(found) == 1
    assert found[0].start_line == 1
    assert found[0].message == "em dash"


def test_em_dash_inside_fenced_block_not_flagged(tmp_path):
    """Code samples are quoted, not authored prose. 22% of this repo's were fenced."""
    md = tmp_path / "doc.md"
    md.write_text("Prose is clean.\n\n```python\nx = 1  # a — in code\n```\n")
    assert run(Config(rules=[EM_DASH], settings={}), [md], tmp_path, "git") == []


def test_prose_without_em_dash_is_silent(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("Short sentences. Commas, and periods. Nothing to flag.\n")
    assert run(Config(rules=[EM_DASH], settings={}), [md], tmp_path, "git") == []


def test_each_offending_line_gets_its_own_fingerprint(tmp_path):
    """Matching the bare character would give every hit one fingerprint.

    Waiving a single em dash would then silence every other one in the file,
    because the fingerprint hashes span_text.
    """
    md = tmp_path / "doc.md"
    md.write_text("First line — here.\nSecond line — there.\n")
    found = run(Config(rules=[EM_DASH], settings={}), [md], tmp_path, "git")
    assert len(found) == 2
    assert len({f.fingerprint for f in found}) == 2


def test_two_em_dashes_on_one_line_are_one_finding(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("One — two — three.\n")
    found = run(Config(rules=[EM_DASH], settings={}), [md], tmp_path, "git")
    assert len(found) == 1
    assert found[0].message == "em dash"          # not a "rule failed" finding
    assert found[0].span_text == "One — two — three."


def test_prose_pattern_filters_incoming_candidates(tmp_path):
    """Chained, it filters like RegexStrategy rather than discarding the set.

    Its file-mates in docs_.py generate regardless, which silently replaces the
    previous stage's findings. New code does not copy that.
    """
    from hoolint.strategies.base import Context
    from hoolint.strategies.docs_ import ProsePatternStrategy
    from hoolint.findings import Finding
    md = tmp_path / "doc.md"
    md.write_text("anything\n")
    ctx = Context(path=md, root=tmp_path, mode="git", settings={},
                  rule_id="em-dashes", severity="warn")
    keep = Finding(rule_id="r", file="doc.md", start_line=1, end_line=1,
                   span_text="has — dash", message="m")
    drop = Finding(rule_id="r", file="doc.md", start_line=2, end_line=2,
                   span_text="clean line", message="m")
    out = ProsePatternStrategy().run([keep, drop], {"pattern": "—"}, ctx)
    assert out == [keep]


def test_shipped_defaults_flag_leverage_and_utilize(tmp_path):
    """Both stems, and their inflections, in one line each."""
    from hoolint.config import load_config
    md = tmp_path / "doc.md"
    md.write_text("Leverage the cache here.\nThe view utilizes a serializer.\n"
                  "It leveraged nothing and we are utilizing none of it.\n")
    found = run(load_config(tmp_path), [md], tmp_path, "git")
    assert {f.start_line for f in found} == {1, 2, 3}
    assert {f.rule_id for f in found} == {"use-not-leverage"}
    assert found[0].message == "say 'use'"


def test_utilization_is_not_flagged(tmp_path):
    """`utilization` is domain vocabulary, and appears inside test ids.

    Measured over 1.29M prose lines it was the single largest form (248 hits) and
    every sampled one was legitimate: "connection pool utilization", "Budget
    Utilization" cards, `data-testid="export-utilization-button"`.
    """
    from hoolint.config import load_config
    md = tmp_path / "doc.md"
    md.write_text("Connection pool utilization should stay below 80%.\n")
    assert run(load_config(tmp_path), [md], tmp_path, "git") == []


def test_leverage_inside_a_fence_is_not_flagged(tmp_path):
    from hoolint.config import load_config
    md = tmp_path / "doc.md"
    md.write_text("Fine prose.\n\n```python\nleverage = compute_leverage()\n```\n")
    assert run(load_config(tmp_path), [md], tmp_path, "git") == []


def test_shipped_defaults_flag_an_em_dash(tmp_path):
    """The rule users get, not a hand-built copy of it.

    test_semantic_calibration.py used to assert against a threshold it computed
    itself, so it never checked the shipped value. Same trap here.
    """
    from hoolint.config import load_config
    md = tmp_path / "doc.md"
    md.write_text("Plain prose with an em dash — right here.\n")
    found = run(load_config(tmp_path), [md], tmp_path, "git")
    assert [f.rule_id for f in found] == ["em-dashes"]
    assert "em dash" in found[0].message
