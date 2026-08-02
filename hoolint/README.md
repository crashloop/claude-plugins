# hoolint

Claude Code plugin: when the model stops, hoolint checks every file it
touched — code and docs — through stacked strategies of increasing cost,
and blocks the stop until findings are fixed or waived.

Name: **hoolint** = hook + lint.

## Install

Requires [`uv`](https://docs.astral.sh/uv/) on PATH — the hooks run the checker
with `uv run --project`. In Claude Code:

```
/plugin marketplace add crashloop/claude-plugins
/plugin install hoolint@crashloop-plugins
```

On first session start hoolint warms the embedding model in the background;
`hoolint warmup` does it on demand. The `semantic` tier is skipped (findings
demote to advisory) until the model is ready, and the `local_llm` tier is
skipped unless a local OpenAI-compatible endpoint is up — so hoolint works with
neither, just with fewer tiers.

## How it works

1. `PostToolUse` journals every file Claude writes or edits.
2. `Stop` runs `hoolint check`: rules pipe candidates through stages —
   `regex` (cheap filter) → `semantic` (model2vec redundancy-with-code) →
   `local_llm` (Ollama/vLLM/LM Studio via one OpenAI-compatible endpoint) →
   `escalate` (the session model judges the shortlist).
3. Confirmed `block` findings exit 2: Claude keeps working and fixes them.
   After `stand_down_after` (default 2) blocked stops, hoolint stands down and
   hands the findings to the human. A filter tier that could not run (no model,
   no endpoint) demotes that rule to advisory for the run — an
   incompletely-configured install reports but never blocks.

## Waivers

`hoolint waive <fingerprint> --reason "<why>"` writes to
`hoolint-waivers.toml` — committed, team-shared, reviewed in the PR diff. Each
entry carries the excused span and its location, so a reviewer can judge it
without checking out the branch. A waiver stops matching once the excused span
changes; `hoolint waive --prune` drops entries that no longer match. Waiving is
only possible for a finding hoolint actually reported, and is reserved for code
the user explicitly sanctioned.

## CI / verification pipelines

`uv run --project <plugin>/app hoolint check --mode git --ref <ref>` checks
`git diff` instead of the session journal; exit 1 on block findings.
`escalate` stages mark findings `not-judged` but keep their severity, so CI
still fails on them; `local_llm` runs whenever a local endpoint is up.

## Configuration

`hoolint.toml` at the project root. Stock rules (`verbose-comments`,
`doc-broken-links`, `doc-drift`, `em-dashes`) are on by default; same-id rules
override wholesale, `enabled = false` disables. Custom Python rules in
`hoolint_rules/` load only after `hoolint trust`, and the grant is pinned to
those files' content, so adding or editing a rule re-arms the prompt.

`em-dashes` warns on an em dash in markdown prose, skipping fenced code blocks
so quoted samples stay legal. It is the only writing-style rule that ships,
because it is the only one that survives contact with technical docs: a ban on
absolutes or adverbs flags "never stdlib `re`", which is a constraint rather
than a stylistic tic. Disable it with `enabled = false` if you write em dashes
on purpose. To ban en dashes and ellipses too, override the pattern:

```toml
[[rule]]
id = "em-dashes"
globs = ["**/*.md"]
severity = "warn"
[[rule.stage]]
strategy = "prose_pattern"
pattern = "[—–…]"
```

Only fenced blocks are skipped, not inline code spans, so a doc that discusses
the character itself (this one) reports it. Waive those.

`use-not-leverage` warns on `leverage` and `utilize` in markdown, in every
inflected form except `utilization`. It is the one word list out of the usual
anti-slop catalogue that earned its place. Measured over 1.29M lines of prose in
four repositories it produced 487 findings at roughly 86% true positive, while
"delve into", "in today's fast-paced world" and "furthermore" produced exactly
zero, and the hedging and meta-commentary lists produced nothing but false
positives: "may or may not be synced" is precision, and "What's in This Section"
is a heading. `utilization` is spared because it is domain vocabulary
("connection pool utilization") and appears inside test ids. As with
`em-dashes`, this paragraph trips its own rule. Waive it.

`exclude_globs` narrows any rule's file scope after `globs` has widened it. Use
it for text nobody in the repository wrote: vendored library dumps, generated
API references, skill files that quote bad prose as examples. Without it, a
single 6000-line vendored doc costs one waiver per finding. Overrides are
wholesale, so repeat the stages you want to keep:

```toml
[[rule]]
id = "em-dashes"
globs = ["**/*.md"]
exclude_globs = [".github/backend/**", "docs/generated/**"]
severity = "warn"
[[rule.stage]]
strategy = "prose_pattern"
pattern = "—"
```

`local_llm.base_url` is restricted to loopback and private addresses, so a
project's config cannot ship your code to a public host.

`local_llm.reasoning_effort` is passed to the endpoint verbatim under OpenAI's
own field name, so an endpoint with no such control ignores it. Set it to
`"none"` on rules whose candidates are decided by reading one span, and leave it
unset where the verdict needs weighing. It is not a free win: it buys latency by
removing deliberation, which is the thing a judge stage is for.

## Python AST rules

These shortlist defects that no pattern can find, because the defect is a statement's
position inside a function rather than its shape. Neither ships enabled: each is a
candidate generator meant to be followed by a `local_llm` or `escalate` stage, never a
verdict on its own. Without a local model reachable, `local_llm` notes that it skipped
and every candidate ships as a `warn`, so turning these on without one gives you the raw
shortlist rather than a verdict.

`mock_echo_assert` flags `assert x == v` where a mock in the *same function* was told to
return `v`. Such an assertion cannot fail unless the code under test stops returning at
all, since it checks the value the test itself installed.

Three filters keep the shortlist honest, each one measured rather than guessed. Mock setups
are collected per function, never module-wide. Valueless literals (`None`, `True`, `[]`,
`0`, `""`) never match, because they collide by coincidence rather than by dataflow. And the
left side must be a bare name: a subscript, attribute or call there means the value
travelled through real code and the assert pins where it landed, which is a wiring check
worth keeping (`assert response.json() == articles`, `assert log.database_size_bytes ==
1024000`). Hand-classifying every finding on two repositories, those three cuts took 88
candidates down to 12, and 10 of the 12 survivors were genuine. The remaining pair is why
the judge stage is still there.

```toml
[[rule]]
id = "mock-echo-assert"
globs = ["**/test_*.py", "**/tests/**/*.py"]
severity = "warn"
[[rule.stage]]
strategy = "mock_echo_assert"
[[rule.stage]]
strategy = "local_llm"
op = "and"
model = "qwen3:4b"
max_candidates = 10
prompt = """Judge each numbered assertion. Reply `[N] VIOLATION: <reason>` or
`[N] OK: <reason>`. VIOLATION if the assertion only restates a value the test
itself configured, so deleting the code under test would not fail it. OK if it
pins a pass-through that a future refactor could silently break, or if the
surrounding call assertions carry the real verification.

Assertions:
{span}"""
```

`permissive_recovery` flags an `except` handler that recovers with `return True`,
`return None`, or `pass` inside a function whose name matches `name_contains`. Fail-open
and fail-closed recovery are the same three tokens of Python, so only the function's role
separates them, and that role is per project vocabulary rather than something to guess.
With the `exclude_globs` below, it produced 4 candidates over 3,724 files, which is the
shortlist size a judge stage wants.

`return None` is offered deliberately even though it is often right. In a cascade of
permission checks it means "no opinion, ask the next tier"; in a lone check it means
"allowed by default"; and in a DRF `authenticate()` it is the documented way to pass to the
next authenticator. Use `exclude_globs` to keep test helpers out of the shortlist.

```toml
[[rule]]
id = "auth-fails-open"
globs = ["**/*.py"]
exclude_globs = ["**/tests/**", "**/test_*.py"]
severity = "warn"
[[rule.stage]]
strategy = "permissive_recovery"
name_contains = ["permission", "authorize", "authenticate", "has_perm", "can_"]
[[rule.stage]]
strategy = "escalate"
prompt = """Does this handler let an unauthorized caller through, or is the
permissive result correct here? `return None` is right when the caller treats it
as "no opinion" and consults another check, and wrong when the caller reads it as
allowed. Follow the call site before deciding. Waive only with the user's
explicit sanction."""
```

Both refuse to run in second position: they generate rather than filter, so chaining one
after another stage would discard what that stage found. Put them first, or use
`op = "or"`.

## Metadata rules

These check the change set and repository history rather than the contents of one file. None is
enabled by default, because CHANGELOG paths and test layouts differ per project. Copy what you
need into `hoolint.toml`.

`modes` restricts a rule to `session` (the model's edits since the last check) or `git` (the
diff against a ref). Omit it and the rule runs in both. Note that "changed" differs between
them: in git mode a CHANGELOG entry added earlier on the branch satisfies a companion rule,
while in session mode only files touched since the last check count.

```toml
# Public API changed without a CHANGELOG entry.
[[rule]]
id = "api-changelog"
globs = ["src/api/**/*.py"]
severity = "warn"
modes = ["git"]
[[rule.stage]]
strategy = "companion"
requires = "CHANGELOG.md"
message = "public API changed without a CHANGELOG entry"

# Source changed without its test. `requires_to` is an re2 substitution.
[[rule]]
id = "source-needs-test"
globs = ["src/**/*.py"]
severity = "warn"
[[rule.stage]]
strategy = "companion"
requires_from = "src/(.*)\\.py"
requires_to = "tests/test_\\1.py"

# Too much at once.
[[rule]]
id = "blast-radius"
globs = ["**/*"]
severity = "warn"
[[rule.stage]]
strategy = "change_size"
max_files = 20

# A file being revised over and over.
[[rule]]
id = "churning-file"
globs = ["src/**/*.py"]
severity = "warn"
[[rule.stage]]
strategy = "churn"
max_commits = 5
window = "30.days"

# Commit subject convention. Git mode only: at Stop time there is usually no new commit.
[[rule]]
id = "commit-subject"
globs = ["**/*"]
severity = "warn"
modes = ["git"]
[[rule.stage]]
strategy = "commit_meta"
subject_pattern = "(feat|fix|docs|test|chore)(\\(.+\\))?: .+"
```

Waivers on `companion` and `churn` findings are **durable**. Those findings have no code span,
so each is anchored to the offending file's path and its fingerprint does not change when the
file's contents do. Waiving one records a lasting decision, such as "this file is exempt from
needing a CHANGELOG entry", rather than an exception that expires on the next edit. This is
deliberate, and differs from span-anchored code rules, whose waivers stop matching once the
excused span changes.

`change_size` and `commit_meta` describe the whole change rather than one file, so they anchor
to an arbitrary file — the first matched path in sorted order. Waiving them is **not** a
supported durable decision. A `change_size` waiver stops matching as soon as that file leaves
the change set, so it excuses nothing next time. A `commit_meta` waiver fails the other way:
with `globs = ["**/*"]` a repository usually has a stable alphabetically-first path, so one
waiver can silence the subject convention indefinitely.

Findings from a `modes = ["git"]` rule cannot be waived with `hoolint waive`. A git-mode check
prints them but does not record them, and `waive` refuses any fingerprint the last check did not
report. Waive those by hand-editing `hoolint-waivers.toml`.

## Custom rules

Drop a `.py` file in `hoolint_rules/` that assigns a module-level `rule` dict:

```python
# hoolint_rules/no_fixme.py
rule = {
    "id": "no-fixme",
    "globs": ["**/*.py"],
    "severity": "block",              # or "warn"
    "stage": [
        {"strategy": "regex", "pattern": "(?m)^.*FIXME.*$",
         "message": "unresolved FIXME"},
    ],
}
```

Custom rules execute arbitrary Python, so they load only after you run
`hoolint trust`, which pins the grant to the exact content of `hoolint_rules/`
— editing or adding a rule (or any file it reads) revokes trust and re-prompts.
Stages chain the same strategies the stock rules use (`regex`, `semantic`,
`local_llm`, `escalate`).

See `CONTEXT.md` for the vocabulary.
