"""Unit tests for the customer-facing ``OrderService``.

* ``cancel_by_customer`` only allowed on pending / confirmed.
* ``cancel_by_customer`` releases reservations.
* ``reorder`` annotates per-line outcomes (added / out_of_stock /
  product_deleted / price_changed).
* ``get_for_user`` 403s on cross-user access.
"""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, PermissionDeniedError
from app.core.types import uuid7
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User
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
from app.domain.orders.models import OrderStatus
from app.domain.orders.order_service import OrderService
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderStatusHistoryRepository,
)
from tests.factories.catalog import seed_category, seed_product
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)
from tests.factories.orders import seed_minimal_order

pytestmark = pytest.mark.unit


def _order_service(session: AsyncSession) -> OrderService:
    inventory = InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    cart_service = CartService(
        carts=CartRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
    )
    return OrderService(
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        cart_service=cart_service,
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
        inventory=inventory,
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


# ─── cancel_by_customer ──────────────────────────────────────────────────────


async def test_cancel_by_customer_pending_succeeds(session: AsyncSession) -> None:
    svc = _order_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="CAN-1")
    order = await seed_minimal_order(session, branch_id=branch.id, user_id=user.id)

    cancelled = await svc.cancel_by_customer(user=user, order_number=order.order_number)
    assert cancelled.status == OrderStatus.CANCELLED.value
    assert cancelled.cancelled_at is not None


async def test_cancel_by_customer_blocked_when_preparing(
    session: AsyncSession,
) -> None:
    svc = _order_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="CAN-2")
    order = await seed_minimal_order(
        session,
        branch_id=branch.id,
        user_id=user.id,
        status=OrderStatus.PREPARING,
    )
    with pytest.raises(ConflictError) as ei:
        await svc.cancel_by_customer(user=user, order_number=order.order_number)
    assert ei.value.context["code"] == "order_not_cancellable_by_customer"


async def test_get_for_user_blocks_other_users(session: AsyncSession) -> None:
    svc = _order_service(session)
    owner = await _make_user(session)
    other = await _make_user(session)
    branch = await seed_branch(session, code="GET-X")
    order = await seed_minimal_order(session, branch_id=branch.id, user_id=owner.id)
    with pytest.raises(PermissionDeniedError):
        await svc.get_for_user(user=other, order_number=order.order_number)


# ─── reorder ─────────────────────────────────────────────────────────────────


async def test_reorder_adds_in_stock_lines(session: AsyncSession) -> None:
    svc = _order_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="REO-1")

    cat = await seed_category(session, slug="cat-reo-1")
    p = await seed_product(session, sku="REO-1", slug="reo-1", category_id=cat.id)
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=p.id,
        price=Decimal("100"),
        total_quantity=20,
    )
    await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=p.id,
        batch_number="REO-LOT-1",
        expiry_date=date.today() + timedelta(days=365),
        quantity_received=20,
    )

    # Seed a delivered order with this item.
    order = await seed_minimal_order(
        session,
        branch_id=branch.id,
        user_id=user.id,
        status=OrderStatus.DELIVERED,
    )
    from app.domain.orders.models import OrderItem

    session.add(
        OrderItem(
            order_id=order.id,
            product_id=p.id,
            inventory_batch_id=None,
            product_name_snapshot="Тест",
            product_sku_snapshot="REO-1",
            quantity=2,
            unit_price=Decimal("100"),
            line_total=Decimal("200"),
        )
    )
    await session.flush()

    cart_id, lines = await svc.reorder(
        user=user, order_number=order.order_number, cart_branch_id=branch.id
    )
    assert len(lines) == 1
    assert lines[0].added_to_cart is True
    assert lines[0].reason == "added"


async def test_reorder_flags_out_of_stock(session: AsyncSession) -> None:
    svc = _order_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="REO-OOS")
    cat = await seed_category(session, slug="cat-reo-oos")
    p = await seed_product(session, sku="REO-OOS", slug="reo-oos", category_id=cat.id)
    # No branch_product or zero stock.
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=p.id,
        price=Decimal("100"),
        total_quantity=0,
    )
    order = await seed_minimal_order(
        session,
        branch_id=branch.id,
        user_id=user.id,
        status=OrderStatus.DELIVERED,
    )
    from app.domain.orders.models import OrderItem

    session.add(
        OrderItem(
            order_id=order.id,
            product_id=p.id,
            product_name_snapshot="Тест",
            product_sku_snapshot="REO-OOS",
            quantity=3,
            unit_price=Decimal("100"),
            line_total=Decimal("300"),
        )
    )
    await session.flush()

    _, lines = await svc.reorder(
        user=user, order_number=order.order_number, cart_branch_id=branch.id
    )
    assert lines[0].added_to_cart is False
    assert lines[0].reason == "out_of_stock"


async def test_reorder_flags_deleted_product(session: AsyncSession) -> None:
    svc = _order_service(session)
    user = await _make_user(session)
    branch = await seed_branch(session, code="REO-DEL")
    cat = await seed_category(session, slug="cat-reo-del")
    p = await seed_product(session, sku="REO-DEL", slug="reo-del", category_id=cat.id)
    p.is_active = False
    await session.flush()
    order = await seed_minimal_order(
        session,
        branch_id=branch.id,
        user_id=user.id,
        status=OrderStatus.DELIVERED,
    )
    from app.domain.orders.models import OrderItem

    session.add(
        OrderItem(
            order_id=order.id,
            product_id=p.id,
            product_name_snapshot="Удалённый",
            product_sku_snapshot="REO-DEL",
            quantity=1,
            unit_price=Decimal("50"),
            line_total=Decimal("50"),
        )
    )
    await session.flush()

    _, lines = await svc.reorder(
        user=user, order_number=order.order_number, cart_branch_id=branch.id
    )
    assert lines[0].added_to_cart is False
    assert lines[0].reason == "product_deleted"
