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
