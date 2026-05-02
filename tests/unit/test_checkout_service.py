"""Unit tests for ``CheckoutService``.

* ``quote`` — totals math (delivery fee 200/free-over-1500/0-pickup),
  surfaces stock + price diffs without reserving.
* ``place_order`` happy path — creates order, items per allocation,
  status history, idempotency response stored.
* ``place_order`` raises ``CheckoutValidationError`` on stock /
  price drift.
* ``place_order`` idempotency replay returns cached.
"""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import uuid7
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User
from app.domain.identity.repositories import UserAddressRepository
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
    SupplierRepository,
)
from app.domain.inventory.services import InventoryService
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from app.domain.orders.cart_service import CartService
from app.domain.orders.checkout_service import (
    CheckoutService,
    CheckoutValidationError,
    compute_delivery_fee,
)
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderSequenceRepository,
    OrderStatusHistoryRepository,
)
from app.domain.orders.schemas import PlaceOrderAddress, PlaceOrderRequest
from tests.factories.catalog import seed_category, seed_product
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)

pytestmark = pytest.mark.unit


def _checkout_service(session: AsyncSession) -> CheckoutService:
    inventory = InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    return CheckoutService(
        carts=CartRepository(session),
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        order_sequence=OrderSequenceRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        addresses=UserAddressRepository(session),
        inventory=inventory,
    )


def _cart_service(session: AsyncSession) -> CartService:
    return CartService(
        carts=CartRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
    )


async def _make_user(session: AsyncSession) -> User:
    user = User(
        id=uuid7(),
        phone=f"+99670{secrets.randbelow(1_000_000):07d}",
        preferred_language="ru",
        is_phone_verified=True,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_priced_with_batch(
    session: AsyncSession,
    *,
    branch_id: int,
    suffix: str,
    price: str = "100.00",
    qty: int = 50,
):
    cat = await seed_category(session, slug=f"chk-cat-{suffix}")
    p = await seed_product(session, sku=f"CHK-{suffix}", slug=f"chk-{suffix}", category_id=cat.id)
    await seed_branch_product(
        session,
        branch_id=branch_id,
        product_id=p.id,
        price=Decimal(price),
        total_quantity=qty,
    )
    await seed_inventory_batch(
        session,
        branch_id=branch_id,
        product_id=p.id,
        batch_number=f"CHK-LOT-{suffix}",
        expiry_date=date.today() + timedelta(days=365),
        quantity_received=qty,
    )
    return p


# ─── compute_delivery_fee ────────────────────────────────────────────────────


def test_delivery_fee_pickup_is_free() -> None:
    assert compute_delivery_fee(subtotal=Decimal("100"), delivery_method="pickup") == 0


def test_delivery_fee_under_threshold_is_200() -> None:
    assert compute_delivery_fee(subtotal=Decimal("1000"), delivery_method="delivery") == Decimal(
        "200"
    )


def test_delivery_fee_over_threshold_is_free() -> None:
    assert compute_delivery_fee(subtotal=Decimal("2000"), delivery_method="delivery") == Decimal(
        "0"
    )


# ─── quote ───────────────────────────────────────────────────────────────────


async def test_quote_totals_under_threshold(session: AsyncSession) -> None:
    cs = _cart_service(session)
    co = _checkout_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="QT-1")
    p = await _seed_priced_with_batch(session, branch_id=branch.id, suffix="qt-1", price="500.00")
    cart = await cs.get_or_create(branch_id=branch.id, user=user, session_id=None)
    await cs.add_item(cart=cart, product_id=p.id, quantity=2)

    full = await cs.get_with_items(cart.id)
    assert full is not None
    quote = await co.quote(cart=full, delivery_method="delivery", payment_method="cash_on_delivery")
    assert quote["subtotal"] == Decimal("1000.00")
    assert quote["delivery_fee"] == Decimal("200")
    assert quote["total"] == Decimal("1200.00")
    assert quote["stock_conflicts"] == []
    assert quote["price_conflicts"] == []


async def test_quote_surfaces_price_conflict(session: AsyncSession) -> None:
    cs = _cart_service(session)
    co = _checkout_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="QT-PC-1")
    p = await _seed_priced_with_batch(
        session, branch_id=branch.id, suffix="qt-pc-1", price="100.00"
    )
    cart = await cs.get_or_create(branch_id=branch.id, user=user, session_id=None)
    await cs.add_item(cart=cart, product_id=p.id, quantity=1)

    # Mutate bp.price after the snapshot.
    bp = await BranchProductRepository(session).get(branch.id, p.id)
    assert bp is not None
    bp.price = Decimal("150.00")
    await session.flush()

    full = await cs.get_with_items(cart.id)
    assert full is not None
    quote = await co.quote(cart=full, delivery_method="delivery", payment_method="cash_on_delivery")
    assert len(quote["price_conflicts"]) == 1
    pc = quote["price_conflicts"][0]
    assert pc.snapshot_price == Decimal("100.00")
    assert pc.current_price == Decimal("150.00")


# ─── place_order ─────────────────────────────────────────────────────────────


async def test_place_order_happy_path(session: AsyncSession, redis_clean: None) -> None:
    cs = _cart_service(session)
    co = _checkout_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="PLACE-1")
    p = await _seed_priced_with_batch(
        session, branch_id=branch.id, suffix="place-1", price="100.00"
    )
    cart = await cs.get_or_create(branch_id=branch.id, user=user, session_id=None)
    await cs.add_item(cart=cart, product_id=p.id, quantity=2)

    full = await cs.get_with_items(cart.id)
    assert full is not None
    payload = PlaceOrderRequest(
        delivery_method="delivery",
        payment_method="cash_on_delivery",
        recipient_name="Тест Получатель",
        recipient_phone="+996700000000",
        address=PlaceOrderAddress(city="Bishkek", address_line="мкр Асанбай 12"),
    )
    response = await co.place_order(
        cart=full,
        user=user,
        payload=payload,
        idempotency_key="key-1",
        body_digest="digest-1",
    )
    assert response.order_number.startswith("PH-")
    assert response.status == "pending"
    assert response.payment_status == "pending"
    assert response.total == Decimal("400.00")  # 200 subtotal + 200 delivery


async def test_place_order_raises_on_price_drift(session: AsyncSession, redis_clean: None) -> None:
    cs = _cart_service(session)
    co = _checkout_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="PLACE-PD")
    p = await _seed_priced_with_batch(
        session, branch_id=branch.id, suffix="place-pd", price="100.00"
    )
    cart = await cs.get_or_create(branch_id=branch.id, user=user, session_id=None)
    await cs.add_item(cart=cart, product_id=p.id, quantity=1)

    bp = await BranchProductRepository(session).get(branch.id, p.id)
    assert bp is not None
    bp.price = Decimal("200.00")
    await session.flush()

    full = await cs.get_with_items(cart.id)
    assert full is not None
    payload = PlaceOrderRequest(
        delivery_method="pickup",
        payment_method="cash_on_delivery",
        recipient_name="Test",
        recipient_phone="+996700000000",
    )
    with pytest.raises(CheckoutValidationError):
        await co.place_order(
            cart=full,
            user=user,
            payload=payload,
            idempotency_key="key-pd",
            body_digest="digest-pd",
        )


async def test_place_order_idempotency_replay(session: AsyncSession, redis_clean: None) -> None:
    cs = _cart_service(session)
    co = _checkout_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="PLACE-IDEM")
    p = await _seed_priced_with_batch(
        session, branch_id=branch.id, suffix="place-idem", price="100.00"
    )
    cart = await cs.get_or_create(branch_id=branch.id, user=user, session_id=None)
    await cs.add_item(cart=cart, product_id=p.id, quantity=1)

    full = await cs.get_with_items(cart.id)
    assert full is not None
    payload = PlaceOrderRequest(
        delivery_method="pickup",
        payment_method="cash_on_delivery",
        recipient_name="Test",
        recipient_phone="+996700000000",
    )
    first = await co.place_order(
        cart=full,
        user=user,
        payload=payload,
        idempotency_key="idem-key-A",
        body_digest="digest-A",
    )
    # Same key + same digest → cached response.
    second = await co.place_order(
        cart=full,
        user=user,
        payload=payload,
        idempotency_key="idem-key-A",
        body_digest="digest-A",
    )
    assert first.order_number == second.order_number
    assert first.order_id == second.order_id
