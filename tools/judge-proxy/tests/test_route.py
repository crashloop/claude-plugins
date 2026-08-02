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
import openai_route
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


@pytest.mark.asyncio
async def test_shutdown_waits_for_a_prewarm_still_in_flight(pool):
    """A warm task landing after the drain parks a live CLI that outlives the
    server. Shutdown must await the prewarms it started, not just empty the pool.
    """
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        await client.post("/v1/chat/completions", json=BODY)
        await openai_route._shutdown()      # the replacement is still booting

    await _settle()
    assert pool == [], "a prewarm re-parked a live process after shutdown"
    assert all(j.killed for j in FakeJudge.made)


@pytest.mark.asyncio
async def test_requests_over_the_inflight_cap_do_not_overlap(pool, monkeypatch):
    """Pins that the serving path actually sits inside the semaphore. Asserting
    the semaphore's initial value alone passes with the `async with` deleted.
    """
    monkeypatch.setattr(openai_route, "_inflight", asyncio.Semaphore(1))
    live = peak = 0

    async def slow_ask(self, prompt: str) -> str:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return "[0] OK: fake verdict"

    monkeypatch.setattr(FakeJudge, "ask", slow_ask)
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        await asyncio.gather(*(client.post("/v1/chat/completions", json=BODY)
                               for _ in range(3)))

    assert peak == 1, f"{peak} requests judged at once against a cap of 1"
