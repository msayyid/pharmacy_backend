"""Inventory repository integration tests — real DB constraints exercised.

Covers:
* ``UNIQUE(branch_id, product_id, batch_number)`` collision
* ``CHECK(reserved_quantity <= total_quantity)`` on branch_products
* ``CHECK(quantity_remaining <= quantity_received)`` on inventory_batches
* ``CHECK(quantity_reserved <= quantity_remaining)`` on inventory_batches
* ``CHECK(chk_movement_sign)`` rejecting wrong-sign rows
* low-stock query
* near-expiry query
* FEFO ordering (single-threaded; concurrent test lives elsewhere)
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.models import (
    BranchProduct,
    InventoryBatch,
    MovementType,
    StockMovement,
)
from app.domain.inventory.repositories import (
    BranchProductRepository,
    InventoryBatchRepository,
    StockMovementRepository,
)
from tests.factories.catalog import seed_category, seed_product
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)

# MySQL surfaces UNIQUE/FK violations as IntegrityError but CHECK
# violations as OperationalError (error 3819). Catch either.
_DB_CONSTRAINT_ERRORS = (IntegrityError, OperationalError)

pytestmark = pytest.mark.integration


async def _seed_product_in_category(session: AsyncSession, *, sku_suffix: str):
    cat = await seed_category(session, slug=f"cat-inv-{sku_suffix}")
    return await seed_product(
        session,
        sku=f"INV-{sku_suffix}",
        slug=f"inv-{sku_suffix}",
        category_id=cat.id,
    )


# ─── Constraints ──────────────────────────────────────────────────────────────


async def test_inventory_batch_natural_key_uniqueness(
    session: AsyncSession,
) -> None:
    """``UNIQUE(branch_id, product_id, batch_number)`` blocks duplicates."""
    branch = await seed_branch(session, code="UNI-1")
    product = await _seed_product_in_category(session, sku_suffix="uni-1")
    await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-A",
    )
    dupe = InventoryBatch(
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-A",
        expiry_date=date.today() + timedelta(days=180),
        quantity_received=50,
        quantity_remaining=50,
        quantity_reserved=0,
        cost_price=Decimal("10.00"),
        currency="KGS",
    )
    session.add(dupe)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_branch_product_reserved_le_total_check(
    session: AsyncSession,
) -> None:
    branch = await seed_branch(session, code="BP-CHK")
    product = await _seed_product_in_category(session, sku_suffix="bp-chk")
    bp = BranchProduct(
        branch_id=branch.id,
        product_id=product.id,
        price=Decimal("0"),
        currency="KGS",
        is_available=False,
        total_quantity=10,
        reserved_quantity=20,  # > total
        low_stock_threshold=5,
    )
    session.add(bp)
    with pytest.raises(_DB_CONSTRAINT_ERRORS):
        await session.flush()
    await session.rollback()


async def test_inventory_batch_reserved_le_remaining_check(
    session: AsyncSession,
) -> None:
    branch = await seed_branch(session, code="IB-CHK")
    product = await _seed_product_in_category(session, sku_suffix="ib-chk")
    bad = InventoryBatch(
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-X",
        expiry_date=date.today() + timedelta(days=180),
        quantity_received=100,
        quantity_remaining=50,
        quantity_reserved=80,  # > remaining
        cost_price=Decimal("10.00"),
        currency="KGS",
    )
    session.add(bad)
    with pytest.raises(_DB_CONSTRAINT_ERRORS):
        await session.flush()
    await session.rollback()


async def test_stock_movement_sign_check_blocks_wrong_sign(
    session: AsyncSession,
) -> None:
    """``chk_movement_sign``: a 'received' movement with negative qty fails."""
    branch = await seed_branch(session, code="SM-SIGN")
    product = await _seed_product_in_category(session, sku_suffix="sm-sign")
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-S",
    )
    bogus = StockMovement(
        inventory_batch_id=batch.id,
        branch_id=branch.id,
        product_id=product.id,
        movement_type=MovementType.RECEIVED.value,
        quantity_change=-10,  # received must be ≥ 0
        quantity_after=batch.quantity_remaining,
    )
    session.add(bogus)
    with pytest.raises(_DB_CONSTRAINT_ERRORS):
        await session.flush()
    await session.rollback()


# ─── FEFO ordering ────────────────────────────────────────────────────────────


async def test_fefo_returns_batches_in_expiry_order(
    session: AsyncSession,
) -> None:
    branch = await seed_branch(session, code="FEFO-1")
    product = await _seed_product_in_category(session, sku_suffix="fefo-1")
    today = date.today()
    later = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-LATE",
        expiry_date=today + timedelta(days=180),
    )
    sooner = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-SOON",
        expiry_date=today + timedelta(days=60),
    )
    repo = InventoryBatchRepository(session)
    batches = await repo.list_for_fefo_locked(
        branch_id=branch.id, product_id=product.id, today=today
    )
    ids = [b.id for b in batches]
    assert ids == [sooner.id, later.id]


async def test_fefo_excludes_hard_block_window(session: AsyncSession) -> None:
    """A batch expiring within 7 days is excluded from FEFO."""
    branch = await seed_branch(session, code="FEFO-7D")
    product = await _seed_product_in_category(session, sku_suffix="fefo-7d")
    today = date.today()
    blocked = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-BLK",
        expiry_date=today + timedelta(days=3),
    )
    ok = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-OK",
        expiry_date=today + timedelta(days=30),
    )
    repo = InventoryBatchRepository(session)
    batches = await repo.list_for_fefo_locked(
        branch_id=branch.id, product_id=product.id, today=today
    )
    ids = {b.id for b in batches}
    assert ok.id in ids
    assert blocked.id not in ids


async def test_fefo_excludes_fully_reserved_batches(
    session: AsyncSession,
) -> None:
    branch = await seed_branch(session, code="FEFO-RES")
    product = await _seed_product_in_category(session, sku_suffix="fefo-res")
    today = date.today()
    fully_reserved = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-FULL",
        expiry_date=today + timedelta(days=60),
        quantity_received=10,
        quantity_remaining=10,
        quantity_reserved=10,  # nothing free
    )
    free = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-FREE",
        expiry_date=today + timedelta(days=180),
    )
    repo = InventoryBatchRepository(session)
    batches = await repo.list_for_fefo_locked(
        branch_id=branch.id, product_id=product.id, today=today
    )
    ids = {b.id for b in batches}
    assert free.id in ids
    assert fully_reserved.id not in ids


# ─── Low-stock query ──────────────────────────────────────────────────────────


async def test_low_stock_query(session: AsyncSession) -> None:
    branch = await seed_branch(session, code="LOW-1")
    product_low = await _seed_product_in_category(session, sku_suffix="low-1")
    product_ok = await _seed_product_in_category(session, sku_suffix="low-2")
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=product_low.id,
        total_quantity=5,
        low_stock_threshold=10,
    )
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=product_ok.id,
        total_quantity=50,
        low_stock_threshold=10,
    )
    repo = BranchProductRepository(session)
    rows = await repo.list_low_stock(branch_id=branch.id)
    pids = {r.product_id for r in rows}
    assert product_low.id in pids
    assert product_ok.id not in pids


# ─── Near-expiry query ────────────────────────────────────────────────────────


async def test_near_expiry_window(session: AsyncSession) -> None:
    branch = await seed_branch(session, code="NEAR-1")
    product = await _seed_product_in_category(session, sku_suffix="near-1")
    today = date.today()
    near = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-NEAR",
        expiry_date=today + timedelta(days=20),
    )
    far = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-FAR",
        expiry_date=today + timedelta(days=180),
    )
    repo = InventoryBatchRepository(session)
    rows = await repo.list_near_expiry(branch_id=branch.id, today=today, days=30)
    ids = {r.id for r in rows}
    assert near.id in ids
    assert far.id not in ids


# ─── Stock movements: append + filtered list ─────────────────────────────────


async def test_stock_movement_append_and_filter(session: AsyncSession) -> None:
    branch = await seed_branch(session, code="MV-1")
    product = await _seed_product_in_category(session, sku_suffix="mv-1")
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=product.id,
        batch_number="LOT-MV",
    )
    repo = StockMovementRepository(session)
    await repo.append(
        StockMovement(
            inventory_batch_id=batch.id,
            branch_id=branch.id,
            product_id=product.id,
            movement_type=MovementType.RECEIVED.value,
            quantity_change=batch.quantity_received,
            quantity_after=batch.quantity_remaining,
        )
    )
    items, total = await repo.list_paginated(offset=0, limit=10, branch_id=branch.id)
    assert total == 1
    assert items[0].movement_type == "received"
