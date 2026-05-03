"""add idx_orders_recipient_phone + idx_payments_provider_txn (Phase 12)

Two missing indexes surfaced by the Phase 12.1 audit:

* ``idx_orders_recipient_phone`` — admin support workflow looks up orders
  by phone (PRODUCT §18.2 "Where's my order?"). Without an index this is
  a full table scan.
* ``idx_payments_provider_txn`` — the ``payment_reconcile`` worker
  (Phase 11) selects by ``provider`` + ``provider_transaction_id``;
  without this index every cron tick scans the payments table.

Hand-edited from autogen to drop the spurious ``alter_column`` noise on
existing tables (server-default detection emits diffs that no-op in
MySQL — same Phase 5/9/10 finding).

Revision ID: 22f5c07c42b5
Revises: ac097ed3c5aa
Create Date: 2026-05-03 02:56:43.974624+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "22f5c07c42b5"
down_revision: str | Sequence[str] | None = "ac097ed3c5aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_orders_recipient_phone",
        "orders",
        ["recipient_phone"],
    )
    op.create_index(
        "idx_payments_provider_txn",
        "payments",
        ["provider", "provider_transaction_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_payments_provider_txn", table_name="payments")
    op.drop_index("idx_orders_recipient_phone", table_name="orders")
