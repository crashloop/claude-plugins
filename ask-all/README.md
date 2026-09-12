# ask-all

A Claude Code plugin that lets you answer **many agent questions at once** instead of one
AskUserQuestion dialog at a time.

## The problem

Planning skills such as wayfinder and grilling put decisions to the human one by one. Each
dialog is a pause, and a breadth-first pass over ten independent decisions is ten pauses.
AskUserQuestion also caps a call at four questions and cannot hide a follow-up until its
parent is answered.

## What it does

The plugin registers one tool, `mcp__ask-all__ask`, and draws its form in the band above the
prompt:

| Question type | Drawn as |
|---------------|----------|
| `single` | One row per option, `(*)` marks the pick, the recommended option tagged |
| `multi` | One row per option, `[x]` toggles |
| `text` | A one-line input |

Every option may carry a `description` stating its trade-off, drawn dimmed beside it, as
AskUserQuestion shows. A question with `showWhen: {id, eq}` appears only once its parent
question holds that answer. Press **Submit answers** and the answers reach the session as
your next user message, as JSON keyed by question id.

**Why a message and not a tool result.** A `tool.call` hook cannot hold a turn open for a
human: its budget expires within a second. So the tool returns at once, tells the model to
end its turn, and Submit hands the answers over with `$.prompt.submit`.

## The browser form

`skills/ask-all-form/` is the same spec served as a browser form by a standard-library Python
script. It opens the browser, waits for Submit, and prints the answers as one JSON line.
Use it where the terminal band is not drawn (the desktop app) or from any skill that wants
a plain script.

```sh
python ask-all/skills/ask-all-form/scripts/ask_form.py spec.json
python ask-all/skills/ask-all-form/scripts/ask_form.py spec.json --no-browser --timeout 900
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
     ], "recommended": "GitHub"},
    {"id": "gh_org", "label": "GitHub org", "type": "text",
     "showWhen": {"id": "tracker", "eq": "GitHub"}},
    {"id": "types", "label": "Ticket types in play", "type": "multi",
     "options": ["research", "prototype", "grilling", "task"]}
  ]
}
```

## Wiring it into a skill

One line is enough. In grilling, for example: "when three or more independent decisions are
open, put them in one form with `mcp__ask-all__ask`, or the `ask-all-form` skill when that tool
is absent; give every option a description with its trade-off and mark your recommendation."

## Ceiling (by design)

The band above the prompt is terminal only, so the desktop app gets the browser form and
mobile gets neither. A pane hook is the upgrade path for the desktop app.

## Develop

```sh
claude --plugin-dir ./ask-all       # load from disk for one session
claude plugin validate ./ask-all    # what the engine sees
python ask-all/skills/ask-all-form/scripts/test_ask_form.py
```

The hooks module is typed against the declarations `/plugin-types` writes.
