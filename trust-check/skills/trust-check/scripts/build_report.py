"""Render a trust-check findings document as one self-contained HTML report.

The findings JSON is validated first; any schema error exits with status 2 and a message
naming the field. Issue counts per domain are computed here, never typed by hand.
All text is HTML-escaped (page content is untrusted); **bold** and `code` are the only
inline markup. Screenshots are embedded as data URIs, so the report is a single file.

Usage:
    python -I build_report.py findings.json report.html
"""
import base64
import html
import io
import json
import re
import sys
from pathlib import Path

SEVERITIES = ("critical", "high", "medium", "low")
TONES = {"ok", "warn", "bad", "dim"}
PERSONA_TONES = {"no", "hold", "go"}
REQUIRED = ("target", "title", "date", "summary", "domains", "sections", "personas", "issues")
ISSUE_KEYS = ("id", "domain", "severity", "title", "evidence", "fix")
RESERVED_IDS = {"summary", "personas", "limits", "corrections", "sources", "register", "counts"}
SEVERITY_HELP = {
    "critical": "Stops a buyer from hiring, or creates legal exposure now.",
    "high": "Likely to lose a qualified buyer or cause real damage.",
    "medium": "Weakens the result; fix before the full launch.",
    "low": "Polish.",
}


class FindingsError(ValueError):
    """Raised when a findings document breaks the schema."""


def _need(cond, msg):
    if not cond:
        raise FindingsError(msg)


def validate(doc):
    """Check a findings document against the schema.

    Args:
        doc: Parsed findings JSON.

    Raises:
        FindingsError: On the first field that breaks the schema.
    """
    for key in REQUIRED:
        _need(key in doc, f"missing top-level field '{key}'")
    keys = [d.get("key") for d in doc["domains"]]
    _need(keys, "domain list is empty: define at least one domain")
    _need(len(set(keys)) == len(keys), "duplicate domain key")
    seen = set()
    for i, issue in enumerate(doc["issues"]):
        for key in ISSUE_KEYS:
            _need(key in issue, f"issue {i} lacks '{key}'")
        _need(issue["severity"] in SEVERITIES,
              f"issue {issue['id']}: severity '{issue['severity']}' not in {SEVERITIES}")
        _need(issue["domain"] in keys, f"issue {issue['id']}: unknown domain '{issue['domain']}'")
        _need(issue["id"] not in seen, f"duplicate issue id '{issue['id']}'")
        seen.add(issue["id"])
    for p in doc["personas"]:
        _need(p.get("tone") in PERSONA_TONES, f"persona '{p.get('name')}': tone not in "
              f"{sorted(PERSONA_TONES)}")
        _need(p.get("verdict"), f"persona '{p.get('name')}' has no verdict")
    ids = set()
    for s in doc["sections"]:
        _need(s.get("id") and s.get("title"), "section without id or title")
        _need(s["id"] not in ids | RESERVED_IDS,
              f"section id '{s['id']}' is duplicated or reserved")
        ids.add(s["id"])
        for b in s.get("blocks", []):
            _need(isinstance(b, dict) and len(set(b) - {"lang", "kind"}) == 1,
                  f"section '{s['id']}': each block holds exactly one kind")


def count_issues(doc):
    """Count issues per domain and severity.

    Returns:
        {domain_key: {severity: count}} for every declared domain, zeros included.
    """
    counts = {d["key"]: dict.fromkeys(SEVERITIES, 0) for d in doc["domains"]}
    for issue in doc["issues"]:
        counts[issue["domain"]][issue["severity"]] += 1
    return counts


def total(counts):
    """Sum per-domain counts into one {severity: count} dict."""
    return {s: sum(c[s] for c in counts.values()) for s in SEVERITIES}


def inline(text):
    """Escape text, then render **bold** and `code` spans."""
    out = html.escape(str(text), quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)


def _cell(value, tag="td"):
    if isinstance(value, dict):
        tone = value.get("tone")
        cls = f' class="t-{tone}"' if tone in TONES else ""
        return f"<{tag}{cls}>{inline(value.get('text', ''))}</{tag}>"
    return f"<{tag}>{inline(value)}</{tag}>"


def _table(head, rows, cls=""):
    attr = f' class="{cls}"' if cls else ""
    out = [f'<div class="tw"><table{attr}>', "<tr>" + "".join(_cell(h, "th") for h in head)
           + "</tr>"]
    out += ["<tr>" + "".join(_cell(c) for c in row) + "</tr>" for row in rows]
    return "\n".join(out + ["</table></div>"])


