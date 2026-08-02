# judge-proxy warm pool: implementation report

Plan: `docs/superpowers/plans/2026-08-01-judge-proxy-warm-pool.md`
Base: `7947214`. Head after this work: `759804a`. All 7 tasks complete.

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

## Remaining issues

None. Pyright reports unresolved `fastapi` and `openai_route` imports and
`Optional` member access inside `_Judge`; all are pre-existing and stem from
pyright not using the project's `.venv`, not from this change.
