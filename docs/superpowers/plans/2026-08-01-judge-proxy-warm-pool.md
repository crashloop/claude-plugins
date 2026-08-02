# judge-proxy Warm Process Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace judge-proxy's single warm CLI process with a keyed pool, so several hoolint `local_llm` rules with different models and thinking settings stop thrashing one shared slot.

**Architecture:** `tools/judge-proxy/openai_route.py` keeps a module-level list of booted `_Judge` processes, keyed by `(model, no_thinking)`. A request takes the first matching live spare or boots its own; after serving, it warms a replacement for the key it used. Eviction is FIFO on boot time once the pool reaches `JUDGE_PROXY_SPARES`. A semaphore separately bounds processes in flight.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, asyncio subprocesses, pytest, `uv` for dependency and test running.

## Starting state (read this first)

This plan builds on `29f5c08`, "perf(judge-proxy): warm the CLI, drop the chrome,
honour reasoning_effort". Start from that commit or later. Before Task 1, confirm
`tools/judge-proxy/openai_route.py` contains all of:

- a `_Judge` class with `key`, `async start()`, `async ask()`, `alive()`, `kill()`
- a module-level `_spare: _Judge | None` and `_lock`
- `_warm`, `_take`, `_startup`, `_shutdown`, and `router.add_event_handler` calls
- `BASE_ARGS` containing `--input-format stream-json`

If instead you find a `_run_claude` function and no `_Judge` class, you are on
`d7f0548` or earlier and the prerequisite work is missing. Stop and say so.

