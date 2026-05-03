"""Delivery — courier-handover record per order (PHARMACY §7.7).

Phase 9 stored ``courier_name`` / ``courier_phone`` inline on
``orders``; this table captures the richer per-handover fields the
inline columns can't carry (assignment / pick-up / drop-off
timestamps, tracking number, actual fee). The inline columns stay as
a denormalised cache so the simple "show courier on the order detail"
read needs no join.

A row is inserted when an order moves to ``out_for_delivery`` and is
the unique handover record for that order (``UNIQUE(order_id)``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_base import Base
from app.core.types import GUID


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("orders.id", name="fk_deliveries_order", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str | None] = mapped_column(String(40))
    courier_name: Mapped[str | None] = mapped_column(String(160))
    courier_phone: Mapped[str | None] = mapped_column(String(20))
    tracking_number: Mapped[str | None] = mapped_column(String(80))
    estimated_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    assigned_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    picked_up_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    delivered_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    delivery_fee_actual: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)
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

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_deliveries_order"),
        Index("idx_deliveries_provider_assigned", "provider", "assigned_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )
