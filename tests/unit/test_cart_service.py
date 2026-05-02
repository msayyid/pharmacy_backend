"""Unit tests for ``CartService``.

* ``add_item`` caps at ``Product.max_per_order``.
* ``add_item`` rejects when current stock is insufficient.
* ``merge_guest_into_user`` is additive and respects the per-product cap.
* ``expire_check`` raises ``CartExpiredError`` past the TTL.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OutOfStockError
from app.core.types import uuid7
from app.domain.catalog.models import Product
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User
from app.domain.inventory.repositories import BranchProductRepository
from app.domain.orders.cart_service import CartExpiredError, CartService
from app.domain.orders.repositories import CartRepository
from tests.factories.catalog import (
    seed_category,
    seed_product,
)
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
)

pytestmark = pytest.mark.unit


def _make_service(session: AsyncSession) -> CartService:
    return CartService(
        carts=CartRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
    )


async def _make_user(session: AsyncSession, *, suffix: str) -> User:
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


async def _seed_priced_product(
    session: AsyncSession,
    *,
    branch_id: int,
    sku_suffix: str,
    max_per_order: int | None = None,
    available: int = 50,
    price: str = "100.00",
) -> Product:
    cat = await seed_category(session, slug=f"cat-cart-{sku_suffix}")
    p = await seed_product(
        session,
        sku=f"CART-{sku_suffix}",
        slug=f"cart-{sku_suffix}",
        category_id=cat.id,
    )
    if max_per_order is not None:
        p.max_per_order = max_per_order
    await seed_branch_product(
        session,
        branch_id=branch_id,
        product_id=p.id,
        price=Decimal(price),
        total_quantity=available,
    )
    await session.flush()
    return p


# ─── add_item ────────────────────────────────────────────────────────────────


async def test_add_item_creates_line_with_price_snapshot(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="add")
    branch = await seed_branch(session, code="CART-ADD-1")
    p = await _seed_priced_product(session, branch_id=branch.id, sku_suffix="add-1", price="123.00")

    cart = await svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
    item = await svc.add_item(cart=cart, product_id=p.id, quantity=2)
    assert item.quantity == 2
    assert item.price_snapshot == Decimal("123.00")


async def test_add_item_caps_at_max_per_order(session: AsyncSession) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="cap")
    branch = await seed_branch(session, code="CART-CAP-1")
    p = await _seed_priced_product(
        session,
        branch_id=branch.id,
        sku_suffix="cap-1",
        max_per_order=3,
    )

    cart = await svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
    item = await svc.add_item(cart=cart, product_id=p.id, quantity=10)
    assert item.quantity == 3


async def test_add_item_rejects_when_stock_insufficient(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="oos")
    branch = await seed_branch(session, code="CART-OOS-1")
    p = await _seed_priced_product(session, branch_id=branch.id, sku_suffix="oos-1", available=2)
    cart = await svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
    with pytest.raises(OutOfStockError):
        await svc.add_item(cart=cart, product_id=p.id, quantity=5)


async def test_update_qty_replaces_quantity(session: AsyncSession) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="upd")
    branch = await seed_branch(session, code="CART-UPD-1")
    p = await _seed_priced_product(session, branch_id=branch.id, sku_suffix="upd-1")
    cart = await svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
    item = await svc.add_item(cart=cart, product_id=p.id, quantity=2)
    updated = await svc.update_qty(cart=cart, item_id=item.id, quantity=5)
    assert updated.quantity == 5


async def test_remove_item_deletes_line(session: AsyncSession) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="rm")
    branch = await seed_branch(session, code="CART-RM-1")
    p = await _seed_priced_product(session, branch_id=branch.id, sku_suffix="rm-1")
    cart = await svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
    item = await svc.add_item(cart=cart, product_id=p.id, quantity=1)
    await svc.remove_item(cart=cart, item_id=item.id)

    full = await svc.get_with_items(cart.id)
    assert full is not None
    assert full.items == []


# ─── merge_guest_into_user ───────────────────────────────────────────────────


async def test_merge_guest_into_user_additive(session: AsyncSession) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="merge")
    branch = await seed_branch(session, code="CART-MERGE-1")
    p = await _seed_priced_product(session, branch_id=branch.id, sku_suffix="merge-1")

    # Guest cart: 2 of product.
    session_id = secrets.token_urlsafe(12)
    guest = await svc.get_or_create(branch_id=branch.id, user=None, session_id=session_id)
    await svc.add_item(cart=guest, product_id=p.id, quantity=2)

    # User cart: 3 of product (different cart).
    user_cart = await svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
    await svc.add_item(cart=user_cart, product_id=p.id, quantity=3)

    merged = await svc.merge_guest_into_user(user=user, session_id=session_id, branch_id=branch.id)
    full = await svc.get_with_items(merged.id)
    assert full is not None
    assert len(full.items) == 1
    assert full.items[0].quantity == 5  # additive


async def test_merge_promotes_guest_when_no_user_cart(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="prom")
    branch = await seed_branch(session, code="CART-PROM-1")
    session_id = secrets.token_urlsafe(12)

    guest = await svc.get_or_create(branch_id=branch.id, user=None, session_id=session_id)
    p = await _seed_priced_product(session, branch_id=branch.id, sku_suffix="prom-1")
    await svc.add_item(cart=guest, product_id=p.id, quantity=4)

    merged = await svc.merge_guest_into_user(user=user, session_id=session_id, branch_id=branch.id)
    assert merged.id == guest.id  # promoted, not duplicated
    assert merged.user_id == user.id
    assert merged.session_id is None


# ─── expire_check ────────────────────────────────────────────────────────────


async def test_add_item_rejects_on_expired_cart(session: AsyncSession) -> None:
    svc = _make_service(session)
    user = await _make_user(session, suffix="exp")
    branch = await seed_branch(session, code="CART-EXP-1")
    p = await _seed_priced_product(session, branch_id=branch.id, sku_suffix="exp-1")
    cart = await svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
    cart.expires_at = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(days=1)
    await session.flush()

    with pytest.raises(CartExpiredError):
        await svc.add_item(cart=cart, product_id=p.id, quantity=1)
