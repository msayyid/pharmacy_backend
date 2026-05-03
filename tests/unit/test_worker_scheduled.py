"""Unit tests — scheduled worker functions.

Each test pre-seeds the DB through the test session, runs the worker
function (which opens its own session_scope), then refreshes through
the test session to verify the worker's commit landed.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import uuid7
from app.domain.identity.models import OtpCode
from app.domain.inventory.models import (
    InventoryBatch,
    MovementType,
    StockMovement,
)
from app.domain.orders.models import (
    Cart,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.integrations.payments.base import ParsedEvent
from app.integrations.payments.factory import set_payment_client
from app.integrations.payments.fake import FakePaymentClient
from app.workers.scheduled import (
    cleanup_carts,
    cleanup_otps,
    expire_batches,
    payment_reconcile,
    release_pending_orders,
)
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)

pytestmark = pytest.mark.unit


def _utcnow() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


# ─── expire_batches ──────────────────────────────────────────────────────────


async def test_expire_batches_marks_expired_and_zeros_remaining(
    session: AsyncSession,
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    branch = await seed_branch(session, code=f"EXP-{secrets.token_hex(3)}")
    from tests.factories.catalog import seed_category, seed_product

    cat = await seed_category(session, slug=f"exp-{secrets.token_hex(3)}")
    p = await seed_product(
        session,
        sku=f"EXP-{secrets.token_hex(3)}",
        slug=f"exp-{secrets.token_hex(3)}",
        category_id=cat.id,
    )
    await seed_branch_product(session, branch_id=branch.id, product_id=p.id, total_quantity=20)
    expired_batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=p.id,
        batch_number=f"EXP-LOT-{secrets.token_hex(3)}",
        expiry_date=date.today() - timedelta(days=1),
        quantity_received=10,
    )
    fresh_batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=p.id,
        batch_number=f"FRESH-LOT-{secrets.token_hex(3)}",
        expiry_date=date.today() + timedelta(days=400),
        quantity_received=10,
    )
    await session.commit()

    result = await expire_batches({})
    assert result["expired"] >= 1

    await session.refresh(expired_batch)
    await session.refresh(fresh_batch)
    assert expired_batch.quantity_remaining == 0
    assert fresh_batch.quantity_remaining == 10  # untouched

    # One paired stock_movements row per expired batch.
    movements = (
        (
            await session.execute(
                select(StockMovement).where(
                    StockMovement.inventory_batch_id == expired_batch.id,
                    StockMovement.movement_type == MovementType.EXPIRED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(movements) == 1
    assert movements[0].quantity_change == -10


# ─── cleanup_otps ────────────────────────────────────────────────────────────


async def test_cleanup_otps_deletes_old_rows(
    session: AsyncSession,
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    """Insert a 10-day-old OTP + a fresh one; cleanup deletes only the old."""
    old = OtpCode(
        phone=f"+99670{secrets.randbelow(10**6):07d}",
        code_hash="x" * 64,
        purpose="login",
        attempts=0,
        expires_at=_utcnow() - timedelta(days=8),
        consumed_at=None,
    )
    fresh = OtpCode(
        phone=f"+99670{secrets.randbelow(10**6):07d}",
        code_hash="y" * 64,
        purpose="login",
        attempts=0,
        expires_at=_utcnow() + timedelta(minutes=5),
        consumed_at=None,
    )
    session.add_all([old, fresh])
    await session.flush()
    # Backdate the old one's created_at via raw SQL (server_default
    # captured "now" on insert).
    from sqlalchemy import text as _text

    await session.execute(
        _text("UPDATE otp_codes SET created_at = :ts WHERE id = :id"),
        {"ts": _utcnow() - timedelta(days=10), "id": old.id},
    )
    await session.commit()

    fresh_id = fresh.id
    old_id = old.id
    deleted = await cleanup_otps({})
    assert deleted >= 1

    # Identity-map: the worker's delete commits in a different session;
    # expunge here forces the test session to re-query.
    session.expunge_all()
    fresh_in_db = await session.get(OtpCode, fresh_id)
    old_in_db = await session.get(OtpCode, old_id)
    assert fresh_in_db is not None  # untouched
    assert old_in_db is None  # gone


# ─── cleanup_carts ───────────────────────────────────────────────────────────


async def test_cleanup_carts_deletes_expired(
    session: AsyncSession,
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    branch = await seed_branch(session, code=f"CC-{secrets.token_hex(3)}")
    expired_cart = Cart(
        id=uuid7(),
        user_id=None,
        session_id=secrets.token_hex(8),
        branch_id=branch.id,
        expires_at=_utcnow() - timedelta(hours=1),
    )
    fresh_cart = Cart(
        id=uuid7(),
        user_id=None,
        session_id=secrets.token_hex(8),
        branch_id=branch.id,
        expires_at=_utcnow() + timedelta(days=30),
    )
    session.add_all([expired_cart, fresh_cart])
    await session.commit()

    expired_id = expired_cart.id
    fresh_id = fresh_cart.id

    deleted = await cleanup_carts({})
    assert deleted >= 1

    session.expunge_all()
    assert await session.get(Cart, expired_id) is None
    assert await session.get(Cart, fresh_id) is not None


# ─── release_pending_orders ──────────────────────────────────────────────────


async def _seed_pending_card_order(
    session: AsyncSession,
    *,
    branch_id: int,
    placed_at: datetime,
) -> Order:
    order = Order(
        id=uuid7(),
        order_number=f"PH-RP-{secrets.token_hex(6).upper()}",
        user_id=None,
        branch_id=branch_id,
        status=OrderStatus.PENDING.value,
        payment_status=PaymentStatus.PENDING.value,
        payment_method=PaymentMethod.CARD_ONLINE.value,
        delivery_method="pickup",
        recipient_name="Test",
        recipient_phone="+996700000000",
        subtotal=Decimal("100"),
        delivery_fee=Decimal("0"),
        discount_amount=Decimal("0"),
        total=Decimal("100"),
        currency="KGS",
        placed_at=placed_at,
    )
    session.add(order)
    await session.commit()
    return order


async def test_release_pending_orders_cancels_only_stale(
    session: AsyncSession,
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    from app.domain.identity.models import AdminUser

    branch = await seed_branch(session, code=f"RP-{secrets.token_hex(3)}")
    # The release worker needs a super_admin actor for the audit row.
    admin = AdminUser(
        email=f"sys-{secrets.token_hex(4)}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="Sys",
        last_name="Bot",
        role="super_admin",
        is_active=True,
    )
    session.add(admin)
    await session.commit()

    stale = await _seed_pending_card_order(
        session,
        branch_id=branch.id,
        placed_at=_utcnow() - timedelta(minutes=45),  # past 30-min card threshold
    )
    fresh = await _seed_pending_card_order(
        session,
        branch_id=branch.id,
        placed_at=_utcnow() - timedelta(minutes=5),
    )

    cancelled = await release_pending_orders({})
    assert cancelled >= 1

    await session.refresh(stale)
    await session.refresh(fresh)
    assert stale.status == OrderStatus.CANCELLED.value
    assert stale.cancel_reason == "payment_failed"
    assert fresh.status == OrderStatus.PENDING.value


# ─── payment_reconcile ───────────────────────────────────────────────────────


@pytest.fixture
def fake_payment_client():  # type: ignore[no-untyped-def]
    client = FakePaymentClient()
    set_payment_client(client)
    yield client
    set_payment_client(None)


async def test_payment_reconcile_flips_pending_to_paid(
    session: AsyncSession,
    fake_payment_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    branch = await seed_branch(session, code=f"PR-{secrets.token_hex(3)}")
    order = Order(
        id=uuid7(),
        order_number=f"PH-PR-{secrets.token_hex(6).upper()}",
        user_id=None,
        branch_id=branch.id,
        status=OrderStatus.PENDING.value,
        payment_status=PaymentStatus.PENDING.value,
        payment_method=PaymentMethod.CARD_ONLINE.value,
        delivery_method="pickup",
        recipient_name="Test",
        recipient_phone="+996700000000",
        subtotal=Decimal("100"),
        delivery_fee=Decimal("0"),
        discount_amount=Decimal("0"),
        total=Decimal("100"),
        currency="KGS",
    )
    session.add(order)
    await session.flush()

    txn = f"fake-txn-{secrets.token_hex(6)}"
    backdated = _utcnow() - timedelta(minutes=15)
    payment = Payment(
        id=uuid7(),
        order_id=order.id,
        provider="fake",
        provider_transaction_id=txn,
        amount=Decimal("100"),
        currency="KGS",
        status=PaymentStatus.PENDING.value,
        is_refund=False,
        created_at=backdated,  # Pre-set so server_default doesn't overwrite.
    )
    session.add(payment)
    await session.commit()

    # Tell the fake gateway that this txn settled.
    fake_payment_client.set_pending_outcome(
        txn,
        ParsedEvent(
            event_id=f"reconcile-{uuid4().hex}",
            event_type="charge_succeeded",
            provider_transaction_id=txn,
            amount=Decimal("100"),
            currency="KGS",
            is_refund=False,
        ),
    )

    result = await payment_reconcile({})
    assert result["reconciled"] >= 1

    await session.refresh(payment)
    await session.refresh(order)
    assert payment.status == PaymentStatus.PAID.value
    assert order.payment_status == PaymentStatus.PAID.value


async def test_payment_reconcile_skips_fresh_pending(
    session: AsyncSession,
    fake_payment_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    """Payment created < 5 min ago must not be touched."""
    branch = await seed_branch(session, code=f"PRF-{secrets.token_hex(3)}")
    order = Order(
        id=uuid7(),
        order_number=f"PH-PF-{secrets.token_hex(6).upper()}",
        user_id=None,
        branch_id=branch.id,
        status=OrderStatus.PENDING.value,
        payment_status=PaymentStatus.PENDING.value,
        payment_method=PaymentMethod.CARD_ONLINE.value,
        delivery_method="pickup",
        recipient_name="Test",
        recipient_phone="+996700000000",
        subtotal=Decimal("50"),
        delivery_fee=Decimal("0"),
        discount_amount=Decimal("0"),
        total=Decimal("50"),
        currency="KGS",
    )
    session.add(order)
    await session.flush()
    payment = Payment(
        id=uuid7(),
        order_id=order.id,
        provider="fake",
        provider_transaction_id=f"fake-txn-{secrets.token_hex(6)}",
        amount=Decimal("50"),
        currency="KGS",
        status=PaymentStatus.PENDING.value,
        is_refund=False,
    )
    session.add(payment)
    await session.commit()

    result = await payment_reconcile({})
    # Won't even ask the gateway about a fresh row.
    assert result["reconciled"] == 0


# Remove unused imports flagged by ruff if linting tightens later.
_ = (InventoryBatch,)
