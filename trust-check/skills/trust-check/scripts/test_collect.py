"""Tests for collect: python -m pytest, or python test_collect.py.

The end-to-end test serves a tiny site from localhost; no external host is contacted.
"""
import http.server
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import collect as co

HERE = Path(__file__).parent
WOFF2 = b"wOF2" + b"\0" * 60

HOME = b"""<!doctype html><html lang="en"><head><title>Acme | Coming soon</title>
<meta name="description" content="We test things.">
<meta property="og:image" content="/og.png">
<link rel="stylesheet" href="/a.css"><link rel="icon" href="/fav.svg">
<script defer src="https://cdn.example.net/track.js" data-id="1"></script>
</head><body><h1>We attack you first.</h1><p>Mail <a href="mailto:hi@acme.test">us</a>.
<a href="/privacy">Privacy</a> <a href="https://news.example.org/x">News</a></p>
<img src="/og.png" alt=""></body></html>"""
PRIVACY = b"<html><body><h1>Privacy</h1><p>We set no cookies.</p></body></html>"
CSS = b"@font-face{src:url(/f.woff2) format('woff2')}body{background:url('/og.png')}"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20


class Site(http.server.BaseHTTPRequestHandler):
    """Tiny fixture site: two pages, assets, a redirecting unknown path."""

    ROUTES = {
        "/": ("text/html", HOME), "/privacy": ("text/html", PRIVACY),
        "/a.css": ("text/css", CSS), "/f.woff2": ("font/woff2", WOFF2),
        "/og.png": ("image/png", PNG), "/fav.svg": ("image/svg+xml", b"<svg/>"),
        "/robots.txt": ("text/plain", b"User-agent: *\nSitemap: /sitemap.xml\n"),
        "/.well-known/security.txt": ("text/plain", b"Contact: mailto:hi@acme.test\n"),
    }

    def do_GET(self):  # noqa: N802 (http.server API)
        path = self.path.split("?")[0]
        if path in self.ROUTES:
            ctype, body = self.ROUTES[path]
            if path == "/" and "text/html" in self.headers.get("Accept", ""):
                body = body.replace(b"</body>", b"<script src='/beacon.js'></script></body>")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Security-Policy", "default-src 'self'")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()

    def log_message(self, format, *args):  # noqa: A002 (http.server API)
        del format, args


def test_parse_refs_classifies_same_origin_and_third_party():
    refs = co.parse_refs(HOME.decode(), "https://acme.test/")
    assert "https://cdn.example.net/track.js" in refs["scripts"]
    assert "https://acme.test/a.css" in refs["styles"]
    assert "https://acme.test/og.png" in refs["images"]
    assert "https://acme.test/privacy" in refs["pages"]
    assert "mailto:hi@acme.test" in refs["mailto"]
    assert "https://news.example.org/x" in refs["outbound"]
    assert refs["meta"]["description"] == "We test things."
    assert refs["script_attrs"][0]["data-id"] == "1"


def test_bare_origin_is_normalised_to_root():
    assert co._clean("https://acme.test") == "https://acme.test/"
    assert co._clean("https://acme.test/a#top") == "https://acme.test/a"
    assert co._clean("mailto:x@acme.test") == "mailto:x@acme.test"


def test_css_urls_and_magic():
    assert co.css_urls(CSS.decode(), "https://acme.test/a.css") == [
        "https://acme.test/f.woff2", "https://acme.test/og.png"]
    assert co.magic(WOFF2) == "woff2" and co.magic(PNG) == "png"
    assert co.magic(b"<svg/>") == "svg" and co.magic(b"\0\1") == "unknown"


def test_security_headers_report():
    rep = co.header_report({"strict-transport-security": "max-age=1",
                            "set-cookie": "a=b", "x-content-type-options": "nosniff"})
    assert rep["present"]["strict-transport-security"] == "max-age=1"
    assert "content-security-policy" in rep["missing"]
    assert rep["sets_cookie"] is True


def test_visible_text_drops_scripts_and_styles():
    html = "<p>Hello <b>you</b></p><script>x=1</script><style>p{}</style><p>Bye</p>"
    assert co.visible_text(html) == "Hello you\nBye"


def test_end_to_end_against_local_site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        with tempfile.TemporaryDirectory() as d:
            run = subprocess.run([sys.executable, "-I", str(HERE / "collect.py"), url, d,
                                  "--no-dns", "--no-archive"],
                                 capture_output=True, text=True, timeout=120)
            assert run.returncode == 0, run.stderr
            ev = json.loads((Path(d) / "evidence.json").read_text())
            pages = {p["url"]: p for p in ev["pages"]}
            assert url in pages and url + "privacy" in pages
            assert (Path(d) / pages[url]["text_file"]).read_text().startswith("We attack")
            kinds = {a["url"].rsplit("/", 1)[-1]: a["magic"] for a in ev["assets"]}
            assert kinds["f.woff2"] == "woff2" and kinds["og.png"] == "png"
            assert kinds["a.css"] == "css"
            assert len(pages) == 2, list(pages)
            assert any(t["url"].endswith("track.js") for t in ev["third_party_scripts"])
            assert ev["robots"]["status"] == 200 and ev["security_txt"]["status"] == 200
            probes = {p["path"]: p for p in ev["probes"]}
            assert probes["/sw.js"]["status"] == 302 and probes["/sw.js"]["offsite"] is False
            cloak = ev["cloaking"]
            assert len({v["sha256"] for v in cloak["variants"]}) == 2
            assert cloak["differs_on"] == ["accept"]
            assert "strict-transport-security" in ev["headers"]["missing"]
            for f in Path(d, "raw").rglob("*"):
                assert not f.is_file() or f.stat().st_mode & 0o111 == 0, f"executable: {f}"
    finally:
        srv.shutdown()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
