"""Tests for build_report: python -m pytest, or python test_build_report.py."""
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import build_report as br

HERE = Path(__file__).parent
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9aw"
    "AAAABJRU5ErkJggg=="
)


def minimal(**over):
    """Return the smallest valid findings document, with overrides."""
    doc = {
        "target": "https://example.test",
        "title": "example.test: trust audit",
        "lede": "An outside-in review.",
        "date": "2026-11-06",
        "summary": {"lead": "The site is clean.", "bullets": ["**No malware** found."]},
        "domains": [{"key": "mkt", "name": "Marketing and SEO"},
                    {"key": "bp", "name": "Best practices"}],
        "sections": [{"id": "message", "title": "Message", "blocks": [
            {"p": "Headline reads `We attack you first`."},
            {"table": {"head": ["Check", "Result"],
                       "rows": [["Cookies", {"text": "None", "tone": "ok"}]]}},
        ]}],
        "personas": [{"name": "A potential customer", "tone": "no",
                      "verdict": "Leaves without writing.",
                      "fields": [["What I see", "A stranger."]]}],
        "issues": [
            {"id": "M1", "domain": "mkt", "severity": "high", "title": "Threat headline",
             "evidence": "We attack you first", "fix": "Add consent"},
            {"id": "M2", "domain": "mkt", "severity": "low", "title": "Weak title",
             "evidence": "Coming soon", "fix": "Describe the service"},
            {"id": "B1", "domain": "bp", "severity": "medium", "title": "Console error",
             "evidence": "CSP blocks beacon", "fix": "Disable beacon"},
        ],
    }
    doc.update(over)
    return doc


def test_counts_per_domain_and_total():
    counts = br.count_issues(minimal())
    assert counts["mkt"] == {"critical": 0, "high": 1, "medium": 0, "low": 1}
    assert counts["bp"] == {"critical": 0, "high": 0, "medium": 1, "low": 0}
    assert br.total(counts) == {"critical": 0, "high": 1, "medium": 1, "low": 1}


def test_render_contains_counts_table_last_and_personas():
    html = br.render(minimal())
    assert html.index('id="personas"') < html.index('id="register"') < html.index('id="counts"')
    assert html.rstrip().endswith("</html>")
    counts_part = html[html.index('id="counts"'):]
    assert "Marketing and SEO" in counts_part and "All domains" in counts_part
    assert "<td>3</td>" in counts_part  # grand total
    assert "Leaves without writing." in html
    assert "3 in total: 0 critical, 1 high, 1 medium, 1 low" in html


def test_inline_markup_and_escaping():
    doc = minimal()
    doc["sections"][0]["blocks"].append({"p": "<script>alert(1)</script> **bold** `x<y`"})
    html = br.render(doc)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<strong>bold</strong>" in html and "<code>x&lt;y</code>" in html


def test_toned_cells_and_code_block():
    doc = minimal()
    doc["sections"][0]["blocks"].append({"code": "v=DMARC1; p=none", "lang": "dns"})
    html = br.render(doc)
    assert '<td class="t-ok">None</td>' in html
    assert "<pre><code>v=DMARC1; p=none</code></pre>" in html


def test_validation_rejects_bad_input():
    bad_cases = [
        minimal(issues=[{"id": "X", "domain": "mkt", "severity": "urgent", "title": "t",
                         "evidence": "e", "fix": "f"}]),
        minimal(issues=[{"id": "X", "domain": "nope", "severity": "low", "title": "t",
                         "evidence": "e", "fix": "f"}]),
        minimal(issues=minimal()["issues"] + [dict(minimal()["issues"][0])]),
        minimal(personas=[{"name": "x", "tone": "maybe", "verdict": "v", "fields": []}]),
        {k: v for k, v in minimal().items() if k != "target"},
    ]
    for doc in bad_cases:
        try:
            br.validate(doc)
        except br.FindingsError:
            continue
        raise AssertionError(f"accepted invalid doc: {doc.get('issues', doc.keys())}")


def test_screenshot_embedded_as_data_uri():
    with tempfile.TemporaryDirectory() as d:
        shot = Path(d) / "s.png"
        shot.write_bytes(PNG_1PX)
        doc = minimal(screenshots=[{"path": str(shot), "alt": "Home", "caption": "Desktop",
                                    "width": 1}])
        html = br.render(doc)
        assert 'src="data:image/' in html and 'alt="Home"' in html


def test_cli_writes_file_and_fails_fast_on_invalid():
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "f.json", Path(d) / "r.html"
        src.write_text(json.dumps(minimal()))
        ok = subprocess.run([sys.executable, str(HERE / "build_report.py"), str(src), str(out)],
                            capture_output=True, text=True)
        assert ok.returncode == 0, ok.stderr
        assert out.read_text().startswith("<!doctype html>")
        src.write_text(json.dumps(minimal(domains=[])))
        bad = subprocess.run([sys.executable, str(HERE / "build_report.py"), str(src), str(out)],
                             capture_output=True, text=True)
        assert bad.returncode == 2 and "domain" in bad.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