def block(b):
    """Render one content block: p, h3, ul, ol, note, code or table."""
    if "p" in b:
        return f"<p>{inline(b['p'])}</p>"
    if "h3" in b:
        return f"<h3>{inline(b['h3'])}</h3>"
    if "ul" in b or "ol" in b:
        tag = "ul" if "ul" in b else "ol"
        return f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in b[tag]) + f"</{tag}>"
    if "note" in b:
        kind = " warn" if b.get("kind") == "warn" else ""
        return f'<div class="note{kind}">{inline(b["note"])}</div>'
    if "code" in b:
        return f"<pre><code>{html.escape(b['code'], quote=False)}</code></pre>"
    if "table" in b:
        return _table(b["table"]["head"], b["table"]["rows"])
    raise FindingsError(f"unknown block kind: {sorted(b)}")


def _image_uri(path, width):
    raw = Path(path).read_bytes()
    try:
        from PIL import Image  # optional: shrink large screenshots
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if width and img.width > width:
            img = img.resize((width, round(img.height * width / img.width)))
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=80)
        return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return "data:image/png;base64," + base64.b64encode(raw).decode()


def _section(num, sid, title, body):
    return (f'<h2 id="{html.escape(sid)}"><span class="n">{num:02d}</span>{inline(title)}</h2>\n'
            + body)


def _persona(p):
    rows = "".join(f"<dt>{inline(k)}</dt><dd>{inline(v)}</dd>" for k, v in p.get("fields", []))
    extra = "".join(block(b) for b in p.get("blocks", []))
    return (f'<article class="card"><h3>{inline(p["name"])}</h3>'
            f'<p class="verdict v-{p["tone"]}">Verdict: {inline(p["verdict"])}</p>'
            f"<dl>{rows}</dl>{extra}</article>")


def _register(doc):
    names = {d["key"]: d["name"] for d in doc["domains"]}
    order = {s: i for i, s in enumerate(SEVERITIES)}
    out = ["<ul>"] + [f'<li><span class="sev s-{s}">{s.title()}</span> {SEVERITY_HELP[s]}</li>'
                      for s in SEVERITIES] + ["</ul>"]
    for key, name in names.items():
        items = sorted((i for i in doc["issues"] if i["domain"] == key),
                       key=lambda i: order[i["severity"]])
        if not items:
            continue
        rows = [[i["id"], {"text": i["severity"].title(), "tone": i["severity"]},
                 i["title"], i["evidence"], i["fix"]] for i in items]
        table = _table(["ID", "Severity", "Issue", "Evidence", "Fix"], rows)
        table = re.sub(r'<td class="t-(critical|high|medium|low)">(\w+)</td>',
                       r'<td><span class="sev s-\1">\2</span></td>', table)
        out += [f"<h3>{inline(name)}</h3>", table]
    return "\n".join(out)


def _counts_table(doc):
    counts = count_issues(doc)
    rows = []
    for d in doc["domains"]:
        c = counts[d["key"]]
        rows.append(f"<tr><td>{inline(d['name'])}</td>" + "".join(
            f'<td class="{s[0] if c[s] else "z"}">{c[s]}</td>' for s in SEVERITIES)
            + f"<td>{sum(c.values())}</td></tr>")
    t = total(counts)
    rows.append('<tr class="total"><td>All domains</td>' + "".join(
        f"<td>{t[s]}</td>" for s in SEVERITIES) + f"<td>{sum(t.values())}</td></tr>")
    head = "".join(f"<th>{h}</th>" for h in ("Domain", "Critical", "High", "Medium", "Low",
                                              "Total"))
    return f'<div class="tw"><table class="counts"><tr>{head}</tr>' + "".join(rows) + \
        "</table></div>"


def _count_sentence(doc):
    t = total(count_issues(doc))
    return (f"{sum(t.values())} in total: {t['critical']} critical, {t['high']} high, "
            f"{t['medium']} medium, {t['low']} low")


