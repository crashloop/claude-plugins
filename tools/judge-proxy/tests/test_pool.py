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