The same applies to hoolint, from `ff08635`: `strategies/local_llm.py` must already
forward `reasoning_effort`, and `defaults.toml` must already set it on
`verbose-comments`. Neither is touched by this plan, but the acceptance
measurement sends `reasoning_effort` and would otherwise measure a thinking judge.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-judge-proxy-spare-pool-design.md`. Read it before starting.
- Max line length 100 characters.
- Google-style docstrings on all public functions and classes.
- Comments are at most 2 lines and carry only crucial information.
- No em dashes, en dashes, or ellipses in prose or markdown. Use commas, periods, or parentheses.
- Never write `leverage` or `utilize` in markdown. Write `use`. This repo lints itself for both.
- All commands run from `tools/judge-proxy/` unless stated otherwise.
- Run tests with `uv run pytest`, never bare `pytest`.
- `tools/judge-proxy/app.py`, `refusals.py`, and the JSON fixtures are inherited from the `llm-faker` fork and must not be edited. `pyproject.toml` gets exactly the two additions in Task 1 and no others.
- Do not add anything to the `hoolint` package that references this proxy. It is a benchmark harness that forwards code to Anthropic, which is what hoolint's loopback pinning exists to prevent.

---

### Task 1: Test harness and the pool structure

Replaces the single `_spare` slot with a capped list. This task leaves the server working end to end.

**Files:**
- Modify: `tools/judge-proxy/pyproject.toml` (add pytest dev dep and pytest config)
- Modify: `tools/judge-proxy/openai_route.py:130-191` (the `_spare` block through the event handlers)
- Create: `tools/judge-proxy/tests/conftest.py`
- Create: `tools/judge-proxy/tests/test_pool.py`

**Interfaces:**
- Consumes: existing `_Judge` class with `.key`, `async start()`, `async ask(prompt)`, `alive()`, `kill()`.
- Produces:
  - `SPARES: int` module global, read at call time by `_warm`.
  - `_pool: list[_Judge]`, oldest boot first.
  - `async _take(model: str, no_thinking: bool) -> tuple[_Judge, bool]` returning the judge and whether it came from the pool. **The return type changes from `_Judge` to a tuple in this task**; Task 6 consumes the boolean.
  - `async _warm(model: str, no_thinking: bool) -> None`.

- [ ] **Step 1: Add the test dependency and pytest path config**

Edit `tools/judge-proxy/pyproject.toml`. Add both test dependencies to the existing dev group and append a pytest section. `pythonpath` is required because `openai_route.py` sits at the project root rather than in a package, and without it `import openai_route` fails from `tests/`. `asyncio_mode` is required because every pool test is a coroutine; without it pytest reports "async def functions are not natively supported" instead of running them.

```toml
[dependency-groups]
dev = [
    "anthropic>=0.40",
    "httpx>=0.27",
    "pytest>=7.0",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
```

- [ ] **Step 2: Write the fake judge and pool-reset fixture**

Create `tools/judge-proxy/tests/conftest.py`:

```python
"""Test doubles for the judge pool.

The real `_Judge` spawns a Claude Code CLI process that takes seconds to boot.
Tests swap in a fake so pool mechanics can be exercised in milliseconds.
"""
import pytest

import openai_route


class FakeJudge:
    """Stands in for `_Judge` without spawning anything."""

    made: list["FakeJudge"] = []      # every instance, in creation order

    def __init__(self, model: str, no_thinking: bool):
        self.key = (model, no_thinking)
        self.started = False
        self.killed = False
        self.crashed = False       # simulates the CLI exiting while parked
        FakeJudge.made.append(self)

    async def start(self) -> None:
        # Invariant 5: a boot must never happen while the pool lock is held,
        # or every concurrent request serializes behind the first boot.
        assert not openai_route._lock.locked(), "booted while holding the pool lock"
        self.started = True

    async def ask(self, prompt: str) -> str:
        return "[0] VIOLATION: fake verdict"

    def alive(self) -> bool:
        return self.started and not self.killed and not self.crashed

    def kill(self) -> None:
        self.killed = True


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    """Give every test an empty pool, a fake judge, and a known cap."""
    monkeypatch.setattr(openai_route, "_Judge", FakeJudge)
    monkeypatch.setattr(openai_route, "SPARES", 4)
    FakeJudge.made.clear()
    openai_route._pool.clear()
    yield openai_route._pool
    openai_route._pool.clear()
    FakeJudge.made.clear()
```

- [ ] **Step 3: Write the failing tests**

Create `tools/judge-proxy/tests/test_pool.py`. These are the final imports for this
file; later tasks append tests to it and do not change the header.

```python
import asyncio
import os

import pytest

import openai_route

HAIKU_FAST = ("haiku", True)
SONNET_SLOW = ("sonnet", False)


@pytest.mark.asyncio
async def test_matching_key_is_reused_not_rebooted(pool):
    await openai_route._warm(*HAIKU_FAST)
    parked = pool[0]

    judge, warm = await openai_route._take(*HAIKU_FAST)

    assert judge is parked
    assert warm is True
    assert pool == []


@pytest.mark.asyncio
async def test_non_matching_key_boots_fresh_and_keeps_the_other_spare(pool):
    """The thrash regression: a mismatched key must not destroy the pool.

    With the old single slot, taking key B killed the parked A and warmed B,
    so alternating rules booted on every request and wasted a process each time.
    """
    await openai_route._warm(*HAIKU_FAST)
    parked = pool[0]

    judge, warm = await openai_route._take(*SONNET_SLOW)

    assert judge is not parked
    assert warm is False
    assert judge.key == SONNET_SLOW
    assert pool == [parked], "the haiku spare must survive a sonnet request"
    assert parked.killed is False


@pytest.mark.asyncio
async def test_shutdown_kills_every_parked_spare(pool):
    """Uvicorn exiting must not leave orphan CLI processes behind."""
    await openai_route._warm(*HAIKU_FAST)
    await openai_route._warm(*SONNET_SLOW)
    parked = list(pool)

    openai_route._shutdown()

    assert pool == []
    assert all(j.killed for j in parked)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pool.py -v`
Expected: FAIL. `AttributeError: module 'openai_route' has no attribute '_pool'`.

- [ ] **Step 5: Replace the single slot with the pool**

In `tools/judge-proxy/openai_route.py`, replace the block from the `# One spare, not a pool.` comment through `def _shutdown()` (currently lines 130 to 188) with:

```python
# A pool, not one spare: several rules judge at once and their (model, thinking)
# keys differ, so one slot would be killed and rebooted on every other request.
SPARES = max(0, int(os.environ.get("JUDGE_PROXY_SPARES", "4")))
_pool: list[_Judge] = []        # oldest boot first
_lock = asyncio.Lock()
# asyncio keeps only a weak reference to a running task, so a fire-and-forget
# prewarm can be collected mid-boot. Holding it here is what makes it happen.
_warming: set[asyncio.Task] = set()


async def _warm(model: str, no_thinking: bool) -> None:
    """Boot a spare and park it, evicting the oldest if the pool is full.

    Args:
        model: Model name the spare is booted with.
        no_thinking: Whether the spare runs with thinking disabled.
    """
    if SPARES <= 0:
        return
    judge = _Judge(model, no_thinking)
    try:
        await judge.start()
    except (OSError, RuntimeError, asyncio.TimeoutError):
        return  # Prewarming is an optimisation; a failure must not fail a request.
    async with _lock:
        while _pool and len(_pool) >= SPARES:
            _pool.pop(0).kill()
        _pool.append(judge)


async def _take(model: str, no_thinking: bool) -> tuple[_Judge, bool]:
    """Return a ready process, reusing a parked spare when one matches.

    Args:
        model: Model name the request wants.
        no_thinking: Whether the request wants thinking disabled.

    Returns:
        The judge to serve this request, and whether it came from the pool.
    """
    key = (model, no_thinking)
    async with _lock:
        for judge in _pool:
            if judge.key == key:
                _pool.remove(judge)
                return judge, True
    # Booting outside the lock: holding it across a 3s boot would serialize
    # every concurrent request behind the first, which is what this pool fixes.
    fresh = _Judge(model, no_thinking)
    await fresh.start()
    return fresh, False


async def _startup() -> None:
    """Park one spare before the first request, guessing the common key.

    Rules that judge through this proxy are expected to set
    `reasoning_effort = "none"`, so that is the guess. The remaining slots fill
    from real traffic, since the keys in use are not knowable in advance.
    """
    await _warm(DEFAULT_MODEL, no_thinking=True)


def _shutdown() -> None:
    """Kill every parked spare so uvicorn leaves no orphan CLI behind."""
    while _pool:
        _pool.pop().kill()
```

- [ ] **Step 6: Update the route's call site**

`_take` now returns a tuple. In `chat_completions`, change the take line (currently line 241) from:

```python
        judge = await _take(model, no_thinking)
```

to:

```python
        judge, warm = await _take(model, no_thinking)
```

Task 6 uses `warm`. Until then it is assigned and unused, which is intentional and lasts one task.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pool.py -v`
Expected: PASS, 3 passed.

- [ ] **Step 8: Verify the server still starts and serves**

Run:

```bash
setsid nohup uv run uvicorn app:app --port 11435 > /tmp/pool-check.log 2>&1 < /dev/null &
until curl -s -m 2 localhost:11435/ >/dev/null 2>&1; do sleep 1; done
curl -sS -X POST localhost:11435/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"qwen3:4b","reasoning_effort":"none",
       "messages":[{"role":"user","content":"Judge item 1: `assert mock.called`."}]}'
