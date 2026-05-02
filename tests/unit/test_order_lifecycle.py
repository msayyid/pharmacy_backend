"""Unit tests for ``OrderLifecycleService``.

Covers the state-transition matrix, stock side-effects on each path,
batch swap during picking, and the refund Payment-row stub.
"""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.types import uuid7
from app.domain.catalog.repositories import ProductRepository
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
from app.domain.orders.models import (
    Order,
    OrderStatus,
    Payment,
)
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderSequenceRepository,
    OrderStatusHistoryRepository,
)
from app.domain.orders.schemas import (
    PlaceOrderRequest,
)
from tests.factories.catalog import seed_category, seed_product
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)

pytestmark = pytest.mark.unit


# ─── Fixtures / helpers ─────────────────────────────────────────────────────


def _inventory(session: AsyncSession) -> InventoryService:
    return InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )


def _lifecycle(session: AsyncSession) -> OrderLifecycleService:
    return OrderLifecycleService(
        session=session,
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        batches=InventoryBatchRepository(session),
        branch_products=BranchProductRepository(session),
        movements=StockMovementRepository(session),
        inventory=_inventory(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )


def _checkout(session: AsyncSession) -> CheckoutService:
    return CheckoutService(
        carts=CartRepository(session),
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        order_sequence=OrderSequenceRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        addresses=UserAddressRepository(session),
        inventory=_inventory(session),
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


async def _make_admin(
    session: AsyncSession,
    *,
    role: str = "super_admin",
    branch_id: int | None = None,
) -> AdminUser:
    admin = AdminUser(
        email=f"admin-{secrets.token_hex(4)}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="Admin",
        last_name="Test",
        role=role,
        branch_id=branch_id,
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin


async def _place_card_order(session: AsyncSession, *, branch_id: int, qty: int = 2) -> Order:
    """Helper: seed product + place a card_online order so refund tests
    have something to work with."""
    cat = await seed_category(session, slug=f"lc-{secrets.token_hex(4)}")
    p = await seed_product(
        session,
        sku=f"LC-{secrets.token_hex(4).upper()}",
        slug=f"lc-{secrets.token_hex(4)}",
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
        batch_number=f"LC-LOT-{secrets.token_hex(3)}",
        expiry_date=date.today() + timedelta(days=365),
        quantity_received=20,
    )
    user = await _make_user(session)
    cart = await _carts(session).get_or_create(branch_id=branch_id, user=user, session_id=None)
    await _carts(session).add_item(cart=cart, product_id=p.id, quantity=qty)
    full = await _carts(session).get_with_items(cart.id)
    assert full is not None
    response = await _checkout(session).place_order(
        cart=full,
        user=user,
        payload=PlaceOrderRequest(
            delivery_method="pickup",
            payment_method="card_online",
            recipient_name="Test",
            recipient_phone="+996700000000",
        ),
        idempotency_key=f"key-{secrets.token_hex(6)}",
        body_digest=f"d-{secrets.token_hex(6)}",
    )
    # Mark as paid (admin would normally see gateway success).
    order = await OrderRepository(session).get_by_id_with_items(response.order_id)
    assert order is not None
    order.payment_status = "paid"
    await session.flush()
    return order


async def _place_cod_order(
    session: AsyncSession,
    *,
    branch_id: int,
    qty: int = 2,
) -> Order:
    cat = await seed_category(session, slug=f"lcd-{secrets.token_hex(4)}")
    p = await seed_product(
        session,
        sku=f"LCD-{secrets.token_hex(4).upper()}",
        slug=f"lcd-{secrets.token_hex(4)}",
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
        batch_number=f"LCD-LOT-{secrets.token_hex(3)}",
        expiry_date=date.today() + timedelta(days=365),
        quantity_received=20,
    )
    user = await _make_user(session)
    cart = await _carts(session).get_or_create(branch_id=branch_id, user=user, session_id=None)
    await _carts(session).add_item(cart=cart, product_id=p.id, quantity=qty)
    full = await _carts(session).get_with_items(cart.id)
    assert full is not None
    response = await _checkout(session).place_order(
        cart=full,
        user=user,
        payload=PlaceOrderRequest(
            delivery_method="pickup",
            payment_method="cash_on_delivery",
            recipient_name="Test",
            recipient_phone="+996700000000",
        ),
        idempotency_key=f"key-{secrets.token_hex(6)}",
        body_digest=f"d-{secrets.token_hex(6)}",
    )
    order = await OrderRepository(session).get_by_id_with_items(response.order_id)
    assert order is not None
    return order


# ─── State-machine matrix ───────────────────────────────────────────────────


async def test_pending_to_confirmed_succeeds(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"LF-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    updated = await svc.confirm(order.id, actor=admin)
    assert updated.status == OrderStatus.CONFIRMED.value
    assert updated.confirmed_at is not None


async def test_disallowed_transition_raises(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"LF2-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    # pending → delivered is not in ALLOWED_TRANSITIONS.
    with pytest.raises(ConflictError) as ei:
        await svc.dispatch(order_id=order.id, to_status="delivered", actor=admin)
    assert ei.value.context["code"] == "transition_not_allowed"


async def test_cancel_pending_releases_reservations(
    session: AsyncSession, redis_clean: None
) -> None:
    branch = await seed_branch(session, code=f"LF3-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id, qty=3)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    # Pre-cancel: bp.reserved_quantity == 3.
    bp_repo = BranchProductRepository(session)
    bp = await bp_repo.get(branch.id, order.items[0].product_id)
    assert bp is not None and bp.reserved_quantity == 3

    await svc.cancel_by_admin(order.id, actor=admin, reason="customer_changed_mind")

    bp = await bp_repo.get(branch.id, order.items[0].product_id)
    assert bp is not None
    assert bp.reserved_quantity == 0
    assert bp.total_quantity == 20  # untouched


async def test_cancel_out_for_delivery_restocks(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"LF4-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id, qty=3)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    # confirm → preparing → out_for_delivery
    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)
    await svc.mark_out_for_delivery(
        order.id,
        actor=admin,
        courier_name="Marat",
        courier_phone="+996700000111",
    )

    # Post-dispatch: bp.total = 17, bp.reserved = 0.
    bp_repo = BranchProductRepository(session)
    bp = await bp_repo.get(branch.id, order.items[0].product_id)
    assert bp is not None
    assert bp.total_quantity == 17
    assert bp.reserved_quantity == 0

    # Refused at door: out_for_delivery → cancelled, restock to original.
    await svc.cancel_by_admin(order.id, actor=admin, reason="customer_refused_at_door")
    bp = await bp_repo.get(branch.id, order.items[0].product_id)
    assert bp is not None
    assert bp.total_quantity == 20  # restored


async def test_mark_ready_converts_reserved_to_sold(
    session: AsyncSession, redis_clean: None
) -> None:
    branch = await seed_branch(session, code=f"LF5-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id, qty=2)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)
    await svc.mark_ready_for_pickup(order.id, actor=admin)

    bp = await BranchProductRepository(session).get(branch.id, order.items[0].product_id)
    assert bp is not None
    assert bp.total_quantity == 18
    assert bp.reserved_quantity == 0


async def test_cannot_cancel_delivered(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"LF6-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)
    await svc.mark_ready_for_pickup(order.id, actor=admin)
    await svc.mark_delivered(order.id, actor=admin)

    # delivered → cancelled is not in matrix.
    with pytest.raises(ConflictError) as ei:
        await svc.cancel_by_admin(order.id, actor=admin, reason="customer_changed_mind")
    assert ei.value.context["code"] == "transition_not_allowed"


async def test_cancel_requires_reason(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"LF7-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    with pytest.raises(ValidationError) as ei:
        await svc.dispatch(order_id=order.id, to_status="cancelled", actor=admin)
    assert ei.value.context["code"] == "reason_required"


async def test_cancel_invalid_reason(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"LF8-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    with pytest.raises(ValidationError) as ei:
        await svc.cancel_by_admin(order.id, actor=admin, reason="bogus_reason")
    assert ei.value.context["code"] == "invalid_cancel_reason"


async def test_pharmacist_cannot_refund(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"LF9-{secrets.token_hex(3)}")
    order = await _place_card_order(session, branch_id=branch.id)
    admin = await _make_admin(session)  # super_admin to walk to delivered
    svc = _lifecycle(session)
    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)
    await svc.mark_ready_for_pickup(order.id, actor=admin)
    await svc.mark_delivered(order.id, actor=admin)

    pharmacist = await _make_admin(session, role="pharmacist", branch_id=branch.id)
    with pytest.raises(PermissionDeniedError) as ei:
        await svc.refund(
            order.id,
            actor=pharmacist,
            amount=order.total,
            reason="customer_refused",
        )
    assert ei.value.context["code"] == "forbidden_role"


async def test_branch_manager_cant_act_on_other_branch(
    session: AsyncSession, redis_clean: None
) -> None:
    branch_a = await seed_branch(session, code=f"LFA-{secrets.token_hex(3)}")
    branch_b = await seed_branch(session, code=f"LFB-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch_a.id)
    bm_b = await _make_admin(session, role="branch_manager", branch_id=branch_b.id)
    svc = _lifecycle(session)
    with pytest.raises(PermissionDeniedError):
        await svc.confirm(order.id, actor=bm_b)


# ─── Refund (creates Payment row for card; status flip for COD) ─────────────


async def test_refund_card_order_creates_pending_payment(
    session: AsyncSession, redis_clean: None
) -> None:
    branch = await seed_branch(session, code=f"REF-{secrets.token_hex(3)}")
    order = await _place_card_order(session, branch_id=branch.id)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)
    await svc.mark_ready_for_pickup(order.id, actor=admin)
    await svc.mark_delivered(order.id, actor=admin)

    refunded = await svc.refund(
        order.id, actor=admin, amount=order.total, reason="customer_refused"
    )
    assert refunded.status == OrderStatus.REFUNDED.value
    assert refunded.payment_status == "refunded"

    payments = (
        (await session.execute(select(Payment).where(Payment.order_id == order.id))).scalars().all()
    )
    refund_rows = [p for p in payments if p.is_refund]
    assert len(refund_rows) == 1
    assert refund_rows[0].status == "pending"
    assert refund_rows[0].amount == order.total


async def test_refund_cod_order_only_flips_status(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"REFCOD-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)
    await svc.mark_ready_for_pickup(order.id, actor=admin)
    await svc.mark_delivered(order.id, actor=admin)

    refunded = await svc.refund(
        order.id, actor=admin, amount=order.total, reason="customer_refused"
    )
    assert refunded.status == OrderStatus.REFUNDED.value
    assert refunded.payment_status == "refunded"

    payments = (
        (await session.execute(select(Payment).where(Payment.order_id == order.id))).scalars().all()
    )
    assert payments == []  # no Payment row for COD refund


# ─── Batch swap ──────────────────────────────────────────────────────────────


async def test_swap_batch_during_picking(session: AsyncSession, redis_clean: None) -> None:
    branch = await seed_branch(session, code=f"SW-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id, qty=2)
    admin = await _make_admin(session)
    svc = _lifecycle(session)

    # Walk to preparing.
    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)

    # Add a NEW batch we can swap to.
    item = order.items[0]
    new_batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=item.product_id,
        batch_number=f"SW-NEW-{secrets.token_hex(3)}",
        expiry_date=date.today() + timedelta(days=400),
        quantity_received=10,
    )

    await svc.swap_batch(
        order_id=order.id,
        item_id=item.id,
        new_batch_id=new_batch.id,
        actor=admin,
    )
    # Old batch should now have 0 reserved (released); new batch holds them.
    new_batch_reload = await InventoryBatchRepository(session).get_by_id(new_batch.id)
    # The swap moved the reserve over.
    assert new_batch_reload is not None
    assert new_batch_reload.quantity_reserved == 2


async def test_swap_batch_rejects_different_product(
    session: AsyncSession, redis_clean: None
) -> None:
    branch = await seed_branch(session, code=f"SWX-{secrets.token_hex(3)}")
    order = await _place_cod_order(session, branch_id=branch.id, qty=1)
    admin = await _make_admin(session)
    svc = _lifecycle(session)
    await svc.confirm(order.id, actor=admin)
    await svc.start_preparing(order.id, actor=admin)

    # Seed a different product's batch.
    cat = await seed_category(session, slug=f"swx-{secrets.token_hex(3)}")
    other_p = await seed_product(
        session,
        sku=f"SWX-OTHER-{secrets.token_hex(3)}",
        slug=f"swx-other-{secrets.token_hex(3)}",
        category_id=cat.id,
    )
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=other_p.id,
        total_quantity=10,
    )
    bad_batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=other_p.id,
        batch_number=f"SWX-BAD-{secrets.token_hex(3)}",
    )

    with pytest.raises(ValidationError) as ei:
        await svc.swap_batch(
            order_id=order.id,
            item_id=order.items[0].id,
            new_batch_id=bad_batch.id,
            actor=admin,
        )
    assert ei.value.context["code"] == "batch_product_mismatch"
