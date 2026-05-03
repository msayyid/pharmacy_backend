"""add password_hash to users (dev auth)

Local-dev convenience added on top of v1.0.0-rc1: customer accounts
can now log in with email + argon2id password hash, in addition to the
existing SMS-OTP flow. Production deploys still use SMS-OTP per
PRODUCT §17 + PHARMACY §3.2 — see DECISION_LOG entry "Local-dev
password auth alongside SMS-OTP".

The column is nullable so existing OTP-only users keep ``None``;
the new ``POST /api/v1/auth/register`` + ``POST /api/v1/auth/login``
routes set it for password-based accounts.

Hand-edited from autogen to drop the spurious ``alter_column`` noise
on existing tables (server-default detection emits diffs that no-op
in MySQL — same Phase 5/9/10/12 finding).

Revision ID: 151a5f8620f0
Revises: 22f5c07c42b5
Create Date: 2026-05-03 13:38:12.889537+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "151a5f8620f0"
down_revision: str | Sequence[str] | None = "22f5c07c42b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
