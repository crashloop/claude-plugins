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
| SessionStart | — | `hoolint warmup` detached in background: `uv sync` + embedding model download. Exits 0 immediately. |
| PostToolUse | Write, Edit, NotebookEdit | Append touched file path to session journal `.hoolint/session-<id>.jsonl`. No analysis. Fires for subagent edits too, so subagent output is covered. |
| Stop | — | Run `hoolint check --mode session`: read journal, analyze touched files, clear journal (marks last run). |

No SubagentStop hook: the main-session Stop analyzes all files touched by
all subagents at once (decision: simplicity over per-subagent enforcement).

**Loop guard / stand-down**: hoolint counts consecutive stops with an
unchanged finding-set (same fingerprints). After `stand_down_after`
consecutive blocked stops (default **2**, configurable), it releases the
stop, prints the findings as warnings, and says why it stood down. Never an
infinite loop.

**Cold cache**: if the Stop check finds the venv or embedding model not yet
warmed, `semantic` stages are skipped with a visible "warming up" notice;
cheap stages still run. Degrade loudly, never hang or block on a cold start.

## Change detection (configurable)

- `--mode session` (default in hooks): journal of files Claude touched since
  the last run.
- `--mode git` (verification pipelines / CI): `git diff --name-only <ref>`;
  ref configurable, default merge-base with main.

## Rules and strategies

**Config**: `hoolint.toml` at project root. Stock rules are active with zero
config. A project file merges per rule id: same id overrides the stock rule
wholesale (no field-level merging), new ids add rules, `enabled = false`
disables a stock rule. Engine settings (`stand_down_after`, git ref,
parallelism) are plain keys; project value wins. No includes, no per-user
overlay in v1.

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
- `semantic` — model2vec redundancy-with-code scoring: embed the flagged
  span, embed the adjacent code (identifiers, signature, docstring), cosine
  similarity above a configurable `threshold` confirms the candidate. An
  honest heuristic shortlist filter; the escalate stage remains the judge.
  Other modes (internal repetitiveness, exemplar similarity) are later
  additions to the same class.
- `local_llm` — judge candidates via a local model behind any
  OpenAI-compatible endpoint (plain httpx, no SDK). Per-stage config:
  `base_url` (default `http://localhost:11434/v1`, Ollama), `model`,
  `prompt`, `timeout`. Same code serves vLLM, LM Studio, llamafile via
  `base_url`. Never a cloud provider: no API keys, no per-call cost — the
  reasons judgment went hook-side do not apply locally. Runs in git/CI mode,
  partially closing the escalate-cannot-run-in-CI gap. Endpoint unreachable
  → stage skips loudly (same degradation contract as `semantic`).
- `escalate` — emit shortlisted findings as `needs-judgment` (see below).
- `external` — wrap a CLI like ruff/mdformat (future, not v1).

**Composition**: a rule's pipeline is a list of stages run in sequence; each
stage has `op` (`and`/`or`) and filters or extends the previous stage's
candidate set. Cheap stages first, expensive stages only on the shortlist.
Independent rules run in parallel via a thread pool (model state is shared;
local_llm is I/O-bound — a process pool would reload the embedding model per
worker); stages within a rule are sequential by design.

**Custom rules**: a project `hoolint_rules/` directory of Python files, each
exposing a `Rule` object; loaded dynamically. TOML covers stock composition,
Python covers anything the expression language cannot say.

**Trust gate**: custom rule loading is off by default — it is arbitrary code
execution triggered by opening a repo. `hoolint trust` records the project
path in `~/.config/hoolint/trusted.toml`; until then, hoolint prints
"custom rules present, not loaded — run `hoolint trust`" and skips them.

## LLM judgment: hook-side, not Python

The Python app never calls a *cloud* model (local endpoints via `local_llm`
are fine: no auth, no per-call cost). A rule's final stage can be `escalate`:
shortlisted findings are emitted with `verdict: "needs-judgment"` plus the
rule's judgment prompt. The Stop hook packages these into the block feedback
so Claude itself judges the shortlist (apply exceptions, confirm or dismiss)
while resuming work. Dismissals are recorded via
`hoolint waive <fingerprint> --reason "<text>"` (reason mandatory), so the
loop guard sees them as resolved.

**Waivers are committed team policy**: they live in `hoolint-waivers.toml`
at the project root, keyed by fingerprint (rule id + file path + hash of the
offending span) with the reason. A waiver auto-expires when the excused span
changes (hash mismatch). Waivers land unstaged in the working tree; **git
review is the approval gate** — no approval workflow inside hoolint.
Ephemeral state (journal, pending findings, stand-down counter) stays in
`.hoolint/`, gitignored.

**Accepted consequence**: in `--mode git` (no session), `escalate` stages
cannot run. Those rules degrade to their cheap-stage result, reported as
`warn` with a `not-judged` marker. CI-side judgment is a possible later
addition, not v1.

## Severity semantics

- Session mode: any confirmed `block` finding → hook exits 2 with findings on
  stderr; the model keeps working. Only `warn` findings → printed, stop
  proceeds. Stand-down rule applies (see Hook wiring).
- Git/CI mode: exit 1 on `block` findings, 0 otherwise.

## V1 rule set

1. **verbose-comments** (block): regex flags >2 consecutive `#` comment lines
   in `.py` → `semantic` scores redundancy with adjacent code → `local_llm`
   judges the shortlist locally → `escalate` for final judgment. The two LLM
   tiers degrade independently: no endpoint and no session still leaves the
   regex+semantic result as a warn.
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
