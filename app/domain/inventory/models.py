"""Inventory domain — Branch, BranchProduct, InventoryBatch, StockMovement.

Phase 4 lands the ``Branch`` table because ``admin_users.branch_id`` references
it. Phase 6 lands the rest of the inventory schema (``BranchProduct``,
``InventoryBatch``, ``StockMovement``) and the FEFO query infrastructure.

Reference: PHARMACY_BLUEPRINT_2.md §6; BACKEND_BLUEPRINT.md §8.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Index, Numeric, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_base import Base, TimestampMixin


class Branch(Base, TimestampMixin):
    """A physical pharmacy location.

    Stock, prices, and orders are all scoped by ``branch_id`` even at MVP
    (single-branch UX) — the data model is multi-branch from day one to
    avoid a brutal migration when Osh launches.
    """

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="Bishkek")
    phone: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(40), nullable=False, default="Asia/Bishkek")
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("code", name="uq_branches_code"),
        Index("idx_branches_active", "is_active"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )
