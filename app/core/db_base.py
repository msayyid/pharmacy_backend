"""SQLAlchemy declarative base + reusable mixins.

Phase 1 scaffolds the ``Base`` and mixins so Phase 2 can land migrations
without import shuffles. No models registered yet — ``Base.metadata`` is
empty until Phase 2 imports them.

Reference: BACKEND_BLUEPRINT.md §7.3.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# NOTE: BACKEND_BLUEPRINT.md §6.6 example used ``DateTime(6)`` for fractional
# seconds, but SQLAlchemy core's ``DateTime`` takes ``timezone: bool`` as its
# first arg, not fsp. The MySQL dialect's ``DATETIME(fsp=6)`` is the correct
# way to get microsecond precision. See DECISION_LOG.


class Base(DeclarativeBase):
    """Project ORM base. All models inherit this."""


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` (``DATETIME(6)``, server-default UTC).

    Uses ``func.utc_timestamp(6)`` rather than ``CURRENT_TIMESTAMP`` so the
    value is independent of the session ``time_zone`` variable.
    """

    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
        onupdate=func.utc_timestamp(6),
    )


class SoftDeleteMixin:
    """Adds nullable ``deleted_at`` for soft-delete semantics (catalog entities)."""

    deleted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
