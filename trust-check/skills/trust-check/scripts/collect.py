"""Passive evidence collector for a trust check. Standard library only.

Fetches a site the way a visitor would and records what a reviewer needs: pages and their
visible text, every same-origin asset with its hash and file signature, third-party scripts
(saved as text, never executed), security headers, a small fixed list of well-known paths,
cloaking variants of the homepage, DNS, whois and web-archive history.

It is deliberately passive: ordinary GET requests, a bounded page crawl, no fuzzing, no
forms, no logins. Everything downloaded is untrusted data; nothing here runs it.

Usage:
    python -I collect.py https://example.com OUTDIR [--max-pages 10] [--no-dns] [--no-archive]
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

TIMEOUT = 20
MAX_BYTES = 5 * 1024 * 1024  # per file; larger responses are truncated and flagged
CHROME = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/130.0 Safari/537.36")
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
BASE_HEADERS = {"User-Agent": CHROME, "Accept": HTML_ACCEPT, "Accept-Language": "en",
                "Accept-Encoding": "identity"}
# One dimension changes per variant, so a hash difference names its cause.
CLOAK_VARIANTS = [
    ("browser", "base", {}),
    ("curl", "ua", {"User-Agent": "curl/8.5.0"}),
    ("iphone", "ua", {"User-Agent": IPHONE}),
    ("googlebot", "ua", {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; "
                                       "+http://www.google.com/bot.html)"}),
    ("linkedinbot", "ua", {"User-Agent": "LinkedInBot/1.0 (compatible; Mozilla/5.0)"}),
    ("no-accept", "accept", {"Accept": "*/*"}),
    ("lang-it", "lang", {"Accept-Language": "it"}),
    ("from-google", "referer", {"Referer": "https://www.google.com/"}),
    ("from-linkedin", "referer", {"Referer": "https://www.linkedin.com/"}),
]
# Bounded and fixed: well-known files plus two redirect checks. Not a directory scan.
PROBES = ["/robots.txt", "/sitemap.xml", "/.well-known/security.txt", "/security.txt",
          "/humans.txt", "/ads.txt", "/manifest.json", "/site.webmanifest", "/sw.js",
          "/service-worker.js", "/favicon.ico", "/trust-check-unknown-path",
          "/?next=https://example.com/", "/trust-check-unknown-path?url=https://example.com/"]
SECURITY_HEADERS = ["content-security-policy", "strict-transport-security",
                    "x-content-type-options", "referrer-policy", "permissions-policy",
                    "x-frame-options", "cross-origin-opener-policy"]
DNS_TYPES = ["A", "AAAA", "NS", "MX", "TXT", "CAA", "SOA"]
DKIM_SELECTORS = ["default", "google", "selector1", "selector2", "s1", "s2", "k1", "k2",
                  "dkim", "mail", "smtp", "key1", "key2", "mx", "aruba", "cf2024-1",
                  "cf-bounce", "zoho", "protonmail", "mandrill", "sendgrid", "amazonses"]
TEXT_TYPES = {"text/css": "css", "text/javascript": "js", "application/javascript": "js",
              "text/plain": "text", "application/json": "json"}
SKIP_TEXT = {"script", "style", "noscript", "template", "svg", "title", "head"}
BLOCKS = {"p", "div", "section", "article", "header", "footer", "main", "nav", "li", "ul",
          "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "td", "th", "br",
          "blockquote", "figcaption", "form", "dt", "dd", "pre"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch(url, headers=None, follow=True):
    """GET a URL and record the redirect chain without trusting it.

    Args:
        url: Absolute http(s) URL.
        headers: Request headers; defaults to a desktop browser.
        follow: Follow up to five redirects when true.

    Returns:
        dict with url, status, headers (lowercase keys), body (bytes), redirects, truncated,
        and error when the request failed.
    """
    hdrs = {**BASE_HEADERS, **(headers or {})}
    chain, current = [], url
    for _ in range(6):
        req = urllib.request.Request(current, headers=hdrs)
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as resp:
                status, rh, body = resp.status, resp.headers, resp.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status, rh, body = exc.code, exc.headers, exc.read(MAX_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"url": url, "final_url": current, "status": None, "headers": {},
                    "body": b"", "redirects": chain, "error": str(exc), "truncated": False}
        lower = {k.lower(): v for k, v in rh.items()}
        if "set-cookie" in lower:
            lower["set-cookie"] = rh.get_all("Set-Cookie")
        location = lower.get("location")
        if follow and status in (301, 302, 303, 307, 308) and location:
            chain.append({"status": status, "from": current, "to":
                          urllib.parse.urljoin(current, location)})
            current = chain[-1]["to"]
            continue
        return {"url": url, "final_url": current, "status": status, "headers": lower,
                "body": body[:MAX_BYTES], "redirects": chain,
                "truncated": len(body) > MAX_BYTES}
    return {"url": url, "final_url": current, "status": None, "headers": {}, "body": b"",
            "redirects": chain, "error": "too many redirects", "truncated": False}


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {k.lower(): (v or "") for k, v in attrs}))


def _same_origin(a, b):
    pa, pb = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def _clean(url):
    """Drop the fragment and give a bare origin its root path, so / is crawled once."""
    parts = urllib.parse.urlsplit(urllib.parse.urldefrag(url)[0])
    if parts.scheme in ("http", "https") and not parts.path:
        parts = parts._replace(path="/")
    return urllib.parse.urlunsplit(parts)


def parse_refs(html, base):
    """Extract every reference a page makes.

    Args:
        html: Page source.
        base: The page URL, for resolving relative references.

    Returns:
        dict of lists: scripts, styles, images, pages (same-origin links), outbound,
        mailto, other_links; plus meta (name/property to content), script_attrs (attributes
        of each external script), inline_scripts (count) and forms (count).
    """
    p = _Refs()
    p.feed(html)
    out: dict = {k: [] for k in ("scripts", "styles", "images", "pages", "outbound", "mailto",
                           "other_links", "script_attrs")}
    out.update(meta={}, inline_scripts=0, forms=0, iframes=[])

    def add(key, value):
        if value and value not in out[key]:
            out[key].append(value)

    for tag, a in p.tags:
        if tag == "script":
            if a.get("src"):
                add("scripts", _clean(urllib.parse.urljoin(base, a["src"])))
                out["script_attrs"].append(a)
            else:
                out["inline_scripts"] += 1
        elif tag == "link":
            rel, href = a.get("rel", "").lower(), a.get("href")
            if not href:
                continue
            absu = _clean(urllib.parse.urljoin(base, href))
            if "stylesheet" in rel:
                add("styles", absu)
            elif "icon" in rel:
                add("images", absu)
        elif tag == "img" and a.get("src"):
            add("images", _clean(urllib.parse.urljoin(base, a["src"])))
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                out["meta"][key] = a.get("content", "")
                if key in ("og:image", "twitter:image") and a.get("content"):
                    add("images", _clean(urllib.parse.urljoin(base, a["content"])))
        elif tag == "a" and a.get("href"):
            href = a["href"].strip()
            if href.lower().startswith("mailto:") or href.lower().startswith("tel:"):
                add("mailto", href)
                continue
            absu = _clean(urllib.parse.urljoin(base, href))
            if not absu.startswith(("http://", "https://")):
                add("other_links", href)
            elif _same_origin(absu, base):
                add("pages", absu)
            else:
                add("outbound", absu)
        elif tag == "form":
            out["forms"] += 1
        elif tag == "iframe" and a.get("src"):
            out["iframes"].append(urllib.parse.urljoin(base, a["src"]))
    return out


def css_urls(css, base):
    """Return absolute url() and @import targets of a stylesheet, in order, deduplicated."""
    found = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", css)
    found += re.findall(r"@import\s+['\"]([^'\"]+)['\"]", css)
    out = []
    for u in found:
        if u.startswith("data:"):
            continue
        absu = _clean(urllib.parse.urljoin(base, u))
        if absu not in out:
            out.append(absu)
    return out


def magic(data):
    """Name a file type from its first bytes."""
    sigs = [(b"wOF2", "woff2"), (b"wOFF", "woff"), (b"\x89PNG\r\n\x1a\n", "png"),
            (b"\xff\xd8\xff", "jpeg"), (b"GIF8", "gif"), (b"%PDF", "pdf"),
            (b"PK\x03\x04", "zip"), (b"\x7fELF", "elf"), (b"MZ", "exe"),
            (b"\x00\x00\x01\x00", "ico")]
    for sig, name in sigs:
        if data.startswith(sig):
            return name
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "svg"
    if head.startswith((b"<!doctype html", b"<html")):
        return "html"
    return "unknown"


def header_report(headers):
    """Summarise security headers.

    Args:
        headers: Response headers with lowercase keys.

    Returns:
        dict with present (name to value), missing (names) and sets_cookie.
    """
    present = {h: headers[h] for h in SECURITY_HEADERS if h in headers}
    csp = headers.get("content-security-policy", "")
    missing = [h for h in SECURITY_HEADERS if h not in headers
               and not (h == "x-frame-options" and "frame-ancestors" in csp)]
    return {"present": present, "missing": missing, "sets_cookie": "set-cookie" in headers}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        del attrs
        if tag in SKIP_TEXT:
            self.skip += 1
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TEXT:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible_text(html):
    """Return the text a visitor sees, one block per line."""
    p = _Text()
    p.feed(html)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.parts).split("\n"))
    return "\n".join(ln for ln in lines if ln)


def _slug(url):
    path = urllib.parse.urlsplit(url).path.strip("/") or "index"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", path)[:80]


def _save(out, rel, data):
    """Write data under OUTDIR as a non-executable file; return the path relative to OUTDIR."""
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o644)
    return rel


def _record(res):
    body = res["body"]
    return {"url": res["url"], "final_url": res["final_url"], "status": res["status"],
            "redirects": res["redirects"], "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "truncated": res["truncated"],
            "content_type": res["headers"].get("content-type"),
            "cache_control": res["headers"].get("cache-control"),
            **({"error": res["error"]} if res.get("error") else {})}


def crawl(start, out, max_pages):
    """Fetch same-origin pages breadth-first and their assets."""
    pages, assets, third, queue, seen = [], {}, {}, [start], set()
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        res = fetch(url)
        rec = _record(res)
        ctype = (rec["content_type"] or "").lower()
        if res["status"] != 200 or "html" not in ctype:
            pages.append(rec)
            continue
        html = res["body"].decode("utf-8", "replace")
        refs = parse_refs(html, res["final_url"])
        slug = _slug(url)
        rec.update(raw_file=_save(out, f"raw/pages/{slug}.html", res["body"]),
                   text_file=_save(out, f"text/{slug}.txt",
                                   visible_text(html).encode()),
                   title=(re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
                          or [None, None])[1],
                   headers=res["headers"], refs=refs)
        pages.append(rec)
        queue += [p for p in refs["pages"] if p not in seen and _same_origin(p, start)]
        for u in refs["styles"] + refs["images"] + refs["scripts"]:
            bucket = assets if _same_origin(u, start) else third
            bucket.setdefault(u, None)
    for u in list(assets):
        assets[u] = _asset(u, out, "raw/assets")
        if (assets[u].get("content_type") or "").startswith("text/css"):
            css = (out / assets[u]["file"]).read_text("utf-8", "replace")
            for v in css_urls(css, u):
                if _same_origin(v, start) and v not in assets:
                    assets[v] = _asset(v, out, "raw/assets")
                elif not _same_origin(v, start):
                    third.setdefault(v, None)
    third_rec = [_asset(u, out, "raw/third_party") for u in third if not u.endswith((
        ".png", ".jpg", ".svg", ".gif", ".webp"))]
    return pages, list(assets.values()), third_rec


def _asset(url, out, sub):
    res = fetch(url, {"Accept": "*/*"})
    rec = _record(res)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", urllib.parse.urlsplit(url).netloc + "_"
                  + urllib.parse.urlsplit(url).path)[-120:]
    kind = magic(res["body"])
    ctype = (rec["content_type"] or "").split(";")[0].strip()
    if kind == "unknown" and ctype in TEXT_TYPES:
        kind = TEXT_TYPES[ctype]
    rec.update(magic=kind, file=_save(out, f"{sub}/{name}", res["body"]),
               headers={k: v for k, v in res["headers"].items()
                        if k in ("content-type", "cache-control", "last-modified", "etag",
                                 "set-cookie", "access-control-allow-origin")})
    return rec


def probes(start):
    """Request the fixed list of well-known paths without following redirects."""
    host = urllib.parse.urlsplit(start).netloc
    out = []
    for path in PROBES:
        res = fetch(urllib.parse.urljoin(start, path), {"Accept": "*/*"}, follow=False)
        loc = res["headers"].get("location")
        target = urllib.parse.urljoin(start, loc) if loc else None
        out.append({"path": path, "status": res["status"], "location": target,
                    "offsite": bool(target and urllib.parse.urlsplit(target).netloc != host),
                    "bytes": len(res["body"]), "content_type": res["headers"].get("content-type"),
                    "body": res["body"][:4000].decode("utf-8", "replace")
                    if res["status"] == 200 and len(res["body"]) < 64000 else None})
    return out


def cloaking(start):
    """Fetch the homepage once per variant and report which dimensions change it."""
    variants = []
    for name, dim, extra in CLOAK_VARIANTS:
        res = fetch(start, extra)
        variants.append({"name": name, "dimension": dim, "status": res["status"],
                         "bytes": len(res["body"]), "final_url": res["final_url"],
                         "sha256": hashlib.sha256(res["body"]).hexdigest()})
    base = variants[0]["sha256"]
    differs = sorted({v["dimension"] for v in variants if v["sha256"] != base})
    return {"variants": variants, "differs_on": differs}


def _run(cmd):
    if not shutil.which(cmd[0]):
        return None
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None


def dns(domain):
    """Query public DNS records with dig; returns None values when dig is unavailable."""
    if not shutil.which("dig"):
        return {"available": False}
    q = lambda name, t: [ln.strip() for ln in (_run(["dig", "+short", t, name]) or "")
                         .splitlines() if ln.strip()]
    out = {"available": True, "records": {t: q(domain, t) for t in DNS_TYPES}}
    out["dmarc"] = q(f"_dmarc.{domain}", "TXT")
    out["mta_sts"] = q(f"_mta-sts.{domain}", "TXT")
    out["tls_rpt"] = q(f"_smtp._tls.{domain}", "TXT")
    out["bimi"] = q(f"default._bimi.{domain}", "TXT")
    out["dkim"] = {s: r for s in DKIM_SELECTORS if (r := q(f"{s}._domainkey.{domain}", "TXT"))}
    out["www"] = q(f"www.{domain}", "A")
    return out


def whois(domain):
    """Return selected whois lines (dates, registrar, status) or None."""
    text = _run(["whois", domain])
    if text is None:
        return None
    keep = re.compile(r"(creat|regist|expir|updated|status|name server|registrant)", re.I)
    return [ln.strip() for ln in text.splitlines() if keep.search(ln) and ":" in ln][:40]


def archive(domain):
    """List web-archive captures of the domain root from the CDX API."""
    url = (f"https://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(domain)}"
           "&output=json&limit=60&fl=timestamp,original,statuscode,mimetype,digest")
    res = fetch(url, {"Accept": "application/json"})
    try:
        rows = json.loads(res["body"] or b"[]")
    except json.JSONDecodeError:
        return {"error": f"status {res['status']}"}
    return [dict(zip(rows[0], r)) for r in rows[1:]] if rows else []


def collect(start, out, max_pages=10, use_dns=True, use_archive=True):
    """Gather all passive evidence for one site and write OUTDIR/evidence.json."""
    out.mkdir(parents=True, exist_ok=True)
    domain = urllib.parse.urlsplit(start).hostname or ""
    pages, assets, third = crawl(start, out, max_pages)
    home = next((p for p in pages if p["url"] == start), pages[0] if pages else {})
    probe = probes(start)
    by_path = {p["path"]: p for p in probe}
    sec = by_path["/.well-known/security.txt"]
    if sec["status"] != 200:
        sec = by_path["/security.txt"]
    ev = {
        "target": start, "domain": domain, "tool": "trust-check collect.py",
        "pages": pages, "assets": assets, "third_party_scripts": third,
        "headers": {**header_report(home.get("headers", {})), "raw": home.get("headers", {})},
        "robots": by_path["/robots.txt"], "security_txt": sec,
        "sitemap": by_path["/sitemap.xml"], "probes": probe, "cloaking": cloaking(start),
        "dns": dns(domain) if use_dns else {"skipped": True},
        "whois": whois(domain) if use_dns else None,
        "archive": archive(domain) if use_archive else {"skipped": True},
    }
    (out / "evidence.json").write_text(json.dumps(ev, indent=1, default=str))
    return ev


def main(argv=None):
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description="Passive evidence collector for a trust check.")
    ap.add_argument("url")
    ap.add_argument("outdir")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--no-dns", action="store_true", help="skip dig and whois")
    ap.add_argument("--no-archive", action="store_true", help="skip the web archive")
    a = ap.parse_args(argv)
    if not a.url.startswith(("http://", "https://")):
        ap.error("url must start with http:// or https://")
    ev = collect(_clean(a.url), Path(a.outdir), a.max_pages, not a.no_dns, not a.no_archive)
    print(f"evidence: {len(ev['pages'])} pages, {len(ev['assets'])} assets, "
          f"{len(ev['third_party_scripts'])} third-party scripts, cloaking differs on "
          f"{ev['cloaking']['differs_on'] or 'nothing'} -> {Path(a.outdir) / 'evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
