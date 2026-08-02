# judge-proxy warm pool: implementation report

Plan: `docs/superpowers/plans/2026-08-01-judge-proxy-warm-pool.md`
Base: `7947214`. Head after this work: `f41547e`. All 7 tasks complete, plus a
review pass recorded at the end.

## Execution note

The plan's tasks were run sequentially, not in parallel batches. Tasks 2 through
7 all write `openai_route.py` or append to the same point in
`tests/test_pool.py`, and Task 4's tests only pass against Task 3's swept
`_take`. The dependency table injected into the plan records this: the graph has
no parallelizable batch, so parallel agents would only have produced merge
conflicts on two files.

## Tasks completed

| task | commit | result |
| --- | --- | --- |
| 1 pool structure and test harness | `053a9f1` | 3 tests pass, live server served a judged request in 2.7s |
| 2 cap, clamping, disable switch | `9a3bf96` | 6 pass, no implementation change needed |
| 3 sweep dead spares | `54f0401` | failed first as predicted, then 8 pass |
| 4 concurrency and lock discipline | `972d206` | 10 pass |
| 5 bound processes in flight | `14471a2` | 11 pass |
| 6 report served-warm | `dfa09b8` | 13 pass |
| 7 measure and document | `759804a` | acceptance criteria met, see below |

## Files changed

- `tools/judge-proxy/openai_route.py`: `_spare` becomes `_pool`, keyed take with
  a dead-spare sweep, `SPARES` and `MAX_INFLIGHT` globals, the serving path
  wrapped in a semaphore, `x_judge_proxy.warm` in the response.
- `tools/judge-proxy/pyproject.toml`: `pytest` and `pytest-asyncio` dev deps,
  `[tool.pytest.ini_options]` with `pythonpath` and `asyncio_mode`.
- `tools/judge-proxy/tests/conftest.py`, `tests/test_pool.py`,
  `tests/test_route.py`: new, 13 tests.
- `tools/judge-proxy/bench_pool.py`: new acceptance probe.
- `tools/judge-proxy/README.md`: pool description, both env vars, the measured
  numbers, and a note that `pyproject.toml` now diverges from upstream.
- `docs/superpowers/plans/2026-08-01-judge-proxy-warm-pool.md`: task dependency
  table (committed with Task 1).

Nothing in the `hoolint` package was touched.

## Tests

```
tools/judge-proxy $ uv run pytest -q     13 passed
hoolint/app      $ uv run pytest -q     181 passed, 1 deselected (unchanged)
```

## Acceptance measurement

`bench_pool.py 4`, two rounds of four concurrent judgments, second round scored,
load average 2.8 to 3.2, 1-request baseline 3.0s in both sessions.

| parked spares | round 2 latencies | served warm | median / baseline |
| --- | --- | --- | --- |
| 1 (the old single slot) | 3.9s, 2.7s, 7.3s, 4.0s | 1 of 4 | 1.31x |
| 4 (default) | 2.6s, 3.4s, 2.4s, 2.8s | 4 of 4 | 0.89x |

Both criteria pass at the default: every scored request reported `warm=True`,
and the median is 0.89x the baseline against a 1.50x limit. The single-slot row
is an extra comparison run with `JUDGE_PROXY_SPARES=1`, not required by the
plan; it is the closest live stand-in for the old behavior and is what the
README's before column reports.

## Assumptions and deviations

- The plan asked for "before and after" numbers in the README without saying how
  to obtain the before. Rather than reuse stale figures from the previous
  section, the probe was re-run against `JUDGE_PROXY_SPARES=1` in the same
  session. That approximates but does not reproduce the old code, which also
  killed a mismatched spare on take. It is labelled as such in the README.
- The `## How the warm spare works` heading was renamed to `## How the warm pool
  works`. The plan named the section by its old title.
- Two pre-existing README lines exceed 100 characters (table rows in `Where the
  seconds went`). They were left alone as pre-existing.

## Post-implementation review, and the fixes it forced

A review pass after Task 7 found three holes the plan left. Fixed in `f41547e`;
the suite is now 16 tests.

**Shutdown leaked CLI processes.** `_shutdown` drained `_pool` but ignored
`_warming`. A prewarm in flight at that moment booted its process and parked it
afterwards, into a pool nobody empties again. Under the old single slot this
leaked one process; with `MAX_INFLIGHT=8` each served request starts a warm, so
up to 8 CLIs at ~277MB could outlive uvicorn. Task 1 Step 8's orphan check
missed it because the warm had already finished by the time it ran. `_shutdown`
is now `async` and awaits `_warming` before draining, which required changing
`test_shutdown_kills_every_parked_spare` to await it.

**Two tests could not fail.** Verified by mutation: with `max(0, ...)` deleted
*and* `async with _inflight:` replaced by `if True:`, the suite stayed 13/13
green.

- `test_negative_spares_clamps_to_zero` reimplemented `max(0, int(...))` in its
  own body and never touched the module. The clamp is now a `_cap` helper used
  by both settings, and the test calls it. A second test pins the
  `MAX_INFLIGHT` floor of 1, which a zero would turn into a deadlock.
- `test_inflight_cap_sits_above_hoolints_own_ceiling` asserted the semaphore's
  initial value only, so Task 5's actual behavior had no coverage.
  `test_requests_over_the_inflight_cap_do_not_overlap` now drives three
  concurrent requests against a cap of 1 and asserts they never overlap.

All three fixes were mutation-checked: reverting each one turns its test red.

**The acceptance ratio's denominator was unverified.** `bench_pool.py` discarded
the baseline's `warm` flag. A cold baseline includes a boot, inflates the
denominator, and lets `median / baseline` pass while proving nothing. The probe
now exits rather than scoring against a cold baseline.

The pattern is visible in the plan itself. Every test with a genuine behavioral
red phase (reuse, thrash, dead-spare sweep, concurrency) bites. The two whose
red was either "expected to pass immediately" (Task 2) or a bare `AttributeError`
(Task 5) were exactly the two that did not.

A live check confirmed the shutdown fix: SIGINT sent while a replacement spare
was booting, `Application shutdown complete` in the log, and no `stream-json`
process left behind.

## Known and accepted

- `MAX_INFLIGHT` bounds requests being served, not total processes. Replacement
  spares boot outside the semaphore, so the real ceiling is about
  `2 * MAX_INFLIGHT + SPARES`, roughly 20 at defaults. The README now says so
  rather than implying 8.
- `_warm` evicts strictly oldest-first without preferring dead entries, so a
  corpse can outlive a live spare until the next `_take` sweeps it. One wasted
  slot for one request; not worth the branch.
- Pyright reports unresolved `fastapi` and `openai_route` imports and `Optional`
  member access inside `_Judge`. All pre-existing, and they stem from pyright
  not using the project's `.venv`.
- Two README lines exceed 100 characters and `app.py` contains an em dash. Both
  pre-existing, and `app.py` is inherited from `llm-faker` and must not be
  edited.
