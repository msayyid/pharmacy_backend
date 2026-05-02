"""Time helpers.

Internal storage is **always UTC**. Presentation converts to Asia/Bishkek.

Bishkek is UTC+6 with **no DST**. ARQ cron jobs are scheduled in **UTC**:

* ``06:00 KG = 00:00 UTC``  (near-expiry / low-stock daily reports)
* ``02:00 KG = 20:00 UTC``  (previous-day; expire_batches)
* ``03:00 KG = 21:00 UTC``  (previous-day; reconcile_stock_cache)

When declaring a new cron, comment the KG-equivalent next to the UTC time.

Reference: CLAUDE.md "Localization"; BACKEND_BLUEPRINT.md §17.2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

BISHKEK_TZ: ZoneInfo = ZoneInfo("Asia/Bishkek")


def utcnow() -> datetime:
    """Current UTC time as an aware ``datetime``."""
    return datetime.now(UTC)


def bishkek_now() -> datetime:
    """Current Bishkek-local time as an aware ``datetime``. Display only."""
    return datetime.now(BISHKEK_TZ)


def to_bishkek(dt: datetime) -> datetime:
    """Convert a (UTC or naive-assumed-UTC) datetime to Bishkek-local."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(BISHKEK_TZ)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as a tz-aware UTC datetime.

    MySQL's ``DATETIME(fsp=6)`` stores tz-naive timestamps (we always write
    UTC). When SQLAlchemy reads them back, the result is naive. Comparing
    a naive datetime to ``utcnow()`` (aware) raises ``TypeError``; this
    helper closes that gap by attaching UTC tzinfo when missing.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
