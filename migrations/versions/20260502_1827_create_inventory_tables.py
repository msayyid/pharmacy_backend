"""create inventory tables

Phase 6 — adds the four inventory tables that depend on Phase 5's
``products`` table:

* ``suppliers``                — distributor reference data.
* ``branch_products``          — composite PK (branch, product); cached
                                 ``total_quantity``/``reserved_quantity``
                                 plus pricing.
* ``inventory_batches``        — source-of-truth stock; FEFO scans here
                                 with ``FOR UPDATE SKIP LOCKED``.
* ``stock_movements``          — append-only audit. ``order_id`` is
                                 column-only at Phase 6 — Phase 8 adds
                                 the FK to ``orders.id`` once that table
                                 exists.

The ``chk_movement_sign`` CHECK is emitted via ``op.execute`` (Phase 5
discipline — keeps long, multi-clause CHECKs out of SQLAlchemy's
auto-quoter so the rendered DDL is exactly what we wrote).

Hand-edited from autogen output: removed spurious ``alter_column``
noise on previously-migrated tables (server_default rewriting); added
``import app.core.types``; emitted the movement-sign CHECK via
``op.execute``; added ``downgrade`` symmetry.

Revision ID: 896070994c68
Revises: 5b872d07a987
Create Date: 2026-05-02 18:27:21.686913+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import app.core.types

# revision identifiers, used by Alembic.
revision: str = "896070994c68"
down_revision: str | Sequence[str] | None = "5b872d07a987"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── suppliers ────────────────────────────────────────────────────────
    op.create_table(
        "suppliers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_suppliers_active", "suppliers", ["is_active"], unique=False)

    # ─── branch_products (composite PK) ───────────────────────────────────
    op.create_table(
        "branch_products",
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("compare_at_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("reserved_quantity", sa.Integer(), nullable=False),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.CheckConstraint("price >= 0", name="chk_bp_price_nonneg"),
        sa.CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= price",
            name="chk_bp_compare_ge_price",
        ),
        sa.CheckConstraint("total_quantity >= 0", name="chk_bp_total_nonneg"),
        sa.CheckConstraint("reserved_quantity >= 0", name="chk_bp_reserved_nonneg"),
        sa.CheckConstraint("reserved_quantity <= total_quantity", name="chk_bp_reserved_le_total"),
        sa.CheckConstraint("low_stock_threshold >= 0", name="chk_bp_threshold_nonneg"),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name="fk_branch_products_branch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_branch_products_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("branch_id", "product_id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_bp_low_stock",
        "branch_products",
        ["branch_id", "total_quantity"],
        unique=False,
    )
    op.create_index(
        "idx_bp_branch_available",
        "branch_products",
        ["branch_id", "is_available"],
        unique=False,
    )

    # ─── inventory_batches ────────────────────────────────────────────────
    op.create_table(
        "inventory_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=True),
        sa.Column("batch_number", sa.String(length=60), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("manufacture_date", sa.Date(), nullable=True),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("quantity_remaining", sa.Integer(), nullable=False),
        sa.Column(
            "quantity_reserved",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("cost_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "received_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
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
        sa.CheckConstraint("quantity_received > 0", name="chk_ib_received_pos"),
        sa.CheckConstraint("quantity_remaining >= 0", name="chk_ib_remaining_nonneg"),
        sa.CheckConstraint(
            "quantity_remaining <= quantity_received",
            name="chk_ib_remaining_le_received",
        ),
        sa.CheckConstraint("quantity_reserved >= 0", name="chk_ib_reserved_nonneg"),
        sa.CheckConstraint(
            "quantity_reserved <= quantity_remaining",
            name="chk_ib_reserved_le_remaining",
        ),
        sa.CheckConstraint("cost_price >= 0", name="chk_ib_cost_nonneg"),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], name="fk_ib_branch", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_ib_product", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_ib_supplier",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "product_id", "batch_number", name="uq_inventory_batch"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_ib_fefo",
        "inventory_batches",
        ["branch_id", "product_id", "expiry_date", "received_at"],
        unique=False,
    )
    op.create_index(
        "idx_ib_expiry",
        "inventory_batches",
        ["branch_id", "expiry_date"],
        unique=False,
    )

    # ─── stock_movements (append-only) ────────────────────────────────────
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inventory_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("movement_type", sa.String(length=16), nullable=False),
        sa.Column("quantity_change", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("order_id", app.core.types.GUID(length=16), nullable=True),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_users.id"],
            name="fk_sm_admin",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], name="fk_sm_branch", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["inventory_batch_id"],
            ["inventory_batches.id"],
            name="fk_sm_batch",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_sm_product", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_sm_branch_created",
        "stock_movements",
        ["branch_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_sm_product_created",
        "stock_movements",
        ["product_id", "created_at"],
        unique=False,
    )
    op.create_index("idx_sm_batch", "stock_movements", ["inventory_batch_id"])
    op.create_index("idx_sm_order", "stock_movements", ["order_id"])
    op.create_index("idx_sm_type", "stock_movements", ["movement_type"])

    # ─── chk_movement_sign — enforces sign-matches-type per PHARMACY §6.5 ─
    # Emitted via op.execute (Phase 5 discipline) so the multi-clause
    # disjunction lands in the DDL exactly as written, and so future
    # editors can read the rule without tracing SQLAlchemy quoting.
    op.execute(
        """
        ALTER TABLE stock_movements
        ADD CONSTRAINT chk_movement_sign CHECK (
            (movement_type IN ('received','released','transferred_in')
             AND quantity_change >= 0)
            OR (movement_type IN ('sold','reserved','expired','damaged','transferred_out')
             AND quantity_change <= 0)
            OR (movement_type = 'adjusted')
        )
        """
    )


def downgrade() -> None:
    # ``drop_table`` removes the table's indexes implicitly. Calling
    # ``drop_index`` first runs into MySQL's "Cannot drop index needed in
    # a foreign key constraint" — FK columns share their index with the
    # constraint and can only be dropped together with the table.
    op.drop_table("stock_movements")
    op.drop_table("inventory_batches")
    op.drop_table("branch_products")
    op.drop_table("suppliers")
