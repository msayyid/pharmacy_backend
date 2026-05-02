"""Operations domain — admin audit log, SMS log, search log.

Phase 5 lands :class:`AdminAuditLog` only. ``sms_log`` and ``search_log``
arrive in Phase 10/11 (operational logs are written by integrations and
the search service that don't exist yet).

The audit log records every admin mutation: who did what, on which entity,
with before/after JSON. Phase 9 adds the read-side viewer endpoint
(``F-ADM-AUD-001``).

Reference: PHARMACY_BLUEPRINT_2.md §8.1; PRODUCT_BLUEPRINT.md §8.7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_base import Base


class AdminAuditLog(Base):
    """Append-only record of admin mutations.

    Grows fast — partitioned by ``created_at`` (monthly) once it crosses
    ~10M rows (PHARMACY §8.1 note). For MVP, plain table.
    """

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", name="fk_audit_admin", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(60))
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        Index("idx_audit_admin_created", "admin_user_id", "created_at"),
        Index("idx_audit_entity", "entity_type", "entity_id", "created_at"),
        Index("idx_audit_created", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )
