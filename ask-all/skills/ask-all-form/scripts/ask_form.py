#!/usr/bin/env python3
"""Serve a one-shot browser form for a question spec and print the answers as JSON.

Usage:
    ask_form.py spec.json [--timeout 600] [--no-browser]

Spec (same shape as the ask-all plugin tool):
    {"title": "...", "questions": [
      {"id": "tracker", "label": "Issue tracker?", "type": "single",
       "options": [{"label": "GitHub", "description": "native blocking, gh CLI"}, "Linear"],
       "recommended": "GitHub", "hint": "..."},
      {"id": "org", "label": "GitHub org", "type": "text",
       "showWhen": {"id": "tracker", "eq": "GitHub"}},
      {"id": "types", "label": "Ticket types", "type": "multi", "options": ["a", "b"]}
    ]}
Answers: {"tracker": "GitHub", "org": "3Craft", "types": ["a"]} on stdout.
"""
import argparse
import html
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

STYLE = """<style>
body{font:16px system-ui;max-width:720px;margin:2rem auto;padding:0 1rem;color:#222}
fieldset{border:1px solid #ccc;border-radius:6px;margin:0 0 1rem;padding:.75rem 1rem}
legend{font-weight:600}label{display:block;margin:.25rem 0}.hint{color:#666;font-size:.9em}
input[type=text]{width:100%;padding:.4rem;font:inherit}button{font:inherit;padding:.5rem 1.2rem}
</style>"""
SCRIPT = """<script>
function sync(){document.querySelectorAll('[data-show-id]').forEach(f=>{
 const el=document.querySelector(`[name="${f.dataset.showId}"]:checked`);
 f.hidden=!(el&&el.value===f.dataset.showEq);});}
document.addEventListener('change',sync);sync();
</script>"""


def _field(q):
    e = html.escape
    qid, kind = e(q["id"]), q["type"]
    if kind == "text":
        return f'<input type="text" name="{qid}" placeholder="{e(q.get("hint", ""))}">'
    box = "radio" if kind == "single" else "checkbox"
    rows = []
    for opt in q.get("options", []):
        opt = {"label": opt} if isinstance(opt, str) else opt
        rec = opt["label"] == q.get("recommended")
        desc = f' <span class="hint">{e(opt["description"])}</span>' if opt.get("description") else ""
        rows.append(
            f'<label><input type="{box}" name="{qid}" value="{e(opt["label"])}"'
            f'{" checked" if rec else ""}> {e(opt["label"])}{" (recommended)" if rec else ""}{desc}</label>'
        )
    return "\n".join(rows)


def render(spec):
    """Return the form page for a spec."""
    e = html.escape
    parts = []
    for q in spec["questions"]:
        show = q.get("showWhen")
        attrs = f' data-show-id="{e(show["id"])}" data-show-eq="{e(show["eq"])}"' if show else ""
        hint = f'<div class="hint">{e(q["hint"])}</div>' if q.get("hint") and q["type"] != "text" else ""
        parts.append(f'<fieldset{attrs}><legend>{e(q["label"])}</legend>{hint}{_field(q)}</fieldset>')
    title = e(spec.get("title", "Questions"))
    return (f"<!doctype html><title>{title}</title>{STYLE}<h1>{title}</h1>"
            f'<form method="post">{"".join(parts)}<button>Submit answers</button></form>{SCRIPT}')


def parse_answers(spec, body):
    """Map a urlencoded POST body to {id: answer}; hidden or empty fields are omitted."""
    form = parse_qs(body, keep_blank_values=False)
    answers = {}
    for q in spec["questions"]:
        vals = form.get(q["id"])
        show = q.get("showWhen")
        if not vals or (show and answers.get(show["id"]) != show["eq"]):
            continue
        answers[q["id"]] = vals if q["type"] == "multi" else vals[0]
    return answers


def serve(spec, timeout, open_browser):
    """Serve the form until one submission or the timeout; return the answers or None."""
    page = render(spec).encode()
    done = threading.Event()
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):  # quiet
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            result.update(parse_answers(spec, body))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<p style='font:16px system-ui'>Answers received. You can close this tab.</p>")
            done.set()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Form: {url}", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    submitted = done.wait(timeout)
    server.shutdown()
    return result if submitted else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="path to the spec JSON, or - for stdin")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait (default 600)")
    ap.add_argument("--no-browser", action="store_true", help="print the URL only")
    args = ap.parse_args()
    spec = json.load(sys.stdin if args.spec == "-" else open(args.spec))
    answers = serve(spec, args.timeout, not args.no_browser)
    if answers is None:
        print(json.dumps({"error": "timeout", "message": "no submission received"}))
        sys.exit(2)
    print(json.dumps(answers, ensure_ascii=False))


if __name__ == "__main__":
    main()
