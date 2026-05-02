"""ARQ worker settings.

Phase 1 stub. Phase 11 populates ``functions`` and ``cron_jobs`` per
BACKEND_BLUEPRINT.md §17.2 — SMS, image-processing, imports, scheduled jobs
(near-expiry, low-stock, expire_batches, reconcile_stock_cache, etc.).

Reference: BACKEND_BLUEPRINT.md §17.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings


class WorkerSettings:
    """ARQ entrypoint. Run with ``arq app.workers.settings.WorkerSettings``.

    All attributes are class-level (``ClassVar``) — ARQ reads them off the
    class, not an instance.
    """

    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(str(get_settings().redis_dsn))
    functions: ClassVar[list[Any]] = []
    cron_jobs: ClassVar[list[Any]] = []
    max_jobs: ClassVar[int] = 10
    job_timeout: ClassVar[int] = 300
    keep_result: ClassVar[int] = 3600
    max_tries: ClassVar[int] = 5