def render(doc):
    """Validate a findings document and return the report as an HTML string."""
    validate(doc)
    secs = [("summary", "Summary", "".join([
        f"<p><strong>{inline(doc['summary']['lead'])}</strong></p>",
        "<ul>" + "".join(f"<li>{inline(b)}</li>" for b in doc["summary"].get("bullets", []))
        + f"<li><strong>Issues found:</strong> {_count_sentence(doc)}. The full list and the "
          "count by domain close this report.</li></ul>"]))]
    shot_at = next((s["id"] for s in doc["sections"] if s.get("screenshots")),
                   doc["sections"][0]["id"] if doc["sections"] else None)
    for s in doc["sections"]:
        body = "\n".join(block(b) for b in s.get("blocks", []))
        if s["id"] == shot_at:
            body = _shots(doc) + body
        secs.append((s["id"], s["title"], body))
    secs.append(("personas", "Verdicts by persona",
                 "<p>What each persona would do after visiting the site. These are reasoned "
                 "judgments from the findings, not interviews with real people.</p>"
                 '<div class="cards">' + "".join(_persona(p) for p in doc["personas"])
                 + "</div>"))
    for key, title in (("limits", "Limits"), ("corrections", "Corrections"),
                       ("sources", "Sources")):
        if doc.get(key):
            cls = ' class="src"' if key == "sources" else ""
            secs.append((key, title, f"<ul{cls}>" + "".join(
                f"<li>{inline(x)}</li>" for x in doc[key]) + "</ul>"))
    secs.append(("register", "Issue register", _register(doc)))
    secs.append(("counts", "Issue count by domain",
                 "<p>Computed from the issue register.</p>" + _counts_table(doc)))
    toc = "".join(f'<li><a href="#{html.escape(i)}">{inline(t)}</a></li>' for i, t, _ in secs)
    meta = "".join(f"<li><b>{inline(k)}:</b> {inline(v)}</li>"
                   for k, v in {"Target": doc["target"], "Audit date": doc["date"],
                                **doc.get("meta", {})}.items())
    body = "\n".join(_section(n, i, t, b) for n, (i, t, b) in enumerate(secs, 1))
    return TEMPLATE.format(
        title=html.escape(doc["title"]), h1=inline(doc["title"]),
        lede=inline(doc.get("lede", "")), meta=meta, toc=toc, body=body,
        footer=inline(doc.get("footer", "Passive audit of public material only. Legal points "
                                        "are preliminary and are not legal advice. Persona "
                                        "verdicts are simulations.")))


