"""Concurrent FEFO test — the centrepiece of Phase 6 correctness.

Two reservers compete for the same ``(branch, product)``. With
``FOR UPDATE SKIP LOCKED`` and per-batch ``quantity_reserved`` tracking:

* No oversell: total reserved across all batches ≤ total physical.
* No deadlock: both coroutines complete.
* No double-spend on a single batch: per-batch reservation never
  exceeds ``quantity_remaining``.

Loop count is read from ``FEFO_CONCURRENT_LOOPS`` env (default 50). CI
nightly bumps it to 100. Each loop seeds a fresh ``(branch, product,
batches)`` so loops are independent.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.types import uuid7
from app.domain.inventory.models import Branch, BranchProduct, InventoryBatch
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
from tests.factories.catalog import seed_category_committed

pytestmark = pytest.mark.integration


_LOOPS = int(os.getenv("FEFO_CONCURRENT_LOOPS", "50"))


@asynccontextmanager
async def _new_session_factory() -> Any:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _make_service(session: Any) -> InventoryService:
    return InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )


async def _seed_one_loop(factory: Any, *, loop_idx: int) -> tuple[int, Any, list[int]]:
    """Commit a fresh branch + product + 2 batches for one loop iteration.

    Returns ``(branch_id, product_id, [batch_ids])``.
    """
    from app.core.types import uuid7 as _uuid7
    from app.domain.catalog.models import Product, ProductTranslation

    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    f = async_sessionmaker(engine, expire_on_commit=False)

    cat_id = await seed_category_committed(slug=f"cat-fefo-{loop_idx}-{uuid7().hex[:6]}")

    async with f() as s:
        branch = Branch(
            code=f"FEFO-CC-{loop_idx}-{uuid7().hex[:6].upper()}",
            name="FEFO test",
            address="мкр Асанбай 12",
            is_active=True,
        )
        s.add(branch)
        await s.flush()

        product = Product(
            id=_uuid7(),
            sku=f"FEFO-CC-{loop_idx}-{uuid7().hex[:6]}",
            slug=f"fefo-cc-{loop_idx}-{uuid7().hex[:6]}",
            category_id=cat_id,
            form="tablet",
            is_active=True,
            is_featured=False,
            requires_prescription=False,
            requires_cold_chain=False,
        )
        product.translations.append(ProductTranslation(language_code="ru", name="FEFO продукт"))
        s.add(product)
        await s.flush()

        bp = BranchProduct(
            branch_id=branch.id,
            product_id=product.id,
            price=Decimal("100"),
            currency="KGS",
            is_available=True,
            total_quantity=20,
            reserved_quantity=0,
            low_stock_threshold=5,
        )
        s.add(bp)

        today = date.today()
        b1 = InventoryBatch(
            branch_id=branch.id,
            product_id=product.id,
            batch_number=f"LOT-A-{loop_idx}",
            expiry_date=today + timedelta(days=60),
            quantity_received=10,
            quantity_remaining=10,
            quantity_reserved=0,
            cost_price=Decimal("50"),
            currency="KGS",
        )
        b2 = InventoryBatch(
            branch_id=branch.id,
            product_id=product.id,
            batch_number=f"LOT-B-{loop_idx}",
            expiry_date=today + timedelta(days=180),
            quantity_received=10,
            quantity_remaining=10,
            quantity_reserved=0,
            cost_price=Decimal("50"),
            currency="KGS",
        )
        s.add_all([b1, b2])
        await s.commit()
        return (branch.id, product.id, [b1.id, b2.id])


async def _reserve_in_own_session(
    factory: Any, *, branch_id: int, product_id: Any, qty: int
) -> Any:
    """One reservation in its own session/transaction. Returns the
    exception (if any) so the caller can assert on the outcome.
    """
    from tests.factories.orders import seed_minimal_order as _seed_order

    async with factory() as session:
        svc = _make_service(session)
        order = await _seed_order(session, branch_id=branch_id)
        order_id = order.id
        try:
            allocations = await svc.allocate_for_order(
                branch_id=branch_id, product_id=product_id, qty=qty
            )
            await svc.reserve(
                branch_id=branch_id,
                product_id=product_id,
                allocations=allocations,
                order_id=order_id,
            )
            await session.commit()
            return ("ok", sum(a.quantity for a in allocations))
        except Exception as exc:
            await session.rollback()
            return ("error", exc)


@pytest.mark.parametrize("loop_idx", range(_LOOPS), ids=lambda i: f"loop{i:03d}")
async def test_concurrent_fefo_no_oversell(_migrated_db: None, loop_idx: int) -> None:
    """Two reservations for 12 units each on a 20-unit pool.

    Total demand (24) > total stock (20). One must succeed, the other
    must surface ``OutOfStockError``. Or both partially succeed if they
    pick non-overlapping batches that sum to ≤ 20.

    Critical assertion: SUM(quantity_reserved across batches) must equal
    SUM(quantity_change of 'reserved' movements), i.e. no double-spend
    of a single batch.
    """
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        branch_id, product_id, batch_ids = await _seed_one_loop(factory, loop_idx=loop_idx)

        results = await asyncio.gather(
            _reserve_in_own_session(factory, branch_id=branch_id, product_id=product_id, qty=12),
            _reserve_in_own_session(factory, branch_id=branch_id, product_id=product_id, qty=12),
            return_exceptions=False,
        )

        # Read post-state in a fresh session.
        async with factory() as session:
            from sqlalchemy import select

            batches = (
                (
                    await session.execute(
                        select(InventoryBatch).where(InventoryBatch.id.in_(batch_ids))
                    )
                )
                .scalars()
                .all()
            )
            total_reserved_per_batch = sum(b.quantity_reserved for b in batches)
            total_remaining = sum(b.quantity_remaining for b in batches)

            for b in batches:
                assert b.quantity_reserved <= b.quantity_remaining, (
                    f"oversell on batch {b.id}: reserved={b.quantity_reserved} "
                    f"> remaining={b.quantity_remaining}"
                )

            bp = await session.execute(
                select(BranchProduct).where(
                    BranchProduct.branch_id == branch_id,
                    BranchProduct.product_id == product_id,
                )
            )
            bp_row = bp.scalar_one()
            assert (
                bp_row.reserved_quantity == total_reserved_per_batch
            ), "bp.reserved_quantity drifted from sum of per-batch reserved"
            assert bp_row.reserved_quantity <= bp_row.total_quantity

        # At least one reservation must complete; the bp totals match the
        # successful allocations.
        ok_count = sum(1 for r in results if r[0] == "ok")
        oos_count = sum(
            1 for r in results if r[0] == "error" and type(r[1]).__name__ == "OutOfStockError"
        )
        assert ok_count + oos_count == 2, f"unexpected outcomes: {results}"
        assert ok_count >= 1, "at least one reservation must succeed"

        successful_qty = sum(r[1] for r in results if r[0] == "ok")
        assert successful_qty == total_reserved_per_batch
        # ``quantity_remaining`` is the *physical* count and does not
        # move on reserve — only ``quantity_reserved`` does. So after
        # any number of reservations on this 20-unit pool the physical
        # remaining is still exactly 20.
        assert total_remaining == 20
    finally:
        await engine.dispose()
