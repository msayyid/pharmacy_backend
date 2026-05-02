"""Read-through cache helpers — miss/hit + invalidate."""

from __future__ import annotations

import pytest

from app.core.cache import cache_get_or_set, invalidate

pytestmark = pytest.mark.integration


async def test_cache_get_or_set_calls_loader_on_miss(redis_clean: None) -> None:
    calls: list[int] = []

    async def loader() -> dict[str, int]:
        calls.append(1)
        return {"value": 42}

    v1 = await cache_get_or_set("v1:test:cache:1", 60, loader)
    v2 = await cache_get_or_set("v1:test:cache:1", 60, loader)
    assert v1 == v2 == {"value": 42}
    assert len(calls) == 1, f"loader should be called exactly once on a miss, was {len(calls)}"


async def test_cache_serialises_unicode(redis_clean: None) -> None:
    """Cyrillic survives orjson + Redis round-trip."""

    async def loader() -> dict[str, str]:
        return {"name": "Парацетамол 500мг"}  # noqa: RUF001

    v = await cache_get_or_set("v1:test:cache:cyrillic", 60, loader)
    cached = await cache_get_or_set("v1:test:cache:cyrillic", 60, loader)
    assert cached == v == {"name": "Парацетамол 500мг"}  # noqa: RUF001


async def test_invalidate_removes_matching_keys(redis_clean: None) -> None:
    """invalidate(prefix) deletes every key starting with the prefix."""

    async def loader_a() -> int:
        return 1

    async def loader_b() -> int:
        return 2

    await cache_get_or_set("v1:test:cat:a", 60, loader_a)
    await cache_get_or_set("v1:test:cat:b", 60, loader_b)
    await cache_get_or_set("v1:test:other:x", 60, loader_a)

    deleted = await invalidate("v1:test:cat:")
    assert deleted == 2

    # Other prefix unaffected
    other_calls: list[int] = []

    async def other_loader() -> int:
        other_calls.append(1)
        return 99

    v = await cache_get_or_set("v1:test:other:x", 60, other_loader)
    assert v == 1  # was 1 before invalidate; loader NOT called
    assert other_calls == []


async def test_invalidate_returns_zero_when_nothing_matches(redis_clean: None) -> None:
    deleted = await invalidate("v1:nothing-here:")
    assert deleted == 0
