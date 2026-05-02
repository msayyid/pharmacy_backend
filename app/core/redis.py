"""Redis client lifecycle.

Phase 1 stub. Phase 3 lands the real ``init_redis``/``close_redis``/``get_redis``
helpers wired to ``settings.redis_dsn`` (used for rate limit counters,
idempotency keys, refresh-token jti store, search-suggest cache, ARQ queue).

Reference: BACKEND_BLUEPRINT.md §18.1.
"""

from __future__ import annotations

# Intentionally empty in Phase 1.
