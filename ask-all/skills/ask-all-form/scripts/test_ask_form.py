"""Self-check: python test_ask_form.py"""
from ask_form import parse_answers, render

SPEC = {"title": "T", "questions": [
    {"id": "tracker", "label": "Tracker?", "type": "single", "options": [{"label": "GitHub", "description": "gh CLI"}, "Linear"],
     "recommended": "GitHub"},
    {"id": "org", "label": "Org", "type": "text", "showWhen": {"id": "tracker", "eq": "GitHub"}},
    {"id": "types", "label": "Types", "type": "multi", "options": ["a", "b"]},
]}

page = render(SPEC)
assert 'value="GitHub" checked' in page and 'gh CLI' in page and 'data-show-id="tracker"' in page
assert parse_answers(SPEC, "tracker=GitHub&org=3Craft&types=a&types=b") == {
    "tracker": "GitHub", "org": "3Craft", "types": ["a", "b"]}
assert parse_answers(SPEC, "tracker=Linear&org=stale") == {"tracker": "Linear"}
print("ok")
