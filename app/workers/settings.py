"""ARQ worker settings — Phase 11 wires every job + cron schedule.

Run: ``arq app.workers.settings.WorkerSettings`` (or ``make worker``).

**Cron timezone discipline (DECISION_LOG)**: ARQ cron uses UTC.
Asia/Bishkek is UTC+6, no DST. Every cron line below carries an inline
KG-time comment so future-you doesn't re-derive the offset. Getting
one off by 6 hours silently breaks ops.

Reference: BACKEND_BLUEPRINT.md §17.2; PHARMACY §18; PRODUCT §10.6.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.workers import images, imports, scheduled, sms

log = get_logger(__name__)


# Every-5-minutes minute set, used by both cron jobs that share the
# 5-minute cadence (offset by 2 min so they don't both contend for the
# DB at the same instant).
_EVERY_5_MIN = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
_EVERY_5_MIN_OFFSET_2 = {2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57}


async def _on_startup(ctx: dict[str, Any]) -> None:
    """ARQ startup hook — configure logging once per worker process."""
    s = get_settings()
    configure_logging(s)
    log.info("worker_startup", env=s.env, redis=str(s.redis_dsn))


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker_shutdown")


class WorkerSettings:
    """ARQ entrypoint. Read by ``arq`` CLI off the class, not an instance.

    All attributes are ``ClassVar`` for that reason.
    """

    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(str(get_settings().redis_dsn))

    functions: ClassVar[list[Any]] = [
        sms.send_sms,
        images.process_image_upload,
        imports.process_product_import,
    ]

    cron_jobs: ClassVar[list[Any]] = [
        # 06:00 KG = 00:00 UTC — daily near-expiry report.
        cron(scheduled.near_expiry_report, hour=0, minute=0),
        # 06:10 KG = 00:10 UTC — daily low-stock report.
        cron(scheduled.low_stock_report, hour=0, minute=10),
        # 02:00 KG = 20:00 UTC (previous day) — daily expire-batches sweep.
        cron(scheduled.expire_batches, hour=20, minute=0),
        # 03:00 KG = 21:00 UTC (previous day) — daily reconcile_stock_cache.
        cron(scheduled.reconcile_stock_cache, hour=21, minute=0),
        # 04:00 KG = 22:00 UTC (previous day) — daily cleanup_otps.
        cron(scheduled.cleanup_otps, hour=22, minute=0),
        # 04:10 KG = 22:10 UTC (previous day) — daily cleanup_carts.
        cron(scheduled.cleanup_carts, hour=22, minute=10),
        # Every 5 minutes — release stale pending orders. Single cron
        # handles both the 30-min card threshold and the 24-h default
        # threshold (resolves OPEN_QUESTIONS Q11).
        cron(scheduled.release_pending_orders, minute=_EVERY_5_MIN),
        # Every 5 minutes, offset 2 — payment reconcile.
        cron(scheduled.payment_reconcile, minute=_EVERY_5_MIN_OFFSET_2),
    ]

    max_jobs: ClassVar[int] = 10
    job_timeout: ClassVar[int] = 300  # 5 min default
    keep_result: ClassVar[int] = 3600  # 1 h
    max_tries: ClassVar[int] = 5

    on_startup = _on_startup
    on_shutdown = _on_shutdown


# ─── KG → UTC cron mappings (used by Phase 11.6 audit test) ──────────────────
#
# A flat dict mirroring the schedule above. The audit test reads this
# and asserts every cron in :class:`WorkerSettings.cron_jobs` matches.
# Updating one without the other will fail the test loudly.

KG_TO_UTC_HOUR_MAPPING: dict[str, tuple[int, int | set[int]]] = {
    "near_expiry_report": (0, 0),
    "low_stock_report": (0, 10),
    "expire_batches": (20, 0),
    "reconcile_stock_cache": (21, 0),
    "cleanup_otps": (22, 0),
    "cleanup_carts": (22, 10),
    "release_pending_orders": (0, _EVERY_5_MIN),  # hour=0 means "every hour"
    "payment_reconcile": (0, _EVERY_5_MIN_OFFSET_2),
}
