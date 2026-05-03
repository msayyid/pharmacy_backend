"""create sms_log + deliveries (Phase 10)

Two new tables for the integrations phase:

* ``sms_log`` (PHARMACY §8.2) — one row per SMS attempt; written
  ``status='queued'`` from the enqueue site, flipped to ``sent`` /
  ``failed`` by the worker after the provider responds.
* ``deliveries`` (PHARMACY §7.7) — per-order courier handover record.
  Inserted when the order moves to ``out_for_delivery``; carries
  assignment / pickup / drop-off timestamps, tracking number, and
  actual delivery fee. The ``courier_name`` / ``courier_phone``
  columns added on ``orders`` in Phase 9 are retained as a
  denormalised cache so the simple "show courier on order detail"
  read needs no join (DECISION_LOG'd).

Hand-edited from autogen to drop the spurious ``alter_column`` noise
on existing tables (server-default detection emits diffs that no-op
in MySQL — same Phase 5/9 finding).

Revision ID: ac097ed3c5aa
Revises: d8499a5e7876
Create Date: 2026-05-03 01:08:19.597127+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import app.core.types

revision: str = "ac097ed3c5aa"
down_revision: str | Sequence[str] | None = "d8499a5e7876"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── sms_log ──────────────────────────────────────────────────────────
    op.create_table(
        "sms_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_message_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cost", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_sms_phone_created", "sms_log", ["phone", "created_at"])
    op.create_index("idx_sms_purpose_created", "sms_log", ["purpose", "created_at"])
    op.create_index("idx_sms_status_created", "sms_log", ["status", "created_at"])

    # ─── deliveries ───────────────────────────────────────────────────────
    op.create_table(
        "deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", app.core.types.GUID(length=16), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("courier_name", sa.String(length=160), nullable=True),
        sa.Column("courier_phone", sa.String(length=20), nullable=True),
        sa.Column("tracking_number", sa.String(length=80), nullable=True),
        sa.Column("estimated_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("assigned_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("picked_up_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("delivered_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("delivery_fee_actual", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_deliveries_order",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_deliveries_order"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_deliveries_provider_assigned",
        "deliveries",
        ["provider", "assigned_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_deliveries_provider_assigned", table_name="deliveries")
    op.drop_table("deliveries")
    op.drop_index("idx_sms_status_created", table_name="sms_log")
    op.drop_index("idx_sms_purpose_created", table_name="sms_log")
    op.drop_index("idx_sms_phone_created", table_name="sms_log")
    op.drop_table("sms_log")
