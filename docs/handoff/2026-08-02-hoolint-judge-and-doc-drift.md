# Handoff: judge-proxy warm pool, hoolint rule precision, doc-drift

Written 2026-08-02. Repo `/home/carmelo/Desktop/proj/claude-plugins`.

## Where things stand

`main` is level with `origin/main` at `69fca42`. One branch is unmerged:

- `fix/doc-drift-path-resolution` (current, 1 commit `7f57e2d`), green, not merged.

Suites: `hoolint/app` 193 passed, `tools/judge-proxy` 16 passed. Both are run
with `uv run pytest`, never bare `pytest`.

Three branches are fully merged into `main` and safe to delete: `feat/hoolint`,
`feat/hoolint-judgment-rules`, `measure/verbose-comments-precision`.

## What was done, and where to read it

Do not re-derive any of this from the code. Each artifact carries its own
reasoning and its measured numbers.

- **The warm pool, all 7 plan tasks plus the review that followed:**
  `docs/plans/docs/superpowers/plans/2026-08-01-judge-proxy-warm-pool.md.REPORT.md`
- **The plan it executed:**
  `docs/superpowers/plans/2026-08-01-judge-proxy-warm-pool.md`
- **What the verbose-comments judge removes, and what it is worth:**
  `docs/measurements/2026-08-01-verbose-comments-judge.md`
- **Pool behaviour, env vars, measured latencies:** `tools/judge-proxy/README.md`
- **Rule-by-rule prose, including the three new decisions:** `hoolint/README.md`

The report's "Post-implementation review" section covers three defects found
after the plan finished: a shutdown that leaked CLI processes, and two tests
that could not fail. All three were mutation-checked.

## How to measure a judged rule

This is the loop that produced every number above, and the next session will
likely need it.

```bash
cd tools/judge-proxy && uv run uvicorn app:app --port 11435   # separate shell
cd hoolint/app
HOOLINT_LLM_BASE_URL=http://localhost:11435/v1 \
  uv run hoolint check --mode git --ref <root-commit> --root <repo>
```

`HOOLINT_LLM_BASE_URL` overrides the endpoint without editing rule config, so
the shipped `defaults.toml` is what gets measured. Corpora used:
`~/Desktop/proj/structurella` (914 Python files, root commit
`619661543c15fbb6be47fdbc66505905aad60a8e`) and this repo (root commit
`440e4d175a2cd8514763ec76876dd171c26fec9d`).

Stopping the proxy needs the pattern split so `pkill` does not match its own
command line, and the `setsid`/`pkill` lines must be separate Bash calls or the
second kills the shell running it:

```bash
PAT="uvi""corn app:app"; pkill -INT -f "$PAT"
ps -o cmd -C claude --no-headers | grep stream-json   # expect nothing
```

## Open work, most useful first

1. **Merge `fix/doc-drift-path-resolution`.** It is green and measured (142
   findings to 21 on this repo). Nothing blocks it.

2. **The doc-drift residue is a premise problem, not a bug.** Of the 21 that
   remain, roughly 18 are still false: `hoolint.toml`, `hoolint-waivers.toml`,
   `.hoolint/state.json` (files hoolint creates in someone else's project) and
   placeholders like `path/to/file.py`. `_REF` in
   `hoolint/app/src/hoolint/strategies/docs_.py` reads any backticked token
   with a code extension as a claim that a file exists. No resolution logic
   fixes that. Options are waivers, a stage-level `exclude` (the strategy
   currently ignores `stage`), or narrowing `_REF` to refs containing a `/`.
   Measure before choosing.

3. **`comment-banners` volume is unresolved.** It reports 205 findings across
   45 files on structurella, five times what the judge ever saw, because the
   semantic stage had been gating banners out. Fourteen sampled were all
   genuine. It is `warn` and reports zero on this repo. The user was told and
   did not ask for a change, so leave it unless they raise it.

4. **The 39-of-59 versus 1-of-53 banner split comes from one repository.**
   `use-not-leverage` was held to four before shipping. `~/Desktop/proj/permessa`
   is the obvious second corpus.

5. **No shipped rule blocks any more.** Demoting `verbose-comments` was
   deliberate and measured, but it was the last `block` rule, so a stock install
   never stops a session. `doc-broken-links` or `comment-banners` could take a
   gate without inheriting the LLM's instability. The user has been told; they
   have not asked.

## Things that will bite you

- **Verify `origin/main` against the remote, not the cached ref.** Mid-session I
  told the user three times that nothing had been pushed, based on
  `git status`'s stale count. `git ls-remote origin main` showed everything was
  already there. Use `ls-remote` before claiming push state.
- **A hoolint verdict from `local_llm` is not reproducible.** Measured: 11% of
  spans change verdict between runs, and two byte-identical comments in
  different files get opposite stable verdicts. Never treat one run as ground
  truth; run three.
- **`cd` does not persist between Bash calls here.** Several commands failed
  because the working directory had reset to the repo root. Use absolute paths
  or `cd` inside each call.
- **Repo prose rules apply to anything you write:** no em dashes or en dashes,
  never `leverage` or `utilize`, max 100 characters per line, comments at most
  two lines. The repo lints itself for the first two. `tools/judge-proxy/app.py`
  is inherited from `llm-faker` and must not be edited, em dash included.

## Suggested skills

- `superpowers:systematic-debugging` before touching item 2. The last two
  diagnoses in this session were both wrong on first statement and only the
  measurement caught them.
- `superpowers:test-driven-development` for any rule change. Every fix here was
  written test-first and then mutation-checked by reverting the fix and
  confirming the test went red. Two shipped tests were found to be unfalsifiable
  precisely because that step had been skipped.
- `superpowers:verification-before-completion` before reporting any number.
- `superpowers:finishing-a-development-branch` for item 1.
- `ponytail:ponytail` is active for this user and shaped several decisions,
  notably fixing `doc-drift` with config-free logic and shipping
  `comment-banners` as TOML with no new Python.
