"""create payments + courier columns

Phase 9 — adds the ``payments`` table (stub for Phase 10's real
gateway wiring) and the inline ``courier_name`` / ``courier_phone``
columns on ``orders`` (Phase 10 moves these to a dedicated
``deliveries`` table per PHARMACY §7.7).

Hand-edited from autogen: removed spurious ``alter_column`` noise on
previously-migrated tables; added ``import app.core.types``.

Revision ID: d8499a5e7876
Revises: ff2951f68321
Create Date: 2026-05-02 21:36:47.510204+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import app.core.types

revision: str = "d8499a5e7876"
down_revision: str | Sequence[str] | None = "ff2951f68321"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── payments ─────────────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("order_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=120), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_refund", sa.Boolean(), nullable=False),
        sa.Column("raw_request", sa.JSON(), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("paid_at", mysql.DATETIME(fsp=6), nullable=True),
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
        sa.CheckConstraint("amount > 0", name="chk_payments_amount_pos"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_payments_order",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_payments_order_created", "payments", ["order_id", "created_at"])
    op.create_index("idx_payments_status", "payments", ["status"])
    op.create_index("idx_payments_refund", "payments", ["is_refund", "status"])

    # ─── courier columns on orders ────────────────────────────────────────
    op.add_column("orders", sa.Column("courier_name", sa.String(length=160), nullable=True))
    op.add_column("orders", sa.Column("courier_phone", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "courier_phone")
    op.drop_column("orders", "courier_name")
    op.drop_table("payments")
