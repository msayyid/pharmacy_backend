"""Rate limiter — fixed-window via INCR + EXPIRE NX."""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import RateLimitExceededError
from app.core.ratelimit import hit, reset

pytestmark = pytest.mark.integration


async def test_hits_within_limit_allowed(redis_clean: None) -> None:
    key = "v1:test:rl:within"
    for i in range(1, 4):
        c = await hit(key=key, limit=3, window_seconds=60)
        assert c == i


async def test_over_limit_raises(redis_clean: None) -> None:
    key = "v1:test:rl:over"
    for _ in range(3):
        await hit(key=key, limit=3, window_seconds=60)
    with pytest.raises(RateLimitExceededError) as excinfo:
        await hit(key=key, limit=3, window_seconds=60)
    assert excinfo.value.context["count"] == 4
    assert excinfo.value.context["limit"] == 3


async def test_window_resets_after_expiry(redis_clean: None) -> None:
    """Use a 1-second window; burn the budget; wait > 1s; budget restored."""
    key = "v1:test:rl:expires"
    for _ in range(2):
        await hit(key=key, limit=2, window_seconds=1)
    with pytest.raises(RateLimitExceededError):
        await hit(key=key, limit=2, window_seconds=1)

    await asyncio.sleep(1.2)

    # Window has expired; counter is gone; next hit succeeds
    c = await hit(key=key, limit=2, window_seconds=1)
    assert c == 1


async def test_reset_clears_counter(redis_clean: None) -> None:
    key = "v1:test:rl:reset"
    for _ in range(3):
        await hit(key=key, limit=3, window_seconds=60)
    await reset(key)
    c = await hit(key=key, limit=3, window_seconds=60)
    assert c == 1


async def test_separate_keys_have_independent_counters(redis_clean: None) -> None:
    """Two different keys do not interfere with each other."""
    for _ in range(3):
        await hit(key="v1:test:rl:phoneA", limit=3, window_seconds=60)
    # phoneB is fresh
    c = await hit(key="v1:test:rl:phoneB", limit=3, window_seconds=60)
    assert c == 1
