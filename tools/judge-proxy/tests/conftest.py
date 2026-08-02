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