```

Expected: JSON with a `choices[0].message.content` starting `[1] VIOLATION:` or `[1] OK:`.

Then stop it. Build the pattern in two pieces so `pkill` does not match its own command line, which kills the shell running it:

```bash
PAT="uvi""corn app:app"; pkill -INT -f "$PAT"
ps -o pid,cmd -C claude | grep stream-json || echo "no orphan CLI processes"
```

Expected: no orphan processes.

- [ ] **Step 9: Commit**

```bash
git add tools/judge-proxy/pyproject.toml tools/judge-proxy/openai_route.py tools/judge-proxy/tests/
git commit -m "feat(judge-proxy): a pool of warm processes instead of one spare

One slot was right while verbose-comments was the only local_llm rule. With
rules whose model and thinking settings differ, a mismatched key was killed on
take and rebooted for the key just served, so alternating rules paid a boot
every request and wasted a process doing it."
```

---

### Task 2: Cap, clamping, and the disable switch

`SPARES=0` is the documented escape hatch and currently pops from an empty pool.

**Files:**
- Modify: `tools/judge-proxy/openai_route.py` (`_warm`, already guarded in Task 1)
- Modify: `tools/judge-proxy/tests/test_pool.py`

**Interfaces:**
- Consumes: `SPARES`, `_pool`, `_warm` from Task 1.
- Produces: no new symbols. Confirms `SPARES <= 0` parks nothing and the cap evicts oldest-first.

- [ ] **Step 1: Write the failing tests**

Append to `tools/judge-proxy/tests/test_pool.py`:

```python
@pytest.mark.asyncio
async def test_pool_never_exceeds_the_cap_and_evicts_oldest(pool, monkeypatch):
    monkeypatch.setattr(openai_route, "SPARES", 2)

    await openai_route._warm(*HAIKU_FAST)
    oldest = pool[0]
    await openai_route._warm(*SONNET_SLOW)
    await openai_route._warm(*HAIKU_FAST)

    assert len(pool) == 2
    assert oldest not in pool
    assert oldest.killed is True, "an evicted spare must be killed, not dropped"


