"""create orders + cart

Phase 8 — adds the cart + orders subsystem and lifts the deferred
``fk_sm_order`` FK on ``stock_movements.order_id`` to point at
``orders.id`` (Phase 6 left the column without a constraint because
the table didn't exist yet).

Tables added:
* ``carts`` + ``cart_items``
* ``orders`` + ``order_items`` + ``order_status_history``
* ``order_sequences`` (per-year ``order_number`` counter)

CHECK constraints emitted via ``op.execute`` for parity with prior
phases (multi-clause / arithmetic CHECKs go through raw DDL):
* ``chk_orders_total CHECK (total = subtotal + delivery_fee - discount_amount)``
* ``chk_order_items_total CHECK (line_total = unit_price * quantity)``

Hand-edited from autogen: removed spurious ``alter_column`` noise on
previously-migrated tables; added ``import app.core.types``.

Revision ID: ff2951f68321
Revises: 5fd2f128b471
Create Date: 2026-05-02 19:36:51.868578+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import app.core.types

revision: str = "ff2951f68321"
down_revision: str | Sequence[str] | None = "5fd2f128b471"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── order_sequences ──────────────────────────────────────────────────
    op.create_table(
        "order_sequences",
        sa.Column("year", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("last_assigned", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("last_assigned >= 0", name="chk_order_seq_nonneg"),
        sa.PrimaryKeyConstraint("year"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )

    # ─── carts ────────────────────────────────────────────────────────────
    op.create_table(
        "carts",
        sa.Column("id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("user_id", app.core.types.GUID(length=16), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.CheckConstraint(
            "user_id IS NOT NULL OR session_id IS NOT NULL",
            name="chk_carts_owner",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name="fk_carts_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_carts_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_carts_user", "carts", ["user_id"])
    op.create_index("idx_carts_session", "carts", ["session_id"])
    op.create_index("idx_carts_expires", "carts", ["expires_at"])

    # ─── cart_items ───────────────────────────────────────────────────────
    op.create_table(
        "cart_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cart_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_snapshot", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "added_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="chk_cart_items_qty_pos"),
        sa.CheckConstraint("price_snapshot >= 0", name="chk_cart_items_price_nonneg"),
        sa.ForeignKeyConstraint(
            ["cart_id"],
            ["carts.id"],
            name="fk_cart_items_cart",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_cart_items_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cart_id", "product_id", name="uq_cart_items"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_cart_items_cart", "cart_items", ["cart_id"])

    # ─── orders ───────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("user_id", app.core.types.GUID(length=16), nullable=True),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payment_status", sa.String(length=20), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column("delivery_method", sa.String(length=20), nullable=False),
        sa.Column("recipient_name", sa.String(length=160), nullable=False),
        sa.Column("recipient_phone", sa.String(length=20), nullable=False),
        sa.Column("delivery_address", sa.JSON(), nullable=True),
        sa.Column("delivery_latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("delivery_longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
        ),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("customer_notes", sa.Text(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "placed_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column("confirmed_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("delivered_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("cancelled_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("subtotal >= 0", name="chk_orders_subtotal_nonneg"),
        sa.CheckConstraint("delivery_fee >= 0", name="chk_orders_delivery_nonneg"),
        sa.CheckConstraint("discount_amount >= 0", name="chk_orders_discount_nonneg"),
        sa.CheckConstraint("total >= 0", name="chk_orders_total_nonneg"),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name="fk_orders_branch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_orders_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_orders_user_created", "orders", ["user_id", "created_at"])
    op.create_index("idx_orders_branch_status", "orders", ["branch_id", "status"])
    op.create_index("idx_orders_placed", "orders", ["placed_at"])
    op.create_index("idx_orders_status_payment", "orders", ["status", "payment_status"])

    # ``chk_orders_total`` — emitted via op.execute (Phase 5/6 discipline).
    op.execute(
        """
        ALTER TABLE orders
        ADD CONSTRAINT chk_orders_total
        CHECK (total = subtotal + delivery_fee - discount_amount)
        """
    )

    # ─── order_items ──────────────────────────────────────────────────────
    op.create_table(
        "order_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=True),
        sa.Column("inventory_batch_id", sa.BigInteger(), nullable=True),
        sa.Column("product_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("product_sku_snapshot", sa.String(length=40), nullable=False),
        sa.Column("batch_number_snapshot", sa.String(length=60), nullable=True),
        sa.Column("expiry_date_snapshot", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="chk_order_items_qty_pos"),
        sa.CheckConstraint("unit_price >= 0", name="chk_order_items_unit_nonneg"),
        sa.CheckConstraint("line_total >= 0", name="chk_order_items_line_nonneg"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_items_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_order_items_product",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_batch_id"],
            ["inventory_batches.id"],
            name="fk_order_items_batch",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_order_items_order", "order_items", ["order_id"])
    op.create_index("idx_order_items_product", "order_items", ["product_id"])
    op.create_index("idx_order_items_batch", "order_items", ["inventory_batch_id"])

    op.execute(
        """
        ALTER TABLE order_items
        ADD CONSTRAINT chk_order_items_total
        CHECK (line_total = unit_price * quantity)
        """
    )

    # ─── order_status_history ─────────────────────────────────────────────
    op.create_table(
        "order_status_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("changed_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("changed_by_system", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_osh_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_admin_id"],
            ["admin_users.id"],
            name="fk_osh_admin",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_osh_order", "order_status_history", ["order_id", "created_at"])

    # ─── Lift the deferred fk_sm_order FK (Phase 6 → Phase 8) ─────────────
    op.create_foreign_key(
        "fk_sm_order",
        "stock_movements",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sm_order", "stock_movements", type_="foreignkey")
    # Drop tables in reverse FK order so FK CASCADEs don't conflict.
    op.drop_table("order_status_history")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("cart_items")
    op.drop_table("carts")
    op.drop_table("order_sequences")
