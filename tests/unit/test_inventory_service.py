"""Inventory service unit-ish tests — exercise business rules with a real DB.

These hit the real DB but stay focused on service-layer behaviour
(receive/adjust/reserve/release/reconcile, 7-day hard block, sign rules,
auto-create branch_products) rather than HTTP/auth concerns.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    OutOfStockError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.types import uuid7
from app.domain.identity.models import AdminUser
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
    SupplierRepository,
)
from app.domain.inventory.schemas import (
    BatchAdjustRequest,
    BatchReceiveRequest,
    BranchProductUpdate,
)
from app.domain.inventory.services import InventoryService
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from tests.factories.catalog import seed_category, seed_product
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)

pytestmark = pytest.mark.unit


def _make_service(session: AsyncSession) -> InventoryService:
    return InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )


async def _make_actor(
    session: AsyncSession, *, suffix: str, role: str = "super_admin", branch_id: int | None = None
) -> AdminUser:
    """Persist a dummy admin so audit FK passes."""
    admin = AdminUser(
        email=f"inv-{suffix}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="Inv",
        last_name="Actor",
        role=role,
        branch_id=branch_id,
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin


async def _seed_product(session: AsyncSession, *, suffix: str) -> UUID:
    cat = await seed_category(session, slug=f"cat-svc-{suffix}")
    p = await seed_product(
        session,
        sku=f"SVC-{suffix}",
        slug=f"svc-{suffix}",
        category_id=cat.id,
    )
    return p.id


# ─── receive_batch ────────────────────────────────────────────────────────────


async def test_receive_batch_creates_batch_increments_total_writes_movement(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="recv-1")
    branch = await seed_branch(session, code="RECV-1")
    pid = await _seed_product(session, suffix="recv-1")

    payload = BatchReceiveRequest(
        product_id=pid,
        batch_number="LOT-001",
        expiry_date=date.today() + timedelta(days=365),
        quantity_received=100,
        cost_price=Decimal("50.00"),
    )
    result = await svc.receive_batch(branch_id=branch.id, payload=payload, actor=actor)

    assert result.batch.quantity_remaining == 100
    assert result.is_short_dated is False
    assert result.branch_product_pending_pricing is True

    bp = await BranchProductRepository(session).get(branch.id, pid)
    assert bp is not None
    assert bp.total_quantity == 100
    assert bp.is_available is False  # auto-created pending pricing

    movements, _ = await StockMovementRepository(session).list_paginated(
        offset=0, limit=10, branch_id=branch.id, product_id=pid
    )
    assert len(movements) == 1
    assert movements[0].movement_type == "received"
    assert movements[0].quantity_change == 100


async def test_receive_batch_within_hard_block_rejected(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="recv-blk")
    branch = await seed_branch(session, code="RECV-BLK")
    pid = await _seed_product(session, suffix="recv-blk")

    with pytest.raises(ValidationError) as ei:
        await svc.receive_batch(
            branch_id=branch.id,
            payload=BatchReceiveRequest(
                product_id=pid,
                batch_number="LOT-BLK",
                expiry_date=date.today() + timedelta(days=3),
                quantity_received=50,
                cost_price=Decimal("10"),
            ),
            actor=actor,
        )
    assert ei.value.context["code"] == "expiry_within_hard_block"


async def test_receive_override_requires_super_admin(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    branch = await seed_branch(session, code="RECV-OV")
    pid = await _seed_product(session, suffix="recv-ov")
    pharmacist = await _make_actor(
        session, suffix="recv-ov", role="pharmacist", branch_id=branch.id
    )

    with pytest.raises(PermissionDeniedError):
        await svc.receive_batch(
            branch_id=branch.id,
            payload=BatchReceiveRequest(
                product_id=pid,
                batch_number="LOT-OV",
                expiry_date=date.today() + timedelta(days=3),
                quantity_received=50,
                cost_price=Decimal("10"),
                override_short_expiry=True,
            ),
            actor=pharmacist,
        )


async def test_receive_short_dated_flag_set_for_60_day_window(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="recv-sd")
    branch = await seed_branch(session, code="RECV-SD")
    pid = await _seed_product(session, suffix="recv-sd")

    result = await svc.receive_batch(
        branch_id=branch.id,
        payload=BatchReceiveRequest(
            product_id=pid,
            batch_number="LOT-SD",
            expiry_date=date.today() + timedelta(days=45),
            quantity_received=20,
            cost_price=Decimal("10"),
        ),
        actor=actor,
    )
    assert result.is_short_dated is True


async def test_receive_same_batch_twice_conflict(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="recv-dup")
    branch = await seed_branch(session, code="RECV-DUP")
    pid = await _seed_product(session, suffix="recv-dup")
    payload = BatchReceiveRequest(
        product_id=pid,
        batch_number="LOT-DUP",
        expiry_date=date.today() + timedelta(days=180),
        quantity_received=50,
        cost_price=Decimal("10"),
    )
    await svc.receive_batch(branch_id=branch.id, payload=payload, actor=actor)
    with pytest.raises(ConflictError) as ei:
        await svc.receive_batch(branch_id=branch.id, payload=payload, actor=actor)
    assert ei.value.context["code"] == "batch_already_received"


# ─── adjust_batch ─────────────────────────────────────────────────────────────


async def test_adjust_batch_damaged_decrements_total(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="adj-dmg")
    branch = await seed_branch(session, code="ADJ-DMG")
    pid = await _seed_product(session, suffix="adj-dmg")
    await seed_branch_product(session, branch_id=branch.id, product_id=pid, total_quantity=100)
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-ADJ",
        quantity_received=100,
        quantity_remaining=100,
    )

    await svc.adjust_batch(
        batch.id,
        payload=BatchAdjustRequest(quantity_change=-5, movement_type="damaged", reason="dropped"),
        actor=actor,
    )
    await session.refresh(batch)
    assert batch.quantity_remaining == 95
    bp = await BranchProductRepository(session).get(branch.id, pid)
    assert bp is not None and bp.total_quantity == 95


async def test_adjust_below_reserved_blocked(session: AsyncSession) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="adj-res")
    branch = await seed_branch(session, code="ADJ-RES")
    pid = await _seed_product(session, suffix="adj-res")
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=pid,
        total_quantity=10,
        reserved_quantity=8,
    )
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-ADJ-RES",
        quantity_received=10,
        quantity_remaining=10,
        quantity_reserved=8,
    )
    with pytest.raises(ConflictError) as ei:
        await svc.adjust_batch(
            batch.id,
            payload=BatchAdjustRequest(quantity_change=-5, movement_type="damaged", reason="x"),
            actor=actor,
        )
    assert ei.value.context["code"] == "adjustment_below_reserved"


# ─── allocate_for_order + reserve ─────────────────────────────────────────────


async def test_allocate_for_order_fefo_split_across_batches(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    branch = await seed_branch(session, code="ALOC-1")
    pid = await _seed_product(session, suffix="aloc-1")
    today = date.today()
    earlier = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-EARLY",
        expiry_date=today + timedelta(days=60),
        quantity_received=10,
        quantity_remaining=10,
    )
    later = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-LATE",
        expiry_date=today + timedelta(days=180),
        quantity_received=20,
        quantity_remaining=20,
    )

    allocations = await svc.allocate_for_order(
        branch_id=branch.id, product_id=pid, qty=15, today=today
    )
    assert len(allocations) == 2
    assert allocations[0].batch_id == earlier.id
    assert allocations[0].quantity == 10
    assert allocations[1].batch_id == later.id
    assert allocations[1].quantity == 5


async def test_allocate_insufficient_stock_raises(session: AsyncSession) -> None:
    svc = _make_service(session)
    branch = await seed_branch(session, code="ALOC-2")
    pid = await _seed_product(session, suffix="aloc-2")
    await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-SMALL",
        quantity_received=5,
        quantity_remaining=5,
    )
    with pytest.raises(OutOfStockError):
        await svc.allocate_for_order(branch_id=branch.id, product_id=pid, qty=10)


async def test_reserve_increments_reserved_and_writes_movement(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    branch = await seed_branch(session, code="RES-1")
    pid = await _seed_product(session, suffix="res-1")
    await seed_branch_product(session, branch_id=branch.id, product_id=pid, total_quantity=20)
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-RES",
        quantity_received=20,
        quantity_remaining=20,
    )
    order_id = uuid7()

    allocations = await svc.allocate_for_order(branch_id=branch.id, product_id=pid, qty=7)
    await svc.reserve(
        branch_id=branch.id, product_id=pid, allocations=allocations, order_id=order_id
    )

    await session.refresh(batch)
    assert batch.quantity_reserved == 7
    assert batch.quantity_remaining == 20  # unchanged on reserve

    bp = await BranchProductRepository(session).get(branch.id, pid)
    assert bp is not None
    assert bp.reserved_quantity == 7
    assert bp.total_quantity == 20  # unchanged on reserve

    movs, _ = await StockMovementRepository(session).list_paginated(
        offset=0, limit=10, order_id=order_id
    )
    assert len(movs) == 1
    assert movs[0].movement_type == "reserved"
    assert movs[0].quantity_change == -7


async def test_convert_reservation_to_sold_decrements_total(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    branch = await seed_branch(session, code="SOLD-1")
    pid = await _seed_product(session, suffix="sold-1")
    await seed_branch_product(session, branch_id=branch.id, product_id=pid, total_quantity=20)
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-SOLD",
        quantity_received=20,
        quantity_remaining=20,
    )
    order_id = uuid7()

    allocations = await svc.allocate_for_order(branch_id=branch.id, product_id=pid, qty=7)
    await svc.reserve(
        branch_id=branch.id, product_id=pid, allocations=allocations, order_id=order_id
    )
    await svc.convert_reservation_to_sold(order_id)

    await session.refresh(batch)
    assert batch.quantity_remaining == 13
    assert batch.quantity_reserved == 0

    bp = await BranchProductRepository(session).get(branch.id, pid)
    assert bp is not None
    assert bp.total_quantity == 13
    assert bp.reserved_quantity == 0


async def test_release_reservations_returns_to_free_pool(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    branch = await seed_branch(session, code="REL-1")
    pid = await _seed_product(session, suffix="rel-1")
    await seed_branch_product(session, branch_id=branch.id, product_id=pid, total_quantity=20)
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-REL",
        quantity_received=20,
        quantity_remaining=20,
    )
    order_id = uuid7()

    allocations = await svc.allocate_for_order(branch_id=branch.id, product_id=pid, qty=5)
    await svc.reserve(
        branch_id=branch.id, product_id=pid, allocations=allocations, order_id=order_id
    )
    await svc.release_reservations(order_id)

    await session.refresh(batch)
    assert batch.quantity_reserved == 0
    assert batch.quantity_remaining == 20  # never decremented

    bp = await BranchProductRepository(session).get(branch.id, pid)
    assert bp is not None
    assert bp.reserved_quantity == 0
    assert bp.total_quantity == 20


# ─── reconcile_branch_product ─────────────────────────────────────────────────


async def test_reconcile_branch_product_corrects_drift(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    branch = await seed_branch(session, code="REC-1")
    pid = await _seed_product(session, suffix="rec-1")
    # Cache says 0 but batches sum to 100 — drift.
    await seed_branch_product(session, branch_id=branch.id, product_id=pid, total_quantity=0)
    await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=pid,
        batch_number="LOT-REC",
        quantity_received=100,
        quantity_remaining=100,
    )
    old, new = await svc.reconcile_branch_product(branch_id=branch.id, product_id=pid)
    assert old == 0
    assert new == 100
    bp = await BranchProductRepository(session).get(branch.id, pid)
    assert bp is not None and bp.total_quantity == 100


# ─── update_branch_product ────────────────────────────────────────────────────


async def test_update_branch_product_price_and_availability(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="bp-up")
    branch = await seed_branch(session, code="BP-UP")
    pid = await _seed_product(session, suffix="bp-up")
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=pid,
        price="0",
        is_available=False,
    )
    bp = await svc.update_branch_product(
        branch_id=branch.id,
        product_id=pid,
        payload=BranchProductUpdate(
            price=Decimal("125.50"), is_available=True, low_stock_threshold=20
        ),
        actor=actor,
    )
    assert bp.price == Decimal("125.50")
    assert bp.is_available is True
    assert bp.low_stock_threshold == 20


# ─── error: updating non-existent bp ─────────────────────────────────────────


async def test_update_branch_product_not_found(session: AsyncSession) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="bp-404")
    branch = await seed_branch(session, code="BP-404")
    pid = await _seed_product(session, suffix="bp-404")
    with pytest.raises(NotFoundError):
        await svc.update_branch_product(
            branch_id=branch.id,
            product_id=pid,
            payload=BranchProductUpdate(price=Decimal("50")),
            actor=actor,
        )