@pytest.mark.asyncio
async def test_spares_zero_parks_nothing_and_does_not_raise(pool, monkeypatch):
    """The documented escape hatch. An unguarded cap check pops an empty list."""
    monkeypatch.setattr(openai_route, "SPARES", 0)

    await openai_route._warm(*HAIKU_FAST)

    assert pool == []


def test_negative_spares_clamps_to_zero(monkeypatch):
    """A negative pool size has an obvious intent (none) and no useful error."""
    monkeypatch.setenv("JUDGE_PROXY_SPARES", "-1")
    assert max(0, int(os.environ["JUDGE_PROXY_SPARES"])) == 0
```

- [ ] **Step 2: Run the tests to verify they fail or pass**

Run: `uv run pytest tests/test_pool.py -v`
Expected: all three PASS, because Task 1 already wrote `max(0, ...)` and the `if SPARES <= 0` guard. If any fail, the Task 1 implementation drifted from the plan. Fix the implementation, not the test.

- [ ] **Step 3: Commit**

```bash
git add tools/judge-proxy/tests/test_pool.py
git commit -m "test(judge-proxy): pin the pool cap, eviction, and the disable switch"
```

---

### Task 3: Sweep dead spares out of the pool

The CLI has its own idle timeout. A spare that died while parked must never be served, and must not keep occupying a cap slot.

**Files:**
- Modify: `tools/judge-proxy/openai_route.py` (`_take`)
- Modify: `tools/judge-proxy/tests/test_pool.py`

**Interfaces:**
- Consumes: `_take` from Task 1.
- Produces: `_take` additionally drops and kills every non-alive spare it sees, anywhere in the list.

- [ ] **Step 1: Write the failing tests**

Append to `tools/judge-proxy/tests/test_pool.py`:

```python
@pytest.mark.asyncio
async def test_dead_spare_is_never_served(pool):
    await openai_route._warm(*HAIKU_FAST)
    pool[0].crashed = True

    judge, warm = await openai_route._take(*HAIKU_FAST)

    assert warm is False, "a corpse must not be handed to a request"
    assert judge.alive()


