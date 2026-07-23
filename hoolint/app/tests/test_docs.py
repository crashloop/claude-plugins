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
