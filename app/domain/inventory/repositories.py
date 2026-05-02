"""Inventory domain — repositories.

One class per aggregate root:

* :class:`BranchRepository`        — Phase 4 minimum + active listing.
* :class:`SupplierRepository`      — get/list/add.
* :class:`BranchProductRepository` — composite-PK CRUD, low-stock query,
                                     row-locking for cached-aggregate
                                     updates.
* :class:`InventoryBatchRepository`— FEFO scan with ``FOR UPDATE SKIP
                                     LOCKED``, near-expiry / expired
                                     reports, batch-by-id.
* :class:`StockMovementRepository` — append-only writes + filtered reads.

Repositories are thin: queries shaped for intent, no business rules,
no commits, no Pydantic. Services own transactions.

Reference: BACKEND_BLUEPRINT.md §11; PHARMACY_BLUEPRINT_2.md §6, §11.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.models import (
    Branch,
    BranchProduct,
    InventoryBatch,
    StockMovement,
    Supplier,
)


class BranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, branch_id: int) -> Branch | None:
        stmt = select(Branch).where(Branch.id == branch_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, code: str) -> Branch | None:
        stmt = select(Branch).where(Branch.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active(self) -> Sequence[Branch]:
        stmt = select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)
        return (await self.session.execute(stmt)).scalars().all()

    async def list_paginated(self, *, offset: int, limit: int) -> tuple[Sequence[Branch], int]:
        base = select(Branch)
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = base.order_by(Branch.name).offset(offset).limit(limit)
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def add(self, branch: Branch) -> None:
        self.session.add(branch)
        await self.session.flush()


# ─── Suppliers ────────────────────────────────────────────────────────────────


class SupplierRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, supplier_id: int) -> Supplier | None:
        stmt = select(Supplier).where(Supplier.id == supplier_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, name: str) -> Supplier | None:
        stmt = select(Supplier).where(Supplier.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self, *, offset: int, limit: int, q: str | None = None
    ) -> tuple[Sequence[Supplier], int]:
        base: Select[tuple[Supplier]] = select(Supplier)
        if q:
            base = base.where(Supplier.name.ilike(f"%{q}%"))
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = base.order_by(Supplier.name).offset(offset).limit(limit)
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def add(self, supplier: Supplier) -> None:
        self.session.add(supplier)
        await self.session.flush()
        await self.session.refresh(supplier)


# ─── Branch products (composite PK) ──────────────────────────────────────────


class BranchProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, branch_id: int, product_id: UUID) -> BranchProduct | None:
        stmt = select(BranchProduct).where(
            BranchProduct.branch_id == branch_id,
            BranchProduct.product_id == product_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_update(self, branch_id: int, product_id: UUID) -> BranchProduct | None:
        """Row-locking variant. Used by reservation flows so the
        cached-aggregate update is serialised against concurrent reservers
        for the same (branch, product).
        """
        stmt = (
            select(BranchProduct)
            .where(
                BranchProduct.branch_id == branch_id,
                BranchProduct.product_id == product_id,
            )
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, bp: BranchProduct) -> None:
        self.session.add(bp)
        await self.session.flush()

    async def list_paginated(
        self,
        *,
        branch_id: int,
        offset: int,
        limit: int,
        low_stock: bool = False,
        only_available: bool = False,
    ) -> tuple[Sequence[BranchProduct], int]:
        base: Select[tuple[BranchProduct]] = select(BranchProduct).where(
            BranchProduct.branch_id == branch_id
        )
        if low_stock:
            base = base.where(BranchProduct.total_quantity <= BranchProduct.low_stock_threshold)
        if only_available:
            base = base.where(BranchProduct.is_available.is_(True))
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = base.order_by(BranchProduct.product_id).offset(offset).limit(limit)
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def list_low_stock(self, *, branch_id: int) -> Sequence[BranchProduct]:
        """All branch_products with total_quantity ≤ threshold."""
        stmt = (
            select(BranchProduct)
            .where(
                BranchProduct.branch_id == branch_id,
                BranchProduct.total_quantity <= BranchProduct.low_stock_threshold,
            )
            .order_by(BranchProduct.total_quantity - BranchProduct.low_stock_threshold)
        )
        return (await self.session.execute(stmt)).scalars().all()


# ─── Inventory batches ────────────────────────────────────────────────────────


class InventoryBatchRepository:
    """Source-of-truth stock store. FEFO query lives here."""

    HARD_BLOCK_DAYS = 7

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, batch_id: int) -> InventoryBatch | None:
        stmt = select(InventoryBatch).where(InventoryBatch.id == batch_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_natural_key(
        self, *, branch_id: int, product_id: UUID, batch_number: str
    ) -> InventoryBatch | None:
        stmt = select(InventoryBatch).where(
            InventoryBatch.branch_id == branch_id,
            InventoryBatch.product_id == product_id,
            InventoryBatch.batch_number == batch_number,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, batch: InventoryBatch) -> None:
        self.session.add(batch)
        await self.session.flush()
        await self.session.refresh(batch)

    async def list_for_fefo_locked(
        self, *, branch_id: int, product_id: UUID, today: date
    ) -> Sequence[InventoryBatch]:
        """Non-expired sellable batches in FEFO order under
        ``FOR UPDATE SKIP LOCKED``.

        Filter logic:

        * ``expiry_date > today + HARD_BLOCK_DAYS`` — enforces the 7-day
          hard block (PRODUCT §10.3) at the query layer so no code path
          can accidentally allocate from blocked stock.
        * ``quantity_remaining > quantity_reserved`` — only batches with
          *unreserved* stock are sellable. Per-batch reservation
          tracking is what prevents oversell-per-batch under concurrent
          reservers (DECISION_LOG 2026-05-02 — deviation from §11.4).
        """
        cutoff = today + timedelta(days=self.HARD_BLOCK_DAYS)
        stmt = (
            select(InventoryBatch)
            .where(
                InventoryBatch.branch_id == branch_id,
                InventoryBatch.product_id == product_id,
                InventoryBatch.quantity_remaining > InventoryBatch.quantity_reserved,
                InventoryBatch.expiry_date > cutoff,
            )
            .order_by(
                InventoryBatch.expiry_date.asc(),
                InventoryBatch.received_at.asc(),
            )
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_for_branch_product(
        self, *, branch_id: int, product_id: UUID
    ) -> Sequence[InventoryBatch]:
        stmt = (
            select(InventoryBatch)
            .where(
                InventoryBatch.branch_id == branch_id,
                InventoryBatch.product_id == product_id,
            )
            .order_by(InventoryBatch.expiry_date.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_near_expiry(
        self, *, branch_id: int, today: date, days: int
    ) -> Sequence[InventoryBatch]:
        upper = today + timedelta(days=days)
        stmt = (
            select(InventoryBatch)
            .where(
                InventoryBatch.branch_id == branch_id,
                InventoryBatch.quantity_remaining > 0,
                InventoryBatch.expiry_date > today,
                InventoryBatch.expiry_date <= upper,
            )
            .order_by(InventoryBatch.expiry_date.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_expired(self, *, branch_id: int, today: date) -> Sequence[InventoryBatch]:
        stmt = (
            select(InventoryBatch)
            .where(
                InventoryBatch.branch_id == branch_id,
                InventoryBatch.quantity_remaining > 0,
                InventoryBatch.expiry_date <= today,
            )
            .order_by(InventoryBatch.expiry_date.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def sum_remaining_non_expired(
        self, *, branch_id: int, product_id: UUID, today: date
    ) -> int:
        """Recompute the cached ``branch_products.total_quantity`` source
        of truth. Used by ``reconcile_branch_product``.
        """
        cutoff = today + timedelta(days=self.HARD_BLOCK_DAYS)
        stmt = select(func.coalesce(func.sum(InventoryBatch.quantity_remaining), 0)).where(
            InventoryBatch.branch_id == branch_id,
            InventoryBatch.product_id == product_id,
            InventoryBatch.expiry_date > cutoff,
        )
        return int((await self.session.execute(stmt)).scalar_one())


# ─── Stock movements (append-only) ───────────────────────────────────────────


class StockMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, movement: StockMovement) -> None:
        self.session.add(movement)
        await self.session.flush()

    async def list_paginated(
        self,
        *,
        offset: int,
        limit: int,
        branch_id: int | None = None,
        product_id: UUID | None = None,
        movement_type: str | None = None,
        admin_user_id: int | None = None,
        order_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[Sequence[StockMovement], int]:
        base: Select[tuple[StockMovement]] = select(StockMovement)
        if branch_id is not None:
            base = base.where(StockMovement.branch_id == branch_id)
        if product_id is not None:
            base = base.where(StockMovement.product_id == product_id)
        if movement_type is not None:
            base = base.where(StockMovement.movement_type == movement_type)
        if admin_user_id is not None:
            base = base.where(StockMovement.admin_user_id == admin_user_id)
        if order_id is not None:
            base = base.where(StockMovement.order_id == order_id)
        if date_from is not None:
            base = base.where(StockMovement.created_at >= date_from)
        if date_to is not None:
            base = base.where(StockMovement.created_at <= date_to)
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = (
            base.order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def list_for_order(self, order_id: UUID) -> Sequence[StockMovement]:
        stmt = (
            select(StockMovement)
            .where(StockMovement.order_id == order_id)
            .order_by(StockMovement.created_at.asc(), StockMovement.id.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()
