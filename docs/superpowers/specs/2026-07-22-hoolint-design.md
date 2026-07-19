# hoolint — design spec

Date: 2026-07-22
Status: approved for planning

## Purpose

A Claude Code plugin that installs hooks to check code and documentation
whenever the model signals it finished working (Stop, SubagentStop). The
plugin wraps a `hoolint` uv/Python CLI that analyzes files created or updated
since the last run, using stackable analysis strategies: cheap filters first
(regex), semantic scoring next (model2vec), model judgment last (in-session
escalation).

## Two-part shape

- **Plugin** (`hoolint/` in the claude-plugins repo): `plugin.json`,
  `hooks/hooks.json`, thin hook scripts, and the Python app in `hoolint/app/`
  (a uv project). Hooks invoke it with
  `uv run --project "$CLAUDE_PLUGIN_ROOT/app" hoolint ...`.
- **Python CLI** (`hoolint`): change detection, rule loading, strategy
  execution, reporting. The hook layer stays dumb: event JSON in, findings
  and exit code out.

## Hook wiring

| Hook | Matcher | Action |
|---|---|---|
| PostToolUse | Write, Edit, NotebookEdit | Append touched file path to session journal `.hoolint/session-<id>.jsonl`. No analysis. |
| Stop, SubagentStop | — | Run `hoolint check --mode session`: read journal, analyze touched files, clear journal (marks last run). |

**Loop guard**: when `stop_hook_active` is true, hoolint only re-checks
previously reported findings. If the same findings persist a second time, it
reports them as warnings and lets the stop through. Never an infinite loop.

## Change detection (configurable)

- `--mode session` (default in hooks): journal of files Claude touched since
  the last run.
- `--mode git` (verification pipelines / CI): `git diff --name-only <ref>`;
  ref configurable, default merge-base with main.

## Rules and strategies

**Config**: `hoolint.toml` at project root; falls back to plugin defaults.
Each rule declares:

```toml
[[rule]]
id = "verbose-comments"
globs = ["**/*.py"]
severity = "block"        # block | warn
[[rule.stage]]
strategy = "regex"
pattern = "(?m)^(\\s*#[^\\n]*\\n){3,}"
[[rule.stage]]
strategy = "semantic"     # model2vec similarity scoring
op = "and"
[[rule.stage]]
strategy = "escalate"     # hand shortlist to Claude for judgment
```

**Stock strategies** (Python classes):

- `regex` — pattern match over file content.
- `semantic` — model2vec embedding similarity against reference phrasings.
- `escalate` — emit shortlisted findings as `needs-judgment` (see below).
- `external` — wrap a CLI like ruff/mdformat (future, not v1).

**Composition**: a rule's pipeline is a list of stages run in sequence; each
stage has `op` (`and`/`or`) and filters or extends the previous stage's
candidate set. Cheap stages first, expensive stages only on the shortlist.
Independent rules run in parallel via a process pool; stages within a rule
are sequential by design.

**Custom rules**: a project `hoolint_rules/` directory of Python files, each
exposing a `Rule` object; loaded dynamically. TOML covers stock composition,
Python covers anything the expression language cannot say.

## LLM judgment: hook-side, not Python

The Python app never calls a model. A rule's final stage can be `escalate`:
shortlisted findings are emitted with `verdict: "needs-judgment"` plus the
rule's judgment prompt. The Stop hook packages these into the block feedback
so Claude itself judges the shortlist (apply exceptions, confirm or dismiss)
while resuming work. Dismissals are recorded via `hoolint waive
<finding-id>`, so the loop guard sees them as resolved.

**Accepted consequence**: in `--mode git` (no session), `escalate` stages
cannot run. Those rules degrade to their cheap-stage result, reported as
`warn` with a `not-judged` marker. CI-side judgment is a possible later
addition, not v1.

## Severity semantics

- Session mode: any confirmed `block` finding → hook exits 2 with findings on
  stderr; the model keeps working. Only `warn` findings → printed, stop
  proceeds.
- Git/CI mode: exit 1 on `block` findings, 0 otherwise.

## V1 rule set

1. **verbose-comments** (block): regex flags >2 consecutive `#` comment lines
   in `.py` → `semantic` scores whether the comment could be compressed →
   `escalate` for final judgment.
2. **doc-broken-links** (warn): extract relative markdown links, flag targets
   that do not exist. Pure Python, no escalation.
3. **doc-drift** (warn): extract file/path references from markdown, flag ones
   missing from the repo → `escalate` to judge whether the doc needs updating.

## Testing

- Pytest for the CLI: per-strategy unit tests, pipeline composition tests,
  journal and git mode tests against fixture repos.
- One end-to-end hook test: canned Stop event JSON through the hook script;
  assert exit code and stderr shape.
- model2vec pinned; semantic tests use a tiny fixture model or are marked
  slow/skippable.

## Out of scope (v1)

- `external` strategy (ruff/mdformat wrapping).
- CI-side LLM judgment.
- Marketplace publication polish beyond a `marketplace.json` entry.