@pytest.mark.asyncio
async def test_dead_spare_behind_a_live_one_does_not_keep_a_slot(pool):
    """A dead entry of another key is never reached by a key-matching scan,
    so it would sit in the pool forever shrinking the effective cap."""
    await openai_route._warm(*SONNET_SLOW)
    pool[0].crashed = True
    await openai_route._warm(*HAIKU_FAST)
    corpse = pool[0]

    judge, warm = await openai_route._take(*HAIKU_FAST)

    assert warm is True
    assert corpse not in pool
    assert corpse.killed is True
    assert pool == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pool.py -v`
Expected: FAIL. `test_dead_spare_is_never_served` fails with `assert warm is False` because the current scan matches on key alone and hands over the corpse.

- [ ] **Step 3: Add the sweep to `_take`**

In `openai_route.py`, replace the whole `_take` function with the version below. The
only change is the first loop inside the lock, but the complete function is given so
there is no splicing to get wrong.

```python
async def _take(model: str, no_thinking: bool) -> tuple[_Judge, bool]:
    """Return a ready process, reusing a parked spare when one matches.

    Args:
        model: Model name the request wants.
        no_thinking: Whether the request wants thinking disabled.

    Returns:
        The judge to serve this request, and whether it came from the pool.
    """
    key = (model, no_thinking)
    async with _lock:
        # Sweep the whole list, not just up to the first key match: a dead entry
        # of another key would otherwise hold a cap slot forever.
        for judge in list(_pool):
            if not judge.alive():
                judge.kill()
                _pool.remove(judge)
        for judge in _pool:
            if judge.key == key:
                _pool.remove(judge)
                return judge, True
    # Booting outside the lock: holding it across a 3s boot would serialize
    # every concurrent request behind the first, which is what this pool fixes.
    fresh = _Judge(model, no_thinking)
    await fresh.start()
    return fresh, False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pool.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/judge-proxy/openai_route.py tools/judge-proxy/tests/test_pool.py
git commit -m "fix(judge-proxy): never serve a spare that died while parked

The CLI has its own idle timeout. Handing over a corpse 502s the request, and
hoolint reads a 502 as judge-unavailable and quietly demotes the rule to
advisory on what is really a harness problem."
```

---

### Task 4: Concurrency and the lock discipline

The pool exists to let concurrent requests proceed. If a boot ever happens under the lock they all serialize, and the change silently achieves nothing.

**Files:**
- Modify: `tools/judge-proxy/tests/test_pool.py`

**Interfaces:**
- Consumes: `_take`, `_lock`, `FakeJudge.start` (which already asserts the lock is free).
- Produces: no new symbols.

- [ ] **Step 1: Write the failing tests**

Append to `tools/judge-proxy/tests/test_pool.py`.

```python
@pytest.mark.asyncio
async def test_concurrent_takes_get_distinct_processes(pool):
    await openai_route._warm(*HAIKU_FAST)

    results = await asyncio.gather(
        *(openai_route._take(*HAIKU_FAST) for _ in range(4)))

    judges = [j for j, _ in results]
    assert len({id(j) for j in judges}) == 4, "a process was handed to two requests"
    assert [w for _, w in results].count(True) == 1, "only one spare was parked"


