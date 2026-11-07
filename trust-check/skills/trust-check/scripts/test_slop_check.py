"""Tests for slop_check: python -m pytest, or python test_slop_check.py."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import slop_check as sc

HERE = Path(__file__).parent

SLOPPY = (
    "Here's the thing: it turns out we really leverage the landscape. "
    "It's not a tool, it's a mindset. What matters is speed, quality, and cost. "
    "Mistakes were made. Nobody saw it coming — truly."
)
CLEAN = "We test your external servers. You get a report within five days."


def test_flags_listed_patterns():
    r = sc.check_text(SLOPPY)
    assert "here's" in r["phrases"] and "it turns out" in r["phrases"]
    assert "landscape" in r["phrases"]
    assert {"really", "truly"} <= set(r["adverbs"])
    assert r["em_dashes"] == 1
    assert "nobody" in r["extremes"]
    assert any("not a tool" in c for c in r["contrasts"])
    assert any(s.startswith("What") for s in r["wh_starts"])
    assert r["passives"]
    assert r["three_lists"]


def test_clean_text_has_no_flags():
    r = sc.check_text(CLEAN)
    for key in ("phrases", "adverbs", "extremes", "contrasts", "wh_starts", "passives"):
        assert not r[key], (key, r[key])
    assert r["em_dashes"] == 0


def test_html_extraction_skips_scripts_and_keeps_blocks():
    html = ("<html><head><title>T</title><script>var really=1</script></head><body>"
            "<h1>We attack.<br>So nobody can.</h1><p>Report goes to you, not to them.</p>"
            "<style>.x{}</style></body></html>")
    blocks = sc.extract_blocks(html)
    texts = [t for _, t in blocks]
    assert "We attack. So nobody can." in texts
    assert not any("var really" in t for t in texts)
    r = sc.check_blocks(blocks)
    assert r["contrasts"] and r["punchy_endings"] == [1, 1]


def test_cli_outputs_json():
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "p.html"
        page.write_text(f"<p>{SLOPPY}</p>")
        out = subprocess.run([sys.executable, str(HERE / "slop_check.py"), "--json", str(page)],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        data = json.loads(out.stdout)
        assert data[0]["file"] == str(page) and data[0]["words"] > 10


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
