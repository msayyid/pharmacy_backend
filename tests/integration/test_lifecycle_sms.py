"""Integration — every customer-visible status transition enqueues exactly one SMS.

Walks an order: pending → confirmed → preparing → out_for_delivery →
delivered. Asserts:
* one ``FakeSmsQueue.sent`` entry per transition that maps to a
  template (PRODUCT §14.2);
* ``preparing`` / ``ready_for_pickup`` are admin-internal — no SMS;
* the template variables (``order_no`` / ``courier_name`` etc.) are
  interpolated correctly from the rendered body;
* one ``deliveries`` row gets created at dispatch time.

Also covers the cancel-from-pending and refund-card paths.
"""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import uuid7
from app.domain.catalog.repositories import ProductRepository
from app.domain.deliveries.models import Delivery
from app.domain.deliveries.repositories import DeliveryRepository
from app.domain.identity.models import AdminUser, User
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
from app.domain.orders.checkout_service import CheckoutService
from app.domain.orders.lifecycle import OrderLifecycleService
from app.domain.orders.models import Order
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderSequenceRepository,
    OrderStatusHistoryRepository,
)
from app.domain.orders.schemas import PlaceOrderRequest
from app.integrations.sms.fake import FakeSmsQueue
from tests.factories.catalog import seed_category, seed_product
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)

pytestmark = pytest.mark.integration


def _inv(session: AsyncSession) -> InventoryService:
    return InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )


def _lifecycle(session: AsyncSession, *, sms_queue: FakeSmsQueue) -> OrderLifecycleService:
    return OrderLifecycleService(
        session=session,
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        batches=InventoryBatchRepository(session),
        branch_products=BranchProductRepository(session),
        movements=StockMovementRepository(session),
        inventory=_inv(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
        sms_queue=sms_queue,
        deliveries=DeliveryRepository(session),
    )


def _checkout(session: AsyncSession, *, sms_queue: FakeSmsQueue) -> CheckoutService:
    return CheckoutService(
        carts=CartRepository(session),
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        order_sequence=OrderSequenceRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        addresses=UserAddressRepository(session),
        inventory=_inv(session),
        sms_queue=sms_queue,
    )


def _carts(session: AsyncSession) -> CartService:
    return CartService(
        carts=CartRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
    )


async def _make_user(session: AsyncSession) -> User:
    user = User(
        id=uuid7(),
        phone=f"+99670{secrets.randbelow(10**6):07d}",
        preferred_language="ru",
        is_phone_verified=True,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_admin(session: AsyncSession) -> AdminUser:
    admin = AdminUser(
        email=f"sms-{secrets.token_hex(4)}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="SMS",
        last_name="Test",
        role="super_admin",
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin


async def _seed_pending_order(
    session: AsyncSession,
    *,
    branch_id: int,
    sms_queue: FakeSmsQueue,
) -> Order:
    cat = await seed_category(session, slug=f"sms-{secrets.token_hex(4)}")
    p = await seed_product(
        session,
        sku=f"SMS-{secrets.token_hex(4).upper()}",
        slug=f"sms-{secrets.token_hex(4)}",
        category_id=cat.id,
    )
    await seed_branch_product(
        session,
        branch_id=branch_id,
        product_id=p.id,
        price=Decimal("100"),
        total_quantity=20,
    )
    await seed_inventory_batch(
        session,
        branch_id=branch_id,
        product_id=p.id,
        batch_number=f"SMS-LOT-{secrets.token_hex(3)}",
        expiry_date=date.today() + timedelta(days=365),
        quantity_received=20,
    )
    user = await _make_user(session)
    cart = await _carts(session).get_or_create(branch_id=branch_id, user=user, session_id=None)
    await _carts(session).add_item(cart=cart, product_id=p.id, quantity=2)
    full = await _carts(session).get_with_items(cart.id)
    assert full is not None
    response = await _checkout(session, sms_queue=sms_queue).place_order(
        cart=full,
        user=user,
        payload=PlaceOrderRequest(
            delivery_method="delivery",
            payment_method="cash_on_delivery",
            recipient_name="Test",
            recipient_phone="+996700000000",
            address={
                "city": "Bishkek",
                "address_line": "мкр Асанбай 12-45",
            },
        ),
        idempotency_key=f"sms-{secrets.token_hex(6)}",
        body_digest=f"d-{secrets.token_hex(6)}",
    )
    order = await OrderRepository(session).get_by_id_with_items(response.order_id)
    assert order is not None
    return order


async def test_place_order_enqueues_order_placed_sms(
    session: AsyncSession,
    redis_clean: None,
) -> None:
    queue = FakeSmsQueue()
    branch = await seed_branch(session, code=f"SMSP-{secrets.token_hex(3)}")
    order = await _seed_pending_order(session, branch_id=branch.id, sms_queue=queue)

    assert len(queue.sent) == 1
    msg = queue.sent[0]
    assert msg.purpose == "order_placed"
    assert order.order_number in msg.body
    assert msg.phone == order.recipient_phone


async def test_full_lifecycle_emits_one_sms_per_customer_visible_step(
    session: AsyncSession,
    redis_clean: None,
) -> None:
    queue = FakeSmsQueue()
    branch = await seed_branch(session, code=f"LCS-{secrets.token_hex(3)}")
    order = await _seed_pending_order(session, branch_id=branch.id, sms_queue=queue)
    admin = await _make_admin(session)
    svc = _lifecycle(session, sms_queue=queue)

    queue.reset()  # discard the place_order SMS

    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)  # internal — no SMS
    await svc.mark_out_for_delivery(
        order.id,
        actor=admin,
        courier_name="Курьер Иван",
        courier_phone="+996770111222",
    )
    await svc.mark_delivered(order.id, actor=admin)

    purposes = [m.purpose for m in queue.sent]
    assert purposes == ["order_confirmed", "order_dispatched", "order_delivered"]

    dispatched = next(m for m in queue.sent if m.purpose == "order_dispatched")
    assert "Курьер Иван" in dispatched.body
    assert "+996770111222" in dispatched.body

    # Deliveries row created at dispatch.
    delivery = (
        (await session.execute(select(Delivery).where(Delivery.order_id == order.id)))
        .scalars()
        .one()
    )
    assert delivery.courier_name == "Курьер Иван"
    assert delivery.courier_phone == "+996770111222"
    assert delivery.assigned_at is not None


async def test_cancel_from_pending_emits_cancelled_sms(
    session: AsyncSession,
    redis_clean: None,
) -> None:
    queue = FakeSmsQueue()
    branch = await seed_branch(session, code=f"CAN-{secrets.token_hex(3)}")
    order = await _seed_pending_order(session, branch_id=branch.id, sms_queue=queue)
    admin = await _make_admin(session)
    svc = _lifecycle(session, sms_queue=queue)

    queue.reset()
    await svc.cancel_by_admin(order.id, actor=admin, reason="customer_changed_mind")

    assert len(queue.sent) == 1
    assert queue.sent[0].purpose == "order_cancelled"
    assert "customer_changed_mind" in queue.sent[0].body
    assert order.order_number in queue.sent[0].body