@pytest.mark.asyncio
async def test_boot_does_not_happen_under_the_pool_lock(pool):
    """FakeJudge.start asserts the lock is free. Without that, the test above
    would still pass while every boot serialized behind the first."""
    judge, warm = await openai_route._take(*SONNET_SLOW)

    assert warm is False
    assert judge.started is True
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pool.py -v`
Expected: PASS, 10 passed. These pin behavior Task 1 already built. If `test_boot_does_not_happen_under_the_pool_lock` fails with "booted while holding the pool lock", the `await fresh.start()` in `_take` was written inside the `async with _lock` block. Move it out.

- [ ] **Step 3: Commit**

```bash
git add tools/judge-proxy/tests/test_pool.py
git commit -m "test(judge-proxy): pin that concurrent takes do not share or serialize"
```

---

### Task 5: Bound processes in flight

`SPARES` caps parked memory. Nothing caps peak: 20 simultaneous requests boot 20 processes at roughly 277MB each.

**Files:**
- Modify: `tools/judge-proxy/openai_route.py` (module globals and `chat_completions`)
- Modify: `tools/judge-proxy/tests/test_pool.py`

**Interfaces:**
- Consumes: `chat_completions` from the existing route.
- Produces: `MAX_INFLIGHT: int` and `_inflight: asyncio.Semaphore` module globals.

- [ ] **Step 1: Write the failing test**

Append to `tools/judge-proxy/tests/test_pool.py`:

```python
def test_inflight_cap_sits_above_hoolints_own_ceiling():
    """hoolint runs rules in a 4-thread pool, so the backstop must never engage
    for the real caller. It exists because the proxy is an HTTP server on a port
    and should not depend on its caller for a memory bound."""
    assert openai_route.MAX_INFLIGHT >= 4
    assert openai_route._inflight._value == openai_route.MAX_INFLIGHT
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pool.py::test_inflight_cap_sits_above_hoolints_own_ceiling -v`
Expected: FAIL. `AttributeError: module 'openai_route' has no attribute 'MAX_INFLIGHT'`.

- [ ] **Step 3: Add the semaphore**

In `openai_route.py`, directly below the `SPARES` line, add:

```python
# SPARES bounds idle memory; this bounds peak. Requests over the limit queue
# rather than fail, so no new error path reaches hoolint.
MAX_INFLIGHT = max(1, int(os.environ.get("JUDGE_PROXY_MAX_INFLIGHT", "8")))
_inflight = asyncio.Semaphore(MAX_INFLIGHT)
```

- [ ] **Step 4: Wrap the serving path in the semaphore**

In `chat_completions`, wrap everything from the `started = time.monotonic()` line through the `finally:` block in `async with _inflight:`, and indent that region by 4 spaces. The result reads:

```python
    started = time.monotonic()
    async with _inflight:
        try:
            judge, warm = await _take(model, no_thinking)
        except (OSError, RuntimeError, asyncio.TimeoutError) as exc:
            return JSONResponse(status_code=502, content={
                "error": {"type": "api_error",
                          "message": f"claude failed to start: {exc}"}})

        try:
            out = await asyncio.wait_for(
                judge.ask(_prompt_from(messages)), timeout=TIMEOUT_S)
        except (asyncio.TimeoutError, RuntimeError) as exc:
            # 502 rather than a 200 with empty content: hoolint treats an HTTP
            # error as "judge unavailable" and demotes the rule to advisory,
            # whereas an empty 200 would read as "every candidate cleared".
            detail = f"timed out after {TIMEOUT_S}s" if isinstance(
                exc, asyncio.TimeoutError) else str(exc)[:300]
            return JSONResponse(status_code=502, content={
                "error": {"type": "api_error", "message": f"claude -p failed: {detail}"}})
        finally:
            # One prompt per process: a reused session would carry the previous
            # file's verdicts into the next judgment and grow the prompt each call.
            judge.kill()
            task = asyncio.create_task(_warm(model, no_thinking))
            _warming.add(task)
            task.add_done_callback(_warming.discard)
```

The `return` dict that follows stays at its current indentation, outside the `async with`.

- [ ] **Step 5: Run the full suite to verify it passes**

Run: `uv run pytest -v`
Expected: PASS, 11 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/judge-proxy/openai_route.py tools/judge-proxy/tests/test_pool.py
git commit -m "feat(judge-proxy): bound processes in flight, not just parked ones

SPARES caps idle memory and left peak unbounded: 20 concurrent requests would
boot 20 CLI processes at ~277MB each. The default of 8 sits above hoolint's
4-thread ceiling, so it never engages for the real caller."
```

---

### Task 6: Report whether the request was served warm

Makes the acceptance measurement read a boolean instead of inferring from latency, which matters because every timing number in this tool has moved with box load.

**Files:**
- Modify: `tools/judge-proxy/openai_route.py` (the response dict at the end of `chat_completions`)
- Create: `tools/judge-proxy/tests/test_route.py`

**Interfaces:**
- Consumes: the `warm` boolean from `_take`, already bound in Task 1.
- Produces: `x_judge_proxy["warm"]` in the response body.

- [ ] **Step 1: Write the failing test**

Create `tools/judge-proxy/tests/test_route.py`:

