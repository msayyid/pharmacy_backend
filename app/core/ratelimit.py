"""Fixed-window rate limiter via Redis ``INCR`` + ``EXPIRE NX``.

Pattern: ``INCR key`` (atomic counter) followed by ``EXPIRE key TTL NX`` (only
set TTL when none exists, i.e. on first hit). The counter expires after
``window_seconds`` of inactivity from the start of the window.

Worked example — "3 OTP requests per phone per 15 minutes":

>>> await hit(key="v1:rl:otp:phone:+996700123456", limit=3, window_seconds=900)
>>> # ... three calls succeed, fourth raises RateLimitExceededError.
>>> # After 900s the counter is gone; the next hit starts fresh.

This is fixed-window, NOT sliding. Two windows can "stack" near a boundary
(briefly twice the configured rate). Acceptable at MVP scale per
PRODUCT_BLUEPRINT §16 and BACKEND_BLUEPRINT §18.5; promote to a sorted-set
sliding window in Phase 12 if measured need.

Reference: BACKEND_BLUEPRINT.md §18.5; PRODUCT_BLUEPRINT.md §16.
"""

from __future__ import annotations

from app.core.errors import RateLimitExceededError
from app.core.redis import get_redis


async def hit(*, key: str, limit: int, window_seconds: int) -> int:
    """Register a hit and raise if the counter would exceed ``limit``.

    Returns the post-hit counter value (useful for emitting "X requests
    remaining" headers if a future endpoint wants them).
    """
    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds, nx=True)
    results = await pipe.execute()
    count = int(results[0])
    if count > limit:
        raise RateLimitExceededError(
            key=key,
            limit=limit,
            window_seconds=window_seconds,
            count=count,
        )
    return count


async def reset(key: str) -> None:
    """Drop a rate-limit counter outright. Useful for tests and admin tools."""
    r = get_redis()
    await r.delete(key)
