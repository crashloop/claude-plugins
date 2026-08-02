# judge-proxy warm process pool (design)

**Date:** 2026-08-01. **Status:** approved, ready for planning.
**Scope:** `tools/judge-proxy` only. This is benchmark harness work; nothing in
the hoolint package references the proxy, and this spec does not change that.

## Decisions taken

1. A flat pool of warm processes, not one spare per key and not one per rule.
   Eviction is FIFO on boot time, not LRU: parked spares are by definition
   unused, so there is no recency of use to order them by.
2. Size comes from `JUDGE_PROXY_SPARES`, default 4, where 0 disables prewarming.
3. Spares are held until shutdown; there is no idle reaper.
4. Eviction follows demand, so a rarely-used key can lose its warm start.
5. The pool is keyed by `(model, no_thinking)`, which is what the route already
   derives from a request's `model` and `reasoning_effort`. Those two fields are
   the only thing the proxy can observe about which rule is asking.
6. A separate semaphore caps processes in flight. The pool bounds idle memory and
   would otherwise leave peak memory unbounded.
7. The response reports whether the request was served from a spare, so the
   acceptance measurement reads a boolean rather than inferring from latency.

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
SPARES = max(0, int(os.environ.get("JUDGE_PROXY_SPARES", "4")))
MAX_INFLIGHT = max(1, int(os.environ.get("JUDGE_PROXY_MAX_INFLIGHT", "8")))
_pool: list[_Judge] = []        # oldest boot first
_lock = asyncio.Lock()
_inflight = asyncio.Semaphore(MAX_INFLIGHT)
```

Both values are clamped rather than validated, because a negative pool size has
an obvious intent (none) and no useful error. A non-numeric value raises at
import and the server refuses to start, which is the right outcome for a config
error with no I/O involved.

The `SPARES` default of 4 matches hoolint's `max_workers=4`, the ceiling on
concurrent judged requests.

### Memory

A parked spare holds about 277MB resident. The pool only grows toward its cap if
concurrency does: at a serial workload it oscillates between 0 and 1 spares
forever, so the resting cost is about 277MB, and about 1.1GB is the peak reached
only when 4 requests have been in flight at once.

`MAX_INFLIGHT` bounds the other direction. Without it, N concurrent requests boot
N processes regardless of `SPARES`: 20 simultaneous requests would hold about
5.5GB. hoolint cannot produce that with 4 threads, but the proxy is an HTTP
server on a port and should not depend on its caller for that bound. The default
of 8 sits above hoolint's 4, so the semaphore never engages for the real caller
and acts purely as a backstop. Requests over the limit queue rather than fail, so
no new error path reaches hoolint.

### Lifecycle

**`_take(model, no_thinking)`** holds the lock only to sweep the pool: dead
spares are killed and dropped wherever they appear, not merely before the first
key match, since a dead entry otherwise occupies a cap slot forever. The first
live spare whose key matches is removed and returned. On a miss it boots a fresh
judge **outside the lock**: holding the lock across a 3s boot would serialize
every concurrent request behind the first, which is the problem this change
exists to solve.

**`_warm(model, no_thinking)`** returns immediately when `SPARES` is 0. Otherwise
it boots outside the lock, then takes the lock to append, evicting and killing
the oldest entry first **only if the pool is non-empty and already at `SPARES`**.
Both guards matter: with `SPARES` at 0 an unguarded `len(pool) >= SPARES` is true
against an empty pool and pops from it. It is called after each request for the
key just served, as today.

Take and warm are balanced by construction: a served request removes one spare
and adds one back, so the pool grows toward the cap only on a miss. Once at the
cap, a miss evicts the oldest spare of some other key. Eviction therefore follows
demand: a burst of one key can evict every spare of another, and a rarely-used
rule loses its warm start until it is used again. That is accepted behavior, not
a defect.

**Startup** warms one spare of the default key, as now. The remaining slots fill
from real traffic, because the proxy cannot know the rules' keys before requests
arrive. **Shutdown** kills every spare in the pool.

`JUDGE_PROXY_SPARES=0` makes `_warm` a no-op and every request boot its own
process, as an escape hatch on a loaded box.

### Warm-up behavior

The pool starts with one spare, so a first burst of 4 same-key requests takes one
hit and three misses, then parks 4 replacements. It is warm from the second burst
onward.

Against hoolint's real shape this means only the **first file of each rule** pays
a boot: rules run concurrently, files within a rule run serially, and each served
request warms a replacement for its own key before the rule's next file arrives.
A run with a single file per rule therefore sees almost no benefit, which is a
property of the workload rather than a defect, and it dictates how acceptance is
measured below.

### Response field

`x_judge_proxy` gains `"warm": true|false`, reporting whether the request was
served from a parked spare or booted its own process.

### Invariants

Every judge is in exactly one of three states: parked in the pool, held by one
in-flight request, or killed.

1. A process is never handed to two requests.
2. One prompt per process, killed after serving, so no file's verdicts reach the
   next judgment.
3. The pool never exceeds `SPARES`, and an evicted spare is killed.
4. A spare that died while parked is never handed out, and never keeps a slot.
5. Booting never happens while holding the lock.
6. Live processes never exceed `MAX_INFLIGHT` plus the parked pool.

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
3. A dead parked spare is dropped and killed rather than served, including one
   sitting behind a live spare of another key.
4. At the cap, `_warm` evicts and kills the oldest spare.
5. `SPARES=0` parks nothing and does not raise. A negative value behaves as 0.
6. N concurrent `_take` calls receive N distinct processes.
7. Booting never happens under the lock: the fake's `start` asserts
   `_lock.locked()` is false. Without this, test 6 would still pass if every boot
   serialized behind the lock, which is the failure mode that would silently undo
   the whole change.
8. Shutdown kills every parked spare.
9. `x_judge_proxy["warm"]` is false on a boot and true on a reuse.

This adds `pytest` to the dev group in `pyproject.toml`. That file is inherited
from `llm-faker`, and the README states inherited files are left alone so the
fork stays easy to diff. A one-line dev-dependency addition is the smallest way
to break that rule, and the README should record it rather than leave the
divergence unexplained.

## Acceptance

Measured, not asserted, and recorded in the README with the box's load average
at the time, since every number in this tool has proven load-sensitive.

The probe must judge **at least two files per rule**. A single-file run measures
only the cold burst, where the pool is known to give one hit in four, and would
wrongly read as the pool doing nothing.

- Baseline to beat: at N=4, about 5.6s per request against 2.9s warm at N=1.
- Pass: from the second file onward, `x_judge_proxy["warm"]` is true for every
  request at N=4 concurrency with a filled pool.
- Pass: median per-request latency at N=4, excluding the first burst, is within
  1.5x of the warm N=1 figure measured in the same session on the same box.
- Pass: the alternating-key case pays exactly one boot per key, not one per
  request.

The latency threshold is a ratio against a same-session baseline rather than an
absolute figure, because absolute numbers on this box have moved by a factor of
three with background load.