```python
"""End-to-end checks over the HTTP route, with the CLI faked out.

httpx's ASGI transport rather than fastapi's TestClient: the replacement spare
is warmed by a background task, and only a client sharing this test's event loop
lets the test yield to that task deterministically. TestClient drives the app on
its own portal, so `len(pool)` right after a response is a race.
"""
import asyncio

import httpx
import pytest

import app as app_module
from conftest import FakeJudge

BODY = {"model": "qwen3:4b", "reasoning_effort": "none",
        "messages": [{"role": "user", "content": "Judge item 1: `assert x`."}]}


async def _settle() -> None:
    """Let the fire-and-forget warm task reach the pool."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_warm_flag_is_false_on_a_boot_and_true_on_a_reuse(pool):
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        first = (await client.post("/v1/chat/completions", json=BODY)).json()
        assert first["x_judge_proxy"]["warm"] is False

        await _settle()
        assert len(pool) == 1, "the request must warm a replacement for its key"

        second = (await client.post("/v1/chat/completions", json=BODY)).json()
        assert second["x_judge_proxy"]["warm"] is True


@pytest.mark.asyncio
async def test_the_serving_process_is_killed_and_never_reused(pool):
    """One prompt per process. A reused session would carry the previous file's
    verdicts into the next judgment and grow the prompt on every call."""
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        await client.post("/v1/chat/completions", json=BODY)
        await _settle()

    served = FakeJudge.made[0]
    assert served.killed is True
    assert served not in pool
```

The ASGI transport does not run startup handlers, so the pool starts empty here
and the first request is a genuine boot. That is deliberate: it keeps the test
independent of what `_startup` happens to warm.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_route.py -v`
Expected: FAIL with `KeyError: 'warm'`.

- [ ] **Step 3: Add the field**

In `openai_route.py`, change the `x_judge_proxy` entry of the returned dict from:

```python
        "x_judge_proxy": {"seconds": round(time.monotonic() - started, 1),
                          "thinking": not no_thinking},
```

to:

```python
        "x_judge_proxy": {"seconds": round(time.monotonic() - started, 1),
                          "thinking": not no_thinking, "warm": warm},
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `uv run pytest -v`
Expected: PASS, 13 passed.

If the `len(pool) == 1` assertion fails, `_warm` is not being called in the `finally` block. The fake boots without any real await, so three loop yields are ample.

- [ ] **Step 5: Commit**

```bash
git add tools/judge-proxy/openai_route.py tools/judge-proxy/tests/test_route.py
git commit -m "feat(judge-proxy): report whether a request was served from a spare

Acceptance now reads a boolean rather than inferring a pool hit from latency,
which on this box has moved by a factor of three with background load."
```

---

### Task 7: Measure it, then document what was measured

The spec's acceptance criteria. A committed probe, because these numbers get re-measured every time the box or the CLI changes.

**Files:**
- Create: `tools/judge-proxy/bench_pool.py`
- Modify: `tools/judge-proxy/README.md`

**Interfaces:**
- Consumes: a running proxy on port 11435 and the `x_judge_proxy.warm` field from Task 6.
- Produces: nothing importable. A script and a documented result.

- [ ] **Step 1: Write the probe**

Create `tools/judge-proxy/bench_pool.py`:

```python
"""Measure the warm pool against the spec's acceptance criteria.

Judges two rounds of N concurrent requests. The first round is cold by
construction (the pool starts with one spare), so only the second is scored.
That mirrors hoolint, where rules run concurrently and files within a rule run
serially, so only the first file of each rule pays a boot.

Usage: python bench_pool.py [N]      (default 4, matching hoolint's max_workers)
"""
import asyncio
import json
import statistics
import sys
import time
import urllib.request

URL = "http://localhost:11435/v1/chat/completions"
SPANS = [
    "`assert mock.called` in a test.",
    "`# increment the counter by one` above `count += 1`.",
    "`assert response.status_code == 200` in a test.",
    "`# TODO: fix later` above a bare except.",
]


def _post(i: int) -> tuple[float, bool]:
    """Judge one span. Returns (seconds, served_from_a_spare)."""
    body = json.dumps({
        "model": "qwen3:4b", "reasoning_effort": "none",
        "messages": [{"role": "user",
                      "content": f"Judge item {i + 1}: {SPANS[i % len(SPANS)]}"}],
    }).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"content-type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as r:
        payload = json.load(r)
    return time.monotonic() - t0, payload["x_judge_proxy"]["warm"]


