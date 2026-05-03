"""Orders domain — Cart, CartItem, Order, OrderItem, OrderStatusHistory.

* :class:`Cart` + :class:`CartItem` — guest-or-user shopping cart;
  ``user_id`` OR ``session_id`` required (CHECK ``chk_carts_owner``);
  30-day expiry; ``UNIQUE(cart_id, product_id)`` prevents duplicate
  lines.
* :class:`Order` — the durable order record with frozen totals and
  snapshotted contact + delivery details. ``order_number`` is the
  human-friendly identifier.
* :class:`OrderItem` — one row **per allocation** (a cart line that
  spans 2 batches yields 2 ``order_items``). Snapshots are immutable
  post-insert.
* :class:`OrderStatusHistory` — append-only audit of state transitions.
* :class:`OrderSequence` — atomic per-year ``order_number`` counter.

Reference: PHARMACY_BLUEPRINT_2.md §7; PRODUCT_BLUEPRINT.md §9 (order
state machine), §11 (pricing), §17.1-17.2 (edge cases).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, TimestampMixin
from app.core.types import GUID

# ─── Enums ────────────────────────────────────────────────────────────────────


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY_FOR_PICKUP = "ready_for_pickup"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentMethod(StrEnum):
    CASH_ON_DELIVERY = "cash_on_delivery"
    CARD_ONLINE = "card_online"
    MBANK = "mbank"
    ELSOM = "elsom"
    ODENGI = "odengi"
    BALANCE_KG = "balance_kg"
    BANK_TRANSFER = "bank_transfer"


class DeliveryMethod(StrEnum):
    DELIVERY = "delivery"
    PICKUP = "pickup"


# ─── Cart ─────────────────────────────────────────────────────────────────────


class Cart(Base):
    """Guest-or-user shopping cart.

    Either ``user_id`` (logged-in customer) OR ``session_id`` (guest
    cookie) must be set — enforced by ``chk_carts_owner``. ``expires_at``
    defaults to 30 days from creation; reads beyond that raise
    ``CartExpiredError`` and the row is cleaned up by a worker (Phase
    11) or eagerly on access.
    """

    __tablename__ = "carts"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(
        GUID,
        ForeignKey("users.id", name="fk_carts_user", ondelete="CASCADE"),
    )
    session_id: Mapped[str | None] = mapped_column(String(64))
    branch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("branches.id", name="fk_carts_branch", ondelete="RESTRICT"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KGS")

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
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)

    items: Mapped[list[CartItem]] = relationship(
        "CartItem",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        # ``chk_carts_owner`` is emitted via op.execute in the migration
        # so the disjunction reads cleanly. Keeping the column-bound
        # CheckConstraint here lets ORM-level autoflush surface the same
        # rule pre-DDL (insert paths exercise it via DB).
        CheckConstraint(
            "user_id IS NOT NULL OR session_id IS NOT NULL",
            name="chk_carts_owner",
        ),
        Index("idx_carts_user", "user_id"),
        Index("idx_carts_session", "session_id"),
        Index("idx_carts_expires", "expires_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cart_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("carts.id", name="fk_cart_items_cart", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_cart_items_product", ondelete="CASCADE"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
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
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items"),
        CheckConstraint("quantity > 0", name="chk_cart_items_qty_pos"),
        CheckConstraint("price_snapshot >= 0", name="chk_cart_items_price_nonneg"),
        Index("idx_cart_items_cart", "cart_id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── Orders ───────────────────────────────────────────────────────────────────


class Order(Base, TimestampMixin):
    """Durable order record.

    Notes per PHARMACY §7.3:
    * ``order_number`` is human-readable (``PH-YYYY-NNNNNN``); ``id`` is
      the internal UUID.
    * ``delivery_address`` is a JSON snapshot of the user_address at
      placement time — addresses change in ``user_addresses`` and we
      do not follow the FK when rendering the order.
    * Money is in ``Numeric(12, 2)``. ``chk_orders_total`` enforces
      ``total = subtotal + delivery_fee - discount_amount``.
    """

    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    order_number: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        GUID,
        ForeignKey("users.id", name="fk_orders_user", ondelete="SET NULL"),
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("branches.id", name="fk_orders_branch", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    delivery_method: Mapped[str] = mapped_column(String(20), nullable=False)

    recipient_name: Mapped[str] = mapped_column(String(160), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    delivery_address: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    delivery_latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    delivery_longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KGS")

    customer_notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    # Courier hand-off (Phase 9). Phase 10 moves these to a dedicated
    # ``deliveries`` table per PHARMACY §7.7; for MVP they live inline.
    courier_name: Mapped[str | None] = mapped_column(String(160))
    courier_phone: Mapped[str | None] = mapped_column(String(20))

    placed_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    delivered_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))

    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    history: Mapped[list[OrderStatusHistory]] = relationship(
        "OrderStatusHistory",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("order_number", name="uq_orders_order_number"),
        CheckConstraint("subtotal >= 0", name="chk_orders_subtotal_nonneg"),
        CheckConstraint("delivery_fee >= 0", name="chk_orders_delivery_nonneg"),
        CheckConstraint("discount_amount >= 0", name="chk_orders_discount_nonneg"),
        CheckConstraint("total >= 0", name="chk_orders_total_nonneg"),
        # ``total = subtotal + delivery_fee - discount_amount`` —
        # rendered via op.execute in the migration to keep the long
        # arithmetic expression readable.
        Index("idx_orders_user_created", "user_id", "created_at"),
        Index("idx_orders_branch_status", "branch_id", "status"),
        Index("idx_orders_placed", "placed_at"),
        Index("idx_orders_status_payment", "status", "payment_status"),
        # Phase 12 — admin queue + support lookup by phone (PRODUCT §18.2).
        Index("idx_orders_recipient_phone", "recipient_phone"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


class OrderItem(Base):
    """One row **per allocation** (DECISION_LOG'd).

    A cart line that spans 2 batches yields 2 ``order_items`` — each
    snapshots its source batch number + expiry for traceability
    (PRODUCT §10.7 recall handling).
    """

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("orders.id", name="fk_order_items_order", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID | None] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_order_items_product", ondelete="SET NULL"),
    )
    inventory_batch_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "inventory_batches.id",
            name="fk_order_items_batch",
            ondelete="SET NULL",
        ),
    )

    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    product_sku_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_number_snapshot: Mapped[str | None] = mapped_column(String(60))
    expiry_date_snapshot: Mapped[Any | None] = mapped_column(Date, nullable=True)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_order_items_qty_pos"),
        CheckConstraint("unit_price >= 0", name="chk_order_items_unit_nonneg"),
        CheckConstraint("line_total >= 0", name="chk_order_items_line_nonneg"),
        # ``line_total = unit_price * quantity`` — emitted via op.execute.
        Index("idx_order_items_order", "order_id"),
        Index("idx_order_items_product", "product_id"),
        Index("idx_order_items_batch", "inventory_batch_id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("orders.id", name="fk_osh_order", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", name="fk_osh_admin", ondelete="SET NULL"),
    )
    changed_by_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        Index("idx_osh_order", "order_id", "created_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── Per-year order-number sequence ──────────────────────────────────────────


class OrderSequence(Base):
    """Per-year ``order_number`` counter.

    Service flow: ``SELECT … WHERE year = ? FOR UPDATE`` (lock the
    row), increment ``last_value``, format
    ``PH-{year}-{last_value:06d}``. Atomic inside the place-order
    transaction.

    DECISION_LOG: chosen over per-year auto-increment table to avoid
    schema churn at year boundary.
    """

    __tablename__ = "order_sequences"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_assigned: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
        onupdate=func.utc_timestamp(6),
    )

    __table_args__ = (
        CheckConstraint("last_assigned >= 0", name="chk_order_seq_nonneg"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── Payments (Phase 9 stub — Phase 10 wires the real gateway) ──────────────


class Payment(Base):
    """One row per payment attempt or refund (PHARMACY §7.6).

    ``is_refund`` distinguishes a charge from a refund row — the spec
    is ambiguous about how to encode the difference, so we add an
    explicit boolean flag (DECISION_LOG'd). ``amount`` is always
    positive (CHECK ``amount > 0``).
    """

    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("orders.id", name="fk_payments_order", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KGS")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_request: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
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
        CheckConstraint("amount > 0", name="chk_payments_amount_pos"),
        Index("idx_payments_order_created", "order_id", "created_at"),
        Index("idx_payments_status", "status"),
        Index("idx_payments_refund", "is_refund", "status"),
        # Phase 12 — payment_reconcile worker looks up by provider txn id;
        # without this index it's a full table scan on every cron tick.
        Index("idx_payments_provider_txn", "provider", "provider_transaction_id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )
