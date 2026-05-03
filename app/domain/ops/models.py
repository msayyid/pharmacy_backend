"""Operations domain — admin audit log, SMS log, search log.

* Phase 5 — :class:`AdminAuditLog`.
* Phase 7 — :class:`SearchLog` (storefront search analytics).
* Phase 10 — :class:`SmsLog` (lands alongside the SMS adapters).

Reference: PHARMACY_BLUEPRINT_2.md §8.1, §8.2, §8.3; PRODUCT_BLUEPRINT.md
§8.7, §12.3, §14.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_base import Base
from app.core.types import GUID


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


class SearchLog(Base):
    """One row per storefront search submission.

    Surfaces "what people search for and find nothing" — the catalog-gap
    + synonym-miss signal (PRODUCT §12.3). Authenticated user FK is
    nullable; guest searches are recorded too. ``clicked_product_id`` is
    settable from a follow-up endpoint (Phase 7 ships the table; the
    click-recording endpoint is Phase 9 admin analytics).
    """

    __tablename__ = "search_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String(255), nullable=False)
    language_code: Mapped[str | None] = mapped_column(String(8))
    user_id: Mapped[UUID | None] = mapped_column(
        GUID,
        ForeignKey("users.id", name="fk_search_log_user", ondelete="SET NULL"),
    )
    results_count: Mapped[int] = mapped_column(Integer, nullable=False)
    clicked_product_id: Mapped[UUID | None] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_search_log_product", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        # Recent activity, ordered by time.
        Index("idx_sl_created", "created_at"),
        # "What did the customer just type?" — query lookup for popular
        # searches and zero-result analytics.
        Index("idx_sl_query", "query"),
        # MySQL has no partial indexes; this composite serves the
        # zero-result report (filter by ``results_count = 0`` in the
        # query, then ORDER BY created_at DESC).
        Index("idx_sl_results_created", "results_count", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


class SmsLog(Base):
    """One row per SMS attempt (PHARMACY §8.2).

    Written when an SMS is enqueued (``status='queued'``); flipped to
    ``sent`` / ``failed`` by the worker after the provider responds.
    Holds the rendered body verbatim so support can answer "what
    exactly did the customer receive?" — phone is stored E.164; the
    structlog redactor masks it on log emission, not at rest.
    """

    __tablename__ = "sms_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        Index("idx_sms_phone_created", "phone", "created_at"),
        Index("idx_sms_status_created", "status", "created_at"),
        Index("idx_sms_purpose_created", "purpose", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )
