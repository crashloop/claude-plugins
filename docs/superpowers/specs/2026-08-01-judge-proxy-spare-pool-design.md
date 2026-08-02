# judge-proxy warm process pool (design)

**Date:** 2026-08-01. **Status:** approved, ready for planning.
**Scope:** `tools/judge-proxy` only. This is benchmark harness work; nothing in
the hoolint package references the proxy, and this spec does not change that.

## Decisions taken

1. A flat LRU pool of warm processes, not one spare per key and not one per rule.
2. Size comes from `JUDGE_PROXY_SPARES`, default 4, where 0 disables prewarming.
3. Spares are held until shutdown; there is no idle reaper.
4. Eviction follows demand, so a rarely-used key can lose its warm start.
5. The pool is keyed by `(model, no_thinking)`, which is what the route already
   derives from a request's `model` and `reasoning_effort`. Those two fields are
   the only thing the proxy can observe about which rule is asking.

## Problem

`tools/judge-proxy` answers hoolint's `local_llm` stage by running the Claude
Code CLI. It parks exactly one booted spare process. That was correct when
`verbose-comments` was the only rule with a `local_llm` stage, because hoolint
could never issue two judged requests at once.

Multiple `local_llm` rules are coming, with model and `reasoning_effort` both
varying (roughly 3 to 4 distinct combinations, with duplicates among them). Two
things break at that point:

**Thrash.** A spare is only reusable by a request with the same
`(model, reasoning_effort)`. With one slot, `_take` kills a spare whose key does
not match, and `_warm` then boots a replacement for the key it just served. Two
rules with different keys alternating means every request kills the wrong spare
and boots fresh, which is worse than holding no spare at all because it also
wastes a process each time. This is read from the code path, not measured.

**Unserved concurrency.** `engine.py:70` runs rules in a
`ThreadPoolExecutor(max_workers=4)`; files within a rule are serial
(`engine.py:34`). So up to 4 judged requests can be in flight. Measured over two
reps, throughput roughly doubles from N=1 to N=4 (about 20 to about 42 req/min),
so the concurrency is worth serving. What it costs today is latency: each
request at N=4 takes about 5.6s against 2.9s for a warm single request, and that
gap is the boot each request pays for itself.

## Alternatives rejected

- **One spare per key** (`dict[key, _Judge]`). Guarantees coverage of N distinct
  keys but structurally cannot cover two concurrent requests of the *same* key,
  which the expected rule set contains.
- **No pool, startup prewarm only** (status quo). Leaves the thrash regression in
  place, which arrives with the new rules.

The pool is not keyed by rule. The proxy never sees a rule id, only an OpenAI
request, so two rules with the same model and effort are served identically.

## Design

### Structure

```python
SPARES = int(os.environ.get("JUDGE_PROXY_SPARES", "4"))   # 0 disables prewarming
_pool: list[_Judge] = []   # oldest first
_lock = asyncio.Lock()
```

The default of 4 matches hoolint's `max_workers=4`, the ceiling on concurrent
judged requests. A parked spare holds about 277MB resident, so a full pool costs
about 1.1GB while the server is up.

### Lifecycle

**`_take(model, no_thinking)`** holds the lock only to scan the pool for the
first spare whose key matches and which is still alive, removing it. Dead spares
encountered during the scan are killed and dropped. On a miss it boots a fresh
judge **outside the lock**: holding the lock across a 3s boot would serialize
every concurrent request behind the first, which is the problem this change
exists to solve.

**`_warm(model, no_thinking)`** boots outside the lock, then takes the lock to
append. If the pool is already at `SPARES`, it evicts and kills the oldest entry
first. It is called after each request for the key just served, as today.

Take and warm are balanced by construction: a served request removes one spare
and adds one back, so the pool grows toward the cap only on a miss. Once at the
cap, a miss evicts the least recently warmed spare of some other key. Eviction
therefore follows demand: a burst of one key can evict every spare of another,
and a rarely-used rule loses its warm start until it is used again. That is
accepted behavior, not a defect.

**Startup** warms one spare of the default key, as now. The remaining slots fill
from real traffic, because the proxy cannot know the rules' keys before requests
arrive. **Shutdown** kills every spare in the pool.

`JUDGE_PROXY_SPARES=0` makes `_warm` a no-op and every request boot its own
process, as an escape hatch on a loaded box.

### Invariants

Every judge is in exactly one of three states: parked in the pool, held by one
in-flight request, or killed.

1. A process is never handed to two requests.
2. One prompt per process, killed after serving, so no file's verdicts reach the
   next judgment.
3. The pool never exceeds `SPARES`, and an evicted spare is killed.
4. A spare that died while parked is never handed out.
5. Booting never happens while holding the lock.

### Error handling

Unchanged from the current route. A prewarm failure is swallowed, since
prewarming is an optimisation and must not fail a request. A judge that dies or
times out mid-request yields HTTP 502, which hoolint reads as "judge
unavailable" and which demotes the rule to advisory rather than silently
clearing every candidate.

## Testing

`tools/judge-proxy` has no tests today. `_take` and `_warm` look `_Judge` up as a
module global, so tests monkeypatch it with a fake that records `start` and
`kill` and never spawns a subprocess. No seam code is added to production.

1. A matching key in the pool is reused; the fake's `start` is not called again.
2. A non-matching key boots fresh and does not evict blindly. This is the thrash
   regression that motivates the change, so it gets an explicit test.
3. A dead parked spare is dropped and killed rather than served.
4. At the cap, `_warm` evicts and kills the oldest spare.
5. `SPARES=0` parks nothing.
6. N concurrent `_take` calls receive N distinct processes.
7. Shutdown kills every parked spare.

This adds `pytest` to the dev group in `pyproject.toml`. That file is inherited
from `llm-faker`, and the README states inherited files are left alone so the
fork stays easy to diff. A one-line dev-dependency addition is the smallest way
to break that rule, and the README should record it rather than leave the
divergence unexplained.

## Acceptance

Measured, not asserted. Re-run the existing concurrency probe and record
before/after in the README, with the box's load average, since every number in
this tool has proven load-sensitive.

- Baseline to beat: at N=4, about 5.6s per request against 2.9s warm at N=1.
- Target: N=4 per-request latency approaching the warm single-request figure once
  the pool is filled.
- The alternating-key case stops paying a boot on every request.
