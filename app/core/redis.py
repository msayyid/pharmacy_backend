"""Redis client lifecycle.

* :func:`init_redis` — connect once at app/worker startup. Stores the client
  in module state.
* :func:`close_redis` — release the connection at shutdown.
* :func:`get_redis` — accessor used by ``cache``, ``ratelimit``, and
  ``idempotency`` modules. Asserts initialised state.

The client uses ``decode_responses=True`` so reads return ``str``. Cache
values are serialised via ``orjson`` (bytes) — ``orjson.loads`` accepts
both ``str`` and ``bytes``, so the round-trip works without manual encoding.

Reference: BACKEND_BLUEPRINT.md §18.1.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings

_redis: Redis | None = None


async def init_redis(settings: Settings) -> Redis:
    """Open and return the Redis client. Idempotent across re-init calls."""
    global _redis  # noqa: PLW0603 — module-level singleton owned by lifespan
    if _redis is not None:
        return _redis
    # Use Redis.from_url (typed classmethod) over the module-level from_url
    # alias which is loosely typed in redis-py stubs.
    _redis = Redis.from_url(
        str(settings.redis_dsn),
        decode_responses=True,
        health_check_interval=30,
    )
    return _redis


async def close_redis() -> None:
    """Release the Redis client. Idempotent."""
    global _redis  # noqa: PLW0603 — module-level singleton owned by lifespan
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> Redis:
    """Return the active Redis client. Must be called after :func:`init_redis`."""
    if _redis is None:
        raise RuntimeError(
            "Redis not initialised — call init_redis() at app startup",
        )
    return _redis
