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
