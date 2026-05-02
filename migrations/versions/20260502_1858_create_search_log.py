"""create search_log

Phase 7 — adds the storefront search analytics table. One row per
``/search`` submission; the catalog-gap signal is rows with
``results_count = 0``.

Hand-edited from autogen: removed spurious ``alter_column`` noise on
previously-migrated tables (server_default rewriting); added
``import app.core.types``.

Revision ID: 5fd2f128b471
Revises: 896070994c68
Create Date: 2026-05-02 18:58:43.297916+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

import app.core.types

revision: str = "5fd2f128b471"
down_revision: str | Sequence[str] | None = "896070994c68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("query", sa.String(length=255), nullable=False),
        sa.Column("language_code", sa.String(length=8), nullable=True),
        sa.Column("user_id", app.core.types.GUID(length=16), nullable=True),
        sa.Column("results_count", sa.Integer(), nullable=False),
        sa.Column(
            "clicked_product_id",
            app.core.types.GUID(length=16),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            server_default=sa.text("utc_timestamp(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["clicked_product_id"],
            ["products.id"],
            name="fk_search_log_product",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_search_log_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("idx_sl_created", "search_log", ["created_at"])
    op.create_index("idx_sl_query", "search_log", ["query"])
    op.create_index(
        "idx_sl_results_created",
        "search_log",
        ["results_count", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("search_log")
