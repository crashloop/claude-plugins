# hoolint metadata rules (design)

**Date:** 2026-07-28. **Status:** approved, ready for planning.
**Scope:** capability #4 (git/metadata rules) only. Capability #7
(retrieval-augmented doc checks) gets its own spec later.

## Purpose

Today every hoolint rule inspects the *content* of one file. This spec adds
rules that inspect the *change set* and the *repository history*: "file A
changed but file B did not", "this file is churning", "the commit subject is
malformed", "this change is too large".

These answer criteria ordinary linting cannot express, because the violation
lives in the relationship between files rather than inside any one file.

## Decisions taken

1. Two specs. This one covers #4. #7 follows separately, because it needs an
   engine capability (drop-on-skip) that #4 does not.
2. Four checks ship: companion file, churn, commit metadata, change size.
3. Rules declare where they apply via a rule-level `modes` key.
4. The companion check supports both a fixed target and a derived pattern.
5. No rule ships enabled. `defaults.toml` is untouched; the rules live in the
   README as copy-paste config a project opts into.

Decision 5 matters most: CHANGELOG paths and test layouts are project
specific, so a default-on metadata rule would fire in every repository that
installs hoolint.

## Context for implementers

Read this before writing code. It is the session knowledge this spec would
otherwise assume.

**Where things are.** The plugin is `hoolint/`; the Python project is
`hoolint/app/`, source under `src/hoolint/`, tests under `tests/`. Strategies
live in `src/hoolint/strategies/`.

**How to verify.** `cd hoolint/app && uv run pytest -q`. At the time of
writing the suite is 102 passed, 1 deselected. The deselected test is a slow
semantic calibration test that needs a real model download; `addopts =
"-m 'not slow'"` in `pyproject.toml` excludes it deliberately. Do not try to
make it run.

**Branch.** `feat/hoolint-strategies`, cut from `feat/hoolint` at `8bb526c`.
`feat/hoolint` holds the reviewed, merge-ready plugin and should not be
disturbed.

**Pyright noise.** Import-resolution errors in the editor are false positives.
Pyright does not see the uv virtualenv. The test suite is the source of truth.

**Line numbers drift.** References such as `engine.py:19` and
`engine.py:38-46` are accurate at `8bb526c`. Re-derive them; do not trust them.

**Registering a strategy.** `STRATEGIES` in `strategies/__init__.py` is a plain
dict mapping a config name to an instance. Add an entry per strategy. The
lookup happens at run time in `_run_rule`, so registration order does not
matter.

**Constructing a Finding.** Copy the `_finding` helper in `strategies/docs_.py`.
Fields are `rule_id`, `file` (relative to the project root), `start_line`,
`end_line`, `span_text`, `message`, and `severity`, which comes from
`ctx.severity` rather than being hardcoded.

**Generator convention.** A generator returns `[]` when `candidates is not
None`, exactly as `doc_links` does. All four strategies in this spec are
generators.

**Test isolation trap.** `tests/conftest.py` has an autouse fixture that
forces the `semantic` and `local_llm` tiers down their skip paths. A skipped
filter sets `filter_skipped`, which demotes `block` findings to `warn`
(`engine.py:32-33`). Any test asserting a `block` severity must therefore use
a rule with no filter stages. The strategies in this spec have none, but a
test that adds a `local_llm` stage will silently see every block become a
warn.

**Why silent passes are treated as defects here.** This is not style
preference. The original hoolint plan shipped a failure path that produced a
passing result in nearly every one of its 13 tasks, and the two security
tasks each needed three review rounds. A failure must be visible: a warn
finding, a raised exception, or a notice. It must never be an empty list that
reads as clean.

## Engine changes

Three changes, all small.

**1. `Context` gains two fields** (`strategies/base.py`):

```python
changed: list[Path] = field(default_factory=list)   # the full change set
matched: list[Path] = field(default_factory=list)   # this rule's glob subset
```

Both are required. `companion` must ask whether `CHANGELOG.md` is in the
change set, and `CHANGELOG.md` never matches a `src/**/*.py` glob, so
`matched` alone cannot answer it. `matched` is required for set-level
anchoring (below).

**2. `_run_rule` populates both** when constructing `Context`
(`engine.py:19`). It already computes `matched` and already receives the full
`files` list, so this is wiring, not new logic.

**3. `engine.run` filters rules by `modes`** before dispatch. A rule-level
`modes = ["git"]` restricts the rule to git mode; omitting the key means both
modes. Filtering at dispatch avoids spawning a thread for a rule that cannot
run.

An unrecognised value in `modes` raises at config load. Silently declining to
run is a silent pass, which this codebase treats as a defect.

## Modules and strategies

Two new modules, four registry entries, following the existing precedent in
`strategies/docs_.py` (two strategy classes in one module, registered
separately).

| Module | Strategies | Data source |
| --- | --- | --- |
| `strategies/changeset_.py` | `companion`, `change_size` | `Context.changed` / `.matched`, no I/O |
| `strategies/githist_.py` | `churn`, `commit_meta` | subprocess to git |

All four are generators: they ignore incoming candidates and produce findings
from the file itself, exactly as `doc_links` does. None of them filter.

The split is by data source, not by theme. It puts every subprocess call
behind one seam, so the failure contract is written and tested once.

### companion

Flags a changed file whose required companion did not also change.

```toml
[[rule]]
id = "api-changelog"
globs = ["src/api/**/*.py"]
severity = "warn"
modes = ["git"]

[[rule.stage]]
strategy = "companion"
requires = "CHANGELOG.md"
message = "public API changed without a CHANGELOG entry"
```

Derived form, for "source changed without its test":

```toml
[[rule.stage]]
strategy = "companion"
requires_from = "src/(.*)\\.py"
requires_to = "tests/test_\\1.py"
message = "source changed without its test"
```