async def _round(n: int) -> list[tuple[float, bool]]:
    loop = asyncio.get_running_loop()
    return await asyncio.gather(*(loop.run_in_executor(None, _post, i)
                                  for i in range(n)))


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4

    baseline = (await _round(1))[0][0]
    print(f"N=1 warm baseline:  {baseline:5.1f}s")

    await asyncio.sleep(8)
    cold = await _round(n)
    print(f"round 1 (cold):     {[f'{s:.1f}s' for s, _ in cold]}  "
          f"warm={[w for _, w in cold]}")

    await asyncio.sleep(8)
    hot = await _round(n)
    lat = [s for s, _ in hot]
    warm = [w for _, w in hot]
    median = statistics.median(lat)
    print(f"round 2 (scored):   {[f'{s:.1f}s' for s in lat]}  warm={warm}")
    print(f"\nall warm:           {all(warm)}            (pass: True)")
    print(f"median / baseline:  {median / baseline:.2f}x       (pass: <= 1.50)")


asyncio.run(main())
```

- [ ] **Step 2: Run the probe against a live proxy**

```bash
uptime | sed 's/.*load/load/'          # record this, the numbers move with it
setsid nohup uv run uvicorn app:app --port 11435 > /tmp/bench.log 2>&1 < /dev/null &
until curl -s -m 2 localhost:11435/ >/dev/null 2>&1; do sleep 1; done
uv run python bench_pool.py 4
PAT="uvi""corn app:app"; pkill -INT -f "$PAT"
```

Expected, per the spec's acceptance section:
- every request in round 2 reports `warm=True`
- median round-2 latency is at most 1.5x the N=1 baseline measured in the same session

If either fails, do not adjust the threshold. Record the actual figures and stop: the pool is not doing what the design claims, and that is a finding, not a number to tune.

- [ ] **Step 3: Record the result in the README**

In `tools/judge-proxy/README.md`, replace the paragraph under `## How the warm spare works` that begins "One spare, not a pool" and the paragraph after it (which describes the 2-3s spare boot and the three back-to-back runs) with a description of the pool: the key, the cap, `JUDGE_PROXY_SPARES` and `JUDGE_PROXY_MAX_INFLIGHT` with their defaults, that only the first file of each rule pays a boot, and the measured before and after numbers from Step 2 with the load average.

Add both env vars to the existing env var table:

```markdown
| `JUDGE_PROXY_SPARES` | `4` | warm processes parked, 0 disables prewarming |
| `JUDGE_PROXY_MAX_INFLIGHT` | `8` | processes allowed in flight; excess requests queue |
```

Add one line noting that `pyproject.toml` now diverges from upstream `llm-faker` by two dev dependencies and a pytest section, so the next person diffing the fork knows it was deliberate.

- [ ] **Step 4: Check the prose against this repo's own rules**

```bash
cd ../.. && grep -n "—\|–" tools/judge-proxy/README.md
grep -niE "\b(leverag|utiliz)" tools/judge-proxy/README.md
```

Expected: no output from either. This repo lints itself for em dashes and for those two words in markdown.

- [ ] **Step 5: Commit**

```bash
git add tools/judge-proxy/bench_pool.py tools/judge-proxy/README.md
git commit -m "docs(judge-proxy): measure the warm pool and record the numbers

Scores the second round of concurrent requests, never the first: the pool starts
with one spare, so a first burst is cold by construction and a single-round probe
would read as the pool doing nothing."
```

---

## Verification

After Task 7, the whole change is verified by:

```bash
cd tools/judge-proxy && uv run pytest -v          # 13 passed
cd ../../hoolint/app && uv run pytest -q          # 181 passed, unchanged
```

The hoolint suite must be unchanged. If it moved, something in this plan touched the hoolint package, which Global Constraints forbid.
