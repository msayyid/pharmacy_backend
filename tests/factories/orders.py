"""Order factories — in-session and committed seeders.

* :func:`seed_minimal_order` — the stub the Phase 6 inventory tests
  use to satisfy the ``fk_sm_order`` FK on ``stock_movements``.
* :func:`seed_cart` — empty cart bound to the given branch / owner.
* :func:`seed_cart_item` — append a line with explicit price snapshot.
* :func:`seed_cart_committed` etc — committed counterparts for E2E.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import uuid7
from app.domain.orders.models import Order, OrderStatus


async def seed_minimal_order(
    session: AsyncSession,
    *,
    branch_id: int,
    user_id: UUID | None = None,
    order_number: str | None = None,
    status: OrderStatus = OrderStatus.PENDING,
) -> Order:
    """Insert a tiny ``Order`` row with all required fields zeroed out.

    Used by tests that need a real ``orders.id`` to satisfy the
    ``fk_sm_order`` foreign key on ``stock_movements`` — the test
    doesn't care about totals or recipient details.
    """
    order_id = uuid7()
    o = Order(
        id=order_id,
        # Use uuid4 (random, not time-ordered) for test order_numbers —
        # two concurrent ``seed_minimal_order`` calls in the FEFO test
        # would collide on the time-prefix bytes of uuid7.
        order_number=order_number or f"PH-TEST-{uuid.uuid4().hex[:12].upper()}",
        user_id=user_id,
        branch_id=branch_id,
        status=status.value,
        payment_status="pending",
        payment_method="cash_on_delivery",
        delivery_method="delivery",
        recipient_name="Test",
        recipient_phone="+996700000000",
        delivery_address={"city": "Bishkek", "address_line": "test"},
        subtotal=Decimal("0"),
        delivery_fee=Decimal("0"),
        discount_amount=Decimal("0"),
        total=Decimal("0"),
        currency="KGS",
        placed_at=datetime.now(tz=UTC).replace(tzinfo=None),
    )
    session.add(o)
    await session.flush()
    return o


# ─── Cart helpers ────────────────────────────────────────────────────────────


from datetime import timedelta  # noqa: E402

from app.domain.orders.models import Cart, CartItem  # noqa: E402


async def seed_cart(
    session: AsyncSession,
    *,
    branch_id: int,
    user_id: UUID | None = None,
    session_id: str | None = None,
    expires_in_days: int = 30,
) -> Cart:
    cart = Cart(
        id=uuid7(),
        user_id=user_id,
        session_id=session_id,
        branch_id=branch_id,
        currency="KGS",
        expires_at=datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(days=expires_in_days),
    )
    session.add(cart)
    await session.flush()
    return cart


async def seed_cart_item(
    session: AsyncSession,
    *,
    cart_id: UUID,
    product_id: UUID,
    quantity: int = 1,
    price_snapshot: Decimal | str = "100.00",
) -> CartItem:
    item = CartItem(
        cart_id=cart_id,
        product_id=product_id,
        quantity=quantity,
        price_snapshot=Decimal(price_snapshot)
        if isinstance(price_snapshot, str)
        else price_snapshot,
    )
    session.add(item)
    await session.flush()
    return item


# ─── Committed E2E variants ──────────────────────────────────────────────────


from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402


async def seed_cart_committed(
    *,
    branch_id: int,
    user_id: UUID | None = None,
    session_id: str | None = None,
) -> UUID:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            cart = Cart(
                id=uuid7(),
                user_id=user_id,
                session_id=session_id,
                branch_id=branch_id,
                currency="KGS",
                expires_at=datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(days=30),
            )
            s.add(cart)
            await s.commit()
            return cart.id
    finally:
        await engine.dispose()
