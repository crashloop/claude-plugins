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
`doc-broken-links`, `doc-drift`) are on by default; same-id rules override
wholesale, `enabled = false` disables. Custom Python rules in `hoolint_rules/`
load only after `hoolint trust`, and the grant is pinned to those files'
content — adding or editing a rule re-arms the prompt.

`local_llm.base_url` is restricted to loopback and private addresses, so a
project's config cannot ship your code to a public host.

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

Waivers on metadata findings are **durable**. A metadata finding has no code span, so it is
anchored to the file's path and its fingerprint does not change when the file's contents do.
Waiving one records a lasting decision, such as "this file is exempt from needing a CHANGELOG
entry", rather than an exception that expires on the next edit. This is deliberate, and differs
from span-anchored code rules, whose waivers stop matching once the excused span changes.

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
