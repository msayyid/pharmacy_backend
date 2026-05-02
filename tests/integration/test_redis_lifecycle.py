"""Redis client lifecycle — init, idempotent re-init, get, close.

This test self-manages the module-level Redis state (does NOT use the
``redis_clean`` fixture) so it can exercise the init/close transitions
explicitly.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.core.redis import close_redis, get_redis, init_redis

pytestmark = pytest.mark.integration


async def test_full_lifecycle() -> None:
    """init → use → close → re-init → close again."""
    settings = get_settings()

    # Defensive: ensure clean slate.
    await close_redis()
    with pytest.raises(RuntimeError):
        get_redis()

    # Init
    r1 = await init_redis(settings)
    assert r1 is not None
    assert get_redis() is r1

    # Round-trip
    await r1.set("v1:test:lifecycle", "alive")
    assert await r1.get("v1:test:lifecycle") == "alive"

    # Init is idempotent — same client returned
    r2 = await init_redis(settings)
    assert r2 is r1

    # Close releases
    await close_redis()
    with pytest.raises(RuntimeError):
        get_redis()

    # Close is idempotent
    await close_redis()


async def test_get_redis_before_init_raises() -> None:
    """Calling get_redis without init must raise RuntimeError."""
    await close_redis()  # defensive: ensure no stale state
    with pytest.raises(RuntimeError):
        get_redis()