def _shots(doc):
    figs = []
    for s in doc.get("screenshots", []):
        uri = _image_uri(s["path"], s.get("width", 1100))
        figs.append(f'<figure><img alt="{html.escape(s.get("alt", ""))}" src="{uri}">'
                    f'<figcaption>{inline(s.get("caption", ""))}</figcaption></figure>')
    return f'<div class="shots">{"".join(figs)}</div>' if figs else ""


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#f5f7f9;--surface:#fff;--sunken:#eceff3;--ink:#16222c;--ink2:#4a5c68;--ink3:#6b7c88;
--rule:#dfe5ea;--accent:#1f6f9f;--crit:#b3261e;--crit-bg:#fbe9e7;--high:#b4510a;--high-bg:#fdefdf;
--med:#7a6100;--med-bg:#fbf3cf;--low:#3b6787;--low-bg:#e6f0f7;--ok:#1c7446;--ok-bg:#e3f4ea;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
--mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0f151a;
--surface:#161e25;--sunken:#1b242c;--ink:#e7edf2;--ink2:#a8b7c2;--ink3:#8496a3;--rule:#27323b;
--accent:#5aa9d6;--crit:#ff8a80;--crit-bg:#3a1c1a;--high:#ffb074;--high-bg:#3a2713;
--med:#e6cf6a;--med-bg:#332c10;--low:#8fc0e0;--low-bg:#152a38;--ok:#7fd3a4;--ok-bg:#12301f}}}}
:root[data-theme="dark"]{{--bg:#0f151a;--surface:#161e25;--sunken:#1b242c;--ink:#e7edf2;
--ink2:#a8b7c2;--ink3:#8496a3;--rule:#27323b;--accent:#5aa9d6;--crit:#ff8a80;--crit-bg:#3a1c1a;
--high:#ffb074;--high-bg:#3a2713;--med:#e6cf6a;--med-bg:#332c10;--low:#8fc0e0;--low-bg:#152a38;
--ok:#7fd3a4;--ok-bg:#12301f}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.6 var(--sans)}}
.wrap{{max-width:1040px;margin:0 auto;padding:0 16px 80px}}
header{{padding:40px 0 24px;border-bottom:1px solid var(--rule)}}
.kicker{{font:600 12px/1.4 var(--mono);letter-spacing:.08em;text-transform:uppercase;
color:var(--ink3);margin:0 0 8px}}
h1{{font-size:clamp(1.6rem,1.1rem + 2.2vw,2.4rem);line-height:1.15;margin:0 0 12px}}
h2{{font-size:1.4rem;line-height:1.25;margin:56px 0 12px;padding-top:16px;
border-top:1px solid var(--rule)}}
h2 .n{{color:var(--ink3);font:600 .8rem var(--mono);margin-right:8px}}
h3{{font-size:1.05rem;margin:28px 0 8px}}
p,ul,ol{{max-width:76ch}} p{{margin:0 0 12px}} ul,ol{{padding-left:22px}} li{{margin:4px 0}}
a{{color:var(--accent)}} :focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
.lede{{font-size:1.1rem;color:var(--ink2)}}
.meta{{display:flex;flex-wrap:wrap;gap:8px 24px;list-style:none;padding:0;color:var(--ink2);
font-size:.9rem;max-width:none}} .meta b{{color:var(--ink)}}
nav{{margin:24px 0 0;padding:16px 20px;background:var(--surface);border:1px solid var(--rule);
border-radius:8px}} nav ol{{columns:2;column-gap:32px;margin:0;max-width:none}}
@media (max-width:640px){{nav ol,.src{{columns:1}}}}
.note{{background:var(--sunken);border-left:3px solid var(--accent);padding:10px 14px;
border-radius:0 6px 6px 0;margin:12px 0 16px;max-width:76ch}}
.note.warn{{border-left-color:var(--high)}}
.tw{{overflow-x:auto;margin:12px 0 20px;border:1px solid var(--rule);border-radius:8px;
background:var(--surface)}}
table{{border-collapse:collapse;width:100%;font-size:.92rem}}
th,td{{text-align:left;vertical-align:top;padding:8px 12px;border-bottom:1px solid var(--rule)}}
th{{background:var(--sunken);font-weight:600}} tr:last-child td{{border-bottom:0}}
code,pre{{font-family:var(--mono);font-size:.88em}}
code{{background:var(--sunken);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}}
pre{{background:var(--sunken);border:1px solid var(--rule);border-radius:8px;padding:12px 14px;
overflow-x:auto}} pre code{{background:none;padding:0}}
.t-ok{{color:var(--ok);font-weight:600}} .t-warn{{color:var(--med);font-weight:600}}
.t-bad{{color:var(--crit);font-weight:600}} .t-dim{{color:var(--ink3)}}
.sev{{display:inline-block;font:600 .75rem/1 var(--sans);padding:4px 8px;border-radius:999px;
white-space:nowrap;border:1px solid currentColor}}
.s-critical{{color:var(--crit);background:var(--crit-bg)}}
.s-high{{color:var(--high);background:var(--high-bg)}}
.s-medium{{color:var(--med);background:var(--med-bg)}}
.s-low{{color:var(--low);background:var(--low-bg)}}
.cards{{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}}
.card{{background:var(--surface);border:1px solid var(--rule);border-radius:8px;padding:16px 18px}}
.card h3{{margin:0 0 8px}} .card p,.card dl{{max-width:none}}
.verdict{{font-weight:600;padding:8px 12px;border-radius:6px}}
.v-no{{color:var(--crit);background:var(--crit-bg)}}
.v-hold{{color:var(--high);background:var(--high-bg)}}
.v-go{{color:var(--ok);background:var(--ok-bg)}}
dl{{margin:0}} dt{{font-weight:600;margin-top:10px}} dd{{margin:2px 0 0;color:var(--ink2)}}
.shots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;
margin:16px 0}} figure{{margin:0}}
figure img{{width:100%;height:auto;display:block;border:1px solid var(--rule);border-radius:8px}}
figcaption{{font-size:.85rem;color:var(--ink3);margin-top:6px}}
.counts td,.counts th{{text-align:right}}
.counts td:first-child,.counts th:first-child{{text-align:left}}
.counts td{{font-size:1.05rem;font-variant-numeric:tabular-nums}}
.counts .c{{color:var(--crit)}} .counts .h{{color:var(--high)}} .counts .m{{color:var(--med)}}
.counts .l{{color:var(--low)}} .counts .z{{color:var(--ink3)}}
.counts tr.total td{{font-weight:700;border-top:2px solid var(--rule);background:var(--sunken)}}
.src{{font-size:.88rem;columns:2;column-gap:32px;max-width:none;overflow-wrap:anywhere}}
footer{{margin-top:48px;color:var(--ink3);font-size:.85rem}}
@media print{{body{{background:#fff}} nav{{display:none}} tr,.card{{break-inside:avoid}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
<p class="kicker">Trust check</p>
<h1>{h1}</h1>
<p class="lede">{lede}</p>
<ul class="meta">{meta}</ul>
<nav aria-label="Contents"><ol>{toc}</ol></nav>
</header>
<main>
{body}
</main>
<footer><p>{footer}</p></footer>
</div>
</body>
</html>
"""


def main(argv=None):
    """Command-line entry point: findings.json -> report.html."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: build_report.py findings.json report.html", file=sys.stderr)
        return 2
    try:
        doc = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
        out = render(doc)
    except (FindingsError, json.JSONDecodeError, KeyError, OSError) as exc:
        print(f"build_report: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    Path(argv[1]).write_text(out, encoding="utf-8")
    print(f"wrote {argv[1]}: {_count_sentence(doc)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
