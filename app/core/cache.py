"""Read-through cache helpers.

* :func:`cache_get_or_set` — return cached JSON value, or call ``loader``
  on miss and cache the result for ``ttl`` seconds.
* :func:`invalidate` — delete every key matching a prefix via ``SCAN`` +
  pipelined ``DEL``. Returns the count.

Values are serialised with ``orjson`` for speed and stable handling of
``datetime``, ``UUID``, etc.

Reference: BACKEND_BLUEPRINT.md §18.3.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

import orjson

from app.core.redis import get_redis

T = TypeVar("T")


async def cache_get_or_set(
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[T]],
) -> T:
    """Return ``key`` from cache or compute it via ``loader`` and cache for ``ttl``."""
    r = get_redis()
    raw = await r.get(key)
    if raw is not None:
        return cast(T, orjson.loads(raw))
    value = await loader()
    await r.set(key, orjson.dumps(value), ex=ttl_seconds)
    return value


_INVALIDATE_BATCH_SIZE = 500


async def invalidate(prefix: str) -> int:
    """Delete every key matching ``<prefix>*``. Returns the count.

    Uses ``SCAN`` so it's safe on large keyspaces (no ``KEYS *`` pitfalls).
    Batches ``DEL`` in groups of :data:`_INVALIDATE_BATCH_SIZE` for throughput.

    Best-effort: if Redis is not initialised (e.g. unit tests that don't
    spin up a Redis client), silently no-ops. The cache is a performance
    optimisation; failure to invalidate must not break a write path. The
    short TTLs (≤ 1h) self-heal any drift.
    """
    try:
        r = get_redis()
    except RuntimeError:
        return 0
    pattern = f"{prefix}*"
    deleted = 0
    batch: list[str] = []
    async for k in r.scan_iter(match=pattern, count=_INVALIDATE_BATCH_SIZE):
        batch.append(k)
        if len(batch) >= _INVALIDATE_BATCH_SIZE:
            deleted += await r.delete(*batch)
            batch = []
    if batch:
        deleted += await r.delete(*batch)
    return deleted


async def get_raw(key: str) -> str | None:
    """Low-level GET — used by :mod:`app.core.idempotency` for opaque storage."""
    r = get_redis()
    val = await r.get(key)
    # decode_responses=True on the client → strings, but redis-py's type stubs
    # are loose (`Any`). Cast to keep mypy strict happy.
    return cast(str | None, val)


async def set_raw(key: str, value: str, ttl_seconds: int) -> None:
    """Low-level SET — used by :mod:`app.core.idempotency`."""
    r = get_redis()
    await r.set(key, value, ex=ttl_seconds)
