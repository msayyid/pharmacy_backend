"""Inventory domain — Branch, Supplier, BranchProduct, InventoryBatch, StockMovement.

Phase 4 lands ``Branch`` (admin auth needs it). Phase 6 lands the rest:

* :class:`Supplier` — distributor reference data.
* :class:`BranchProduct` — per-branch availability, price, and the
  **cached** ``total_quantity`` / ``reserved_quantity`` aggregates.
* :class:`InventoryBatch` — the source-of-truth for stock; FEFO uses
  ``ORDER BY expiry_date, received_at`` + ``FOR UPDATE SKIP LOCKED``.
* :class:`StockMovement` — append-only audit log paired with every
  batch quantity change in the same transaction.

Reference: PHARMACY_BLUEPRINT_2.md §6; BACKEND_BLUEPRINT.md §11; PRODUCT
§10 (stock truth + FEFO + 7-day hard block).
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, TimestampMixin
from app.core.types import GUID

if TYPE_CHECKING:  # pragma: no cover
    from app.domain.identity.models import AdminUser


# ─── Enums ────────────────────────────────────────────────────────────────────


class MovementType(StrEnum):
    """Stock movement types per PHARMACY §6.5.

    Sign rules (enforced by ``chk_movement_sign``):

    * ``received``, ``released``, ``transferred_in`` → quantity_change >= 0
    * ``sold``, ``reserved``, ``expired``, ``damaged``, ``transferred_out``
      → quantity_change <= 0
    * ``adjusted`` → either sign (manual correction)
    """

    RECEIVED = "received"
    SOLD = "sold"
    RESERVED = "reserved"
    RELEASED = "released"
    EXPIRED = "expired"
    DAMAGED = "damaged"
    ADJUSTED = "adjusted"
    TRANSFERRED_IN = "transferred_in"
    TRANSFERRED_OUT = "transferred_out"


# ─── Branch ───────────────────────────────────────────────────────────────────


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


# ─── Supplier ─────────────────────────────────────────────────────────────────


class Supplier(Base, TimestampMixin):
    """A distributor / pharmaceutical supplier.

    Optional FK target on :class:`InventoryBatch` (``ON DELETE SET NULL``)
    so deleting a supplier does not orphan historical batches.
    """

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("idx_suppliers_active", "is_active"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── Branch product (per-branch availability + cached stock) ─────────────────


class BranchProduct(Base):
    """Per-branch availability, pricing, and the cached stock aggregates.

    PK is the composite ``(branch_id, product_id)``. ``total_quantity``
    and ``reserved_quantity`` are denormalised: every change to an
    :class:`InventoryBatch.quantity_remaining` updates the matching
    ``branch_products`` row inside the same transaction. The nightly
    ``reconcile_stock_cache`` job (Phase 11) is a safety net.

    ``is_available=False`` hides the product from the storefront entirely
    even if stock is positive (e.g. priced at 0 / pending pricing).
    """

    __tablename__ = "branch_products"

    branch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("branches.id", name="fk_branch_products_branch", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_branch_products_product", ondelete="CASCADE"),
        primary_key=True,
    )

    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KGS")

    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
        onupdate=func.utc_timestamp(6),
    )

    __table_args__ = (
        CheckConstraint("price >= 0", name="chk_bp_price_nonneg"),
        CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= price",
            name="chk_bp_compare_ge_price",
        ),
        CheckConstraint("total_quantity >= 0", name="chk_bp_total_nonneg"),
        CheckConstraint("reserved_quantity >= 0", name="chk_bp_reserved_nonneg"),
        CheckConstraint("reserved_quantity <= total_quantity", name="chk_bp_reserved_le_total"),
        CheckConstraint("low_stock_threshold >= 0", name="chk_bp_threshold_nonneg"),
        Index("idx_bp_low_stock", "branch_id", "total_quantity"),
        Index("idx_bp_branch_available", "branch_id", "is_available"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── Inventory batch (source of truth) ────────────────────────────────────────


class InventoryBatch(Base, TimestampMixin):
    """A single batch of stock at a single branch.

    Identified by ``(branch_id, product_id, batch_number)`` — repeating
    a batch_number across products or branches is allowed; repeating it
    within a ``(branch, product)`` pair is rejected (admin should use
    ``adjust`` instead of receiving the same batch twice).

    FKs use ``ON DELETE RESTRICT`` so historical audit chains cannot be
    broken by deleting a branch / product / supplier.
    """

    __tablename__ = "inventory_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("branches.id", name="fk_ib_branch", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_ib_product", ondelete="RESTRICT"),
        nullable=False,
    )
    supplier_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("suppliers.id", name="fk_ib_supplier", ondelete="SET NULL"),
    )

    batch_number: Mapped[str] = mapped_column(String(60), nullable=False)
    expiry_date: Mapped[date] = mapped_column(nullable=False)
    manufacture_date: Mapped[date | None] = mapped_column()

    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    # Held by pending/confirmed/preparing orders. ``quantity_remaining``
    # is the full physical count; ``quantity_remaining - quantity_reserved``
    # is what FEFO can allocate to a new order. Per-batch tracking is
    # what prevents oversell-per-batch under concurrent reservers.
    # See DECISION_LOG 2026-05-02 for the deviation from PHARMACY §11.4.
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KGS")

    received_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        UniqueConstraint("branch_id", "product_id", "batch_number", name="uq_inventory_batch"),
        CheckConstraint("quantity_received > 0", name="chk_ib_received_pos"),
        CheckConstraint("quantity_remaining >= 0", name="chk_ib_remaining_nonneg"),
        CheckConstraint(
            "quantity_remaining <= quantity_received", name="chk_ib_remaining_le_received"
        ),
        CheckConstraint("quantity_reserved >= 0", name="chk_ib_reserved_nonneg"),
        CheckConstraint(
            "quantity_reserved <= quantity_remaining", name="chk_ib_reserved_le_remaining"
        ),
        CheckConstraint("cost_price >= 0", name="chk_ib_cost_nonneg"),
        # FEFO scan: WHERE branch_id=? AND product_id=? AND quantity_remaining>0
        #            AND expiry_date > today + 7 days
        #            ORDER BY expiry_date ASC, received_at ASC
        Index(
            "idx_ib_fefo",
            "branch_id",
            "product_id",
            "expiry_date",
            "received_at",
        ),
        # Near-expiry / expired reports.
        Index("idx_ib_expiry", "branch_id", "expiry_date"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── Stock movement (append-only audit) ───────────────────────────────────────


class StockMovement(Base):
    """Immutable audit log of every stock change.

    ``order_id`` carries an FK to ``orders.id`` (added by Phase 8's
    migration; was column-only at Phase 6).
    """

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inventory_batch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("inventory_batches.id", name="fk_sm_batch", ondelete="RESTRICT"),
        nullable=False,
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("branches.id", name="fk_sm_branch", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_sm_product", ondelete="RESTRICT"),
        nullable=False,
    )
    movement_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)

    # FK added in Phase 8 once ``orders`` exists. Keep column nullable so
    # admin-driven movements (received, damaged, adjusted) leave it NULL.
    order_id: Mapped[UUID | None] = mapped_column(
        GUID,
        ForeignKey("orders.id", name="fk_sm_order", ondelete="SET NULL"),
    )
    admin_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", name="fk_sm_admin", ondelete="SET NULL"),
    )
    reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    admin_user: Mapped[AdminUser | None] = relationship(lazy="raise")

    __table_args__ = (
        # ``chk_movement_sign`` is emitted via ``op.execute`` in the migration —
        # SQLAlchemy renders it fine here too, but keeping the constraint
        # logic in one place avoids duplication / drift.
        Index("idx_sm_branch_created", "branch_id", "created_at"),
        Index("idx_sm_product_created", "product_id", "created_at"),
        Index("idx_sm_order", "order_id"),
        Index("idx_sm_batch", "inventory_batch_id"),
        Index("idx_sm_type", "movement_type"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )
