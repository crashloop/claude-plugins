---
name: ask-all-form
description: Ask the user many questions at once through a browser form and read all answers back as one JSON object. Use when a skill (wayfinder, grilling, planning) has 3+ independent decisions open and one-at-a-time AskUserQuestion would be slow.
---

# ask-all-form

Serves a one-shot HTML form on localhost, opens the browser, waits for Submit, prints the
answers as JSON. Same question spec as the `mcp__ask-all__ask` terminal tool, so a skill can
use whichever is available.

## When to Use

- 3+ independent decisions are open at once (breadth-first grilling, mapping a frontier)
- Answers branch: a follow-up question should appear only after a parent choice
- The user asked to "answer everything in one go", "batch the questions", "give me a form"

Prefer the `mcp__ask-all__ask` tool when it is listed: no browser needed. Its call returns at once; end the turn and the answers arrive as the next user message. Use ask-all-form when
that tool is absent or the session runs in a desktop app. In a remote or SSH session
neither works; fall back to AskUserQuestion with up to 4 questions per call.

## Usage

```bash
python skills/ask-all-form/scripts/ask_form.py spec.json            # opens the browser, waits
python skills/ask-all-form/scripts/ask_form.py spec.json --no-browser --timeout 900
echo '{"questions":[...]}' | python skills/ask-all-form/scripts/ask_form.py -
```

## Spec

```json
{
  "title": "Map the frontier",
  "questions": [
    {"id": "tracker", "label": "Issue tracker?", "type": "single",
     "options": [
       {"label": "GitHub", "description": "Native blocking edges; needs gh and a repo"},
       {"label": "Linear", "description": "Best UI; one more login"},
       "Local markdown"
     ], "recommended": "GitHub",
     "hint": "Where the wayfinder map and tickets will live"},
    {"id": "gh_org", "label": "GitHub org", "type": "text",
     "showWhen": {"id": "tracker", "eq": "GitHub"}},
    {"id": "types", "label": "Ticket types in play", "type": "multi",
     "options": ["research", "prototype", "grilling", "task"]}
  ]
}
```

| Field | Meaning |
|-------|---------|
| `type` | `single` (radio), `multi` (checkboxes), `text` (one line) |
| `options` | Strings, or `{"label", "description"}`; put the trade-off in `description`, as AskUserQuestion does |
| `recommended` | Preselected option for `single`; label it as your recommended answer |
| `hint` | One line under the label (`text`: the placeholder) |
| `showWhen` | Draw only while question `id` equals `eq`; hidden answers are dropped |

## Arguments

| Flag | Default | Meaning |
|------|---------|---------|
| `spec` | required | Path to the spec JSON, or `-` for stdin |
| `--timeout` | 600 | Seconds to wait for Submit; exit 2 with `{"error": "timeout"}` after |
| `--no-browser` | off | Print the URL to stderr only, do not open a browser |

## Dependencies

Python 3.10+ standard library only. A browser on the same machine as the session.

## Output

One JSON object on stdout: `{"tracker": "GitHub", "gh_org": "3Craft", "types": ["research"]}`.
Multi answers are lists, everything else a string. Unanswered and hidden questions are omitted.

## Claude Integration

1. Look up facts in the codebase first; only decisions go in the form.
2. Write the spec to the scratchpad. Put your recommended answer in `recommended`.
3. Run the script with Bash. Use a timeout of at least 600000 ms, or run in the background.
4. Parse the JSON on stdout. Treat a missing id as "not answered", not as a refusal.
5. Dependent decisions that the answers unlock go in a second form, not a guess.