`requires` and `requires_from`/`requires_to` are mutually exclusive.
Supplying both, or supplying `requires_from` without `requires_to`, is a
config error and raises.

Pattern matching and substitution use `google-re2`, already a dependency and
already the engine behind the `regex` strategy. Keeping one regex engine
avoids a second dialect in committed config.

A substituted path that resolves outside the project root is rejected,
matching the containment discipline in `journal.py`, `changes.py`, and
`engine.py`.

`companion` runs in both modes, but "changed" means different things in each.
In git mode it is the diff against the ref, so a CHANGELOG entry added earlier
on the branch satisfies the rule. In session mode it is the journal, so only
files touched since the last check count, and a CHANGELOG edited in an earlier
session does not satisfy it. Projects that find the session reading too strict
should set `modes = ["git"]`, as the example above does.

### change_size

Flags a change set that touches too many files.

```toml
[[rule.stage]]
strategy = "change_size"
max_files = 20
message = "change touches more than 20 files"
```

`max_files` counts `ctx.changed`, the whole change set, since blast radius is
the point. It does not count `ctx.matched`, which is used only to pick the
anchor file (see Set-level anchoring). A rule whose globs match a subset still
reports on the size of the entire change.

Line counts are not available. The session journal records only
`{"file": path}`, with no diff and no line totals, so a line-based threshold
would work in git mode and silently mean nothing in session mode. File count
works identically in both.

### churn

Flags a file revised more than `max_commits` times within `window`.

```toml
[[rule.stage]]
strategy = "churn"
max_commits = 5
window = "30.days"
message = "file is churning; consider whether it has one responsibility"
```

`window` is passed to `git log --since`.

### commit_meta

Flags a malformed commit subject.

```toml
[[rule]]
id = "commit-subject"
globs = ["**/*"]
severity = "warn"
modes = ["git"]

[[rule.stage]]
strategy = "commit_meta"
subject_pattern = "^(feat|fix|docs|test|chore)(\\(.+\\))?: .+"
message = "commit subject does not match the project convention"
```

This is git mode only in practice. At Stop time in a session there is usually
no new commit to inspect.

## Set-level anchoring

`change_size` and `commit_meta` describe the whole change set, not one file.
The engine invokes a strategy once per matched file, so a naive
implementation emits one identical finding per file.

Both strategies therefore emit only when `ctx.path == sorted(ctx.matched)[0]`.
That yields exactly one finding, anchored to a real file with a real span and
a stable fingerprint, and it requires no engine change.

Anchoring on `matched` rather than `changed` is deliberate. Anchoring on
`changed` would let a narrow glob silently prevent the rule from ever firing.

If set-level rules multiply later, a first-class set-level rule shape becomes
worthwhile, and this convention converts to it cleanly.

## Error handling

The `githist_` strategies raise on git failure. `engine._guarded`
(`engine.py:38-46`) already converts any exception into a visible `warn`
finding carrying the exception repr. Missing git binary, not a repository,
non-zero exit, and malformed patterns all become one visible message. None can
produce a silent empty-list "clean".

This reuses tested machinery rather than adding a second degradation path.

Three cases are handled explicitly instead of raising:

- **Unborn HEAD.** A file with no history has a churn count of zero, which is
  a legitimate result, not an error. `test_cli.py` already creates repositories
  in this state, so the case is reachable in the existing suite.
- **Substituted path outside the root.** Rejected as a config error.
- **Unrecognised `modes` value.** Raises at config load.

## Waiver semantics

Metadata findings have no meaningful code span. For `companion`, the span is
the file path, so the fingerprint is constant for that file. A waiver on a
metadata finding is therefore durable: it does not expire when the file
changes.

This is the correct behaviour for this rule family. "This file is exempt from
needing a CHANGELOG entry" is a lasting decision. The alternative, using file
contents as the span, expires the waiver on every edit and forces constant
re-waiving.

It departs from the README's statement that a waiver stops matching once the
excused span changes, so the README must record that metadata waivers are
durable by design.

## Testing

`changeset_.py` is pure, so it is tested with synthetic `Context` objects:

- companion, fixed target: satisfied, and violated
- companion, derived pattern: substitution hit, substitution miss
- companion: mutually exclusive config raises
- companion: substituted path escaping the root is rejected
- change_size: under threshold, over threshold
- change_size: emits exactly once across N matched files

`githist_.py` is tested against real repositories in `tmp_path`, following the
existing pattern in `test_changes.py`:

- churn over and under threshold
- churn on unborn HEAD yields no finding rather than crashing
- commit_meta subject matching and failing
- a git failure produces a non-empty finding list

That last test is the discriminating one. It must fail against an
implementation that swallows the error and returns `[]`.

Engine tests cover `modes` filtering in both directions and confirm that
`Context.changed` and `Context.matched` are populated correctly.

## Out of scope

- Capability #7, retrieval-augmented doc checks.
- Capability #1, AST and structural analysis via Beacon.
- Line-based change size, which the journal cannot support.
- A first-class set-level rule shape in the engine.

## Known debt recorded, not fixed here

`_guarded` builds its failure findings with `span_text=""`, giving them a
constant fingerprint, so a waiver on a crashed rule never expires. This
predates the current work. Routing git failures through `_guarded` makes it
more reachable, which is worth noting when it is eventually addressed.

## Success criteria

1. All four strategies are registered and reachable from TOML config.
2. `defaults.toml` is unchanged; no rule is enabled by default.
3. The README documents all four as copy-paste config, and records that
   metadata waivers are durable.
4. A git failure surfaces a visible warn finding, proven by a test that fails
   against a swallow-the-error implementation.
5. The existing suite still passes, with the new tests added.
