"""Inventory service — receive, adjust, FEFO allocate, reserve, lifecycle.

The single non-negotiable invariant: **every quantity change to a batch
writes a paired ``stock_movements`` row, and updates the cached aggregates
on ``branch_products``, in the same transaction.**

Stock-truth model used here (see DECISION_LOG 2026-05-02):

* ``inventory_batches.quantity_remaining`` = full physical stock for the
  batch (held + free).
* ``inventory_batches.quantity_reserved`` = held by pending/confirmed/
  preparing orders. ``quantity_remaining - quantity_reserved`` is what
  FEFO can allocate to a new order.
* ``branch_products.total_quantity`` = SUM(``quantity_remaining`` for
  non-expired batches with expiry > today + 7d).
* ``branch_products.reserved_quantity`` = SUM(``quantity_reserved``).
* ``available = total_quantity - reserved_quantity`` (PRODUCT §10.1).

Phase 8 will call ``allocate_for_order`` + ``reserve`` from inside the
place-order transaction. ``convert_reservation_to_sold`` runs on
``preparing → ready/dispatch``. ``release_reservations`` runs on
pre-dispatch cancel. ``release_pending_orders`` is the worker target
(Phase 11 schedules it; the service implementation lives here now).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    OutOfStockError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.time import utcnow
from app.domain.identity.models import AdminUser
from app.domain.inventory.models import (
    BranchProduct,
    InventoryBatch,
    MovementType,
    StockMovement,
)
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
    SupplierRepository,
)
from app.domain.inventory.schemas import (
    BatchAdjustRequest,
    BatchAllocation,
    BatchReceiveRequest,
    BatchReceiveResponse,
    BranchProductUpdate,
)
from app.domain.ops.services import AdminAuditLogService

# 60-day soft-warn threshold for receiving (PRODUCT §10.5).
SHORT_DATED_DAYS = 60
HARD_BLOCK_DAYS = InventoryBatchRepository.HARD_BLOCK_DAYS


class InventoryService:
    """Inventory aggregate root service. Phase 6 + Phase 8 call paths."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        branches: BranchRepository,
        suppliers: SupplierRepository,
        branch_products: BranchProductRepository,
        batches: InventoryBatchRepository,
        movements: StockMovementRepository,
        audit: AdminAuditLogService,
    ) -> None:
        self.session = session
        self.branches = branches
        self.suppliers = suppliers
        self.branch_products = branch_products
        self.batches = batches
        self.movements = movements
        self.audit = audit

    # ─── Receiving ──────────────────────────────────────────────────────────

    async def receive_batch(
        self,
        *,
        branch_id: int,
        payload: BatchReceiveRequest,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
        today: date | None = None,
    ) -> BatchReceiveResponse:
        """Create a new batch and update the cached aggregate.

        Hard rule: ``expiry_date > today + 7 days`` unless
        ``override_short_expiry=True`` AND the actor is super_admin
        (PRODUCT §10.5 hard block; rare receiving error).
        """
        today = today or utcnow().date()
        branch = await self.branches.get_by_id(branch_id)
        if branch is None:
            raise NotFoundError(code="branch_not_found", branch_id=branch_id)

        # Hard-block check.
        cutoff = today + timedelta(days=HARD_BLOCK_DAYS)
        if payload.expiry_date <= cutoff:
            if not payload.override_short_expiry:
                raise ValidationError(
                    code="expiry_within_hard_block",
                    expiry_date=payload.expiry_date.isoformat(),
                    hard_block_days=HARD_BLOCK_DAYS,
                )
            if actor.role != "super_admin":
                raise PermissionDeniedError(
                    code="override_requires_super_admin",
                    role=actor.role,
                )

        # Optional supplier ref check.
        if payload.supplier_id is not None:
            supplier = await self.suppliers.get_by_id(payload.supplier_id)
            if supplier is None:
                raise ValidationError(code="supplier_not_found", supplier_id=payload.supplier_id)

        # Same-batch-twice → 409.
        if (
            await self.batches.get_by_natural_key(
                branch_id=branch_id,
                product_id=payload.product_id,
                batch_number=payload.batch_number,
            )
        ) is not None:
            raise ConflictError(
                code="batch_already_received",
                batch_number=payload.batch_number,
            )

        # branch_products row: lazy-create at price=0, is_available=False
        # ("pending pricing" — admin sets price before storefront shows it).
        # See DECISION_LOG 2026-05-02 — branch_products auto-create.
        bp = await self.branch_products.get_for_update(branch_id, payload.product_id)
        pending_pricing = False
        if bp is None:
            bp = BranchProduct(
                branch_id=branch_id,
                product_id=payload.product_id,
                price=Decimal("0"),
                currency=payload.currency,
                is_available=False,
                total_quantity=0,
                reserved_quantity=0,
                low_stock_threshold=10,
            )
            await self.branch_products.add(bp)
            pending_pricing = True
        elif bp.price == 0 and not bp.is_available:
            pending_pricing = True

        batch = InventoryBatch(
            branch_id=branch_id,
            product_id=payload.product_id,
            supplier_id=payload.supplier_id,
            batch_number=payload.batch_number,
            expiry_date=payload.expiry_date,
            manufacture_date=payload.manufacture_date,
            quantity_received=payload.quantity_received,
            quantity_remaining=payload.quantity_received,
            quantity_reserved=0,
            cost_price=payload.cost_price,
            currency=payload.currency,
        )
        try:
            await self.batches.add(batch)
        except IntegrityError as e:
            # Race: a concurrent receive of the same natural key.
            await self.session.rollback()
            raise ConflictError(
                code="batch_already_received",
                batch_number=payload.batch_number,
            ) from e

        bp.total_quantity += payload.quantity_received

        await self.movements.append(
            StockMovement(
                inventory_batch_id=batch.id,
                branch_id=branch_id,
                product_id=payload.product_id,
                movement_type=MovementType.RECEIVED.value,
                quantity_change=payload.quantity_received,
                quantity_after=batch.quantity_remaining,
                admin_user_id=actor.id,
                reason=None,
            )
        )

        await self.audit.record(
            admin_user_id=actor.id,
            action="receive",
            entity_type="inventory_batch",
            entity_id=batch.id,
            after=_batch_snapshot(batch),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        is_short_dated = payload.expiry_date <= today + timedelta(days=SHORT_DATED_DAYS)

        return BatchReceiveResponse.model_validate(
            {
                "batch": batch,
                "is_short_dated": is_short_dated,
                "branch_product_pending_pricing": pending_pricing,
            }
        )

    # ─── Adjust (manual correction / damage / write-off) ───────────────────

    async def adjust_batch(
        self,
        batch_id: int,
        *,
        payload: BatchAdjustRequest,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> InventoryBatch:
        """Apply a signed quantity_change to a batch with a reason.

        Writes either a ``damaged`` or ``adjusted`` movement. ``damaged``
        always negative; ``adjusted`` signed. Cannot reduce below
        ``quantity_reserved`` — held stock cannot be written off until
        the holding orders are released.
        """
        batch = await self.batches.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError(code="batch_not_found", batch_id=batch_id)

        if payload.movement_type == "damaged" and payload.quantity_change >= 0:
            raise ValidationError(
                code="damaged_must_be_negative",
                quantity_change=payload.quantity_change,
            )

        new_remaining = batch.quantity_remaining + payload.quantity_change
        if new_remaining < 0:
            raise ValidationError(
                code="adjustment_would_underflow",
                quantity_remaining=batch.quantity_remaining,
                quantity_change=payload.quantity_change,
            )
        if new_remaining > batch.quantity_received:
            raise ValidationError(
                code="adjustment_above_received",
                quantity_received=batch.quantity_received,
                new_remaining=new_remaining,
            )
        if new_remaining < batch.quantity_reserved:
            raise ConflictError(
                code="adjustment_below_reserved",
                quantity_reserved=batch.quantity_reserved,
                new_remaining=new_remaining,
            )

        before = _batch_snapshot(batch)
        batch.quantity_remaining = new_remaining

        bp = await self.branch_products.get_for_update(batch.branch_id, batch.product_id)
        if bp is None:
            raise NotFoundError(code="branch_product_not_found")
        bp.total_quantity += payload.quantity_change

        await self.movements.append(
            StockMovement(
                inventory_batch_id=batch.id,
                branch_id=batch.branch_id,
                product_id=batch.product_id,
                movement_type=payload.movement_type,
                quantity_change=payload.quantity_change,
                quantity_after=batch.quantity_remaining,
                admin_user_id=actor.id,
                reason=payload.reason,
            )
        )

        await self.audit.record(
            admin_user_id=actor.id,
            action="adjust",
            entity_type="inventory_batch",
            entity_id=batch.id,
            before=before,
            after=_batch_snapshot(batch),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return batch

    # ─── FEFO allocation + reservation lifecycle ───────────────────────────

    async def allocate_for_order(
        self,
        *,
        branch_id: int,
        product_id: UUID,
        qty: int,
        today: date | None = None,
    ) -> list[BatchAllocation]:
        """FEFO: lock candidate batches, plan the per-batch split.

        **Locks but does not mutate.** Caller must invoke ``reserve``
        next, in the same transaction, to make the locks productive.
        Locks persist until ``commit``, so concurrent reservers see the
        rows as locked and pick non-overlapping batches via
        ``SKIP LOCKED``.

        Raises :class:`OutOfStockError` if the unreserved-and-non-expired
        sum is below ``qty``.
        """
        if qty <= 0:
            raise ValidationError(code="qty_must_be_positive", qty=qty)
        today = today or utcnow().date()

        batches = await self.batches.list_for_fefo_locked(
            branch_id=branch_id, product_id=product_id, today=today
        )
        allocations: list[BatchAllocation] = []
        qty_left = qty
        for batch in batches:
            if qty_left <= 0:
                break
            available_in_batch = batch.quantity_remaining - batch.quantity_reserved
            if available_in_batch <= 0:
                continue
            take = min(qty_left, available_in_batch)
            allocations.append(
                BatchAllocation(
                    batch_id=batch.id,
                    batch_number=batch.batch_number,
                    expiry_date=batch.expiry_date,
                    quantity=take,
                )
            )
            qty_left -= take

        if qty_left > 0:
            raise OutOfStockError(
                code="insufficient_stock",
                branch_id=branch_id,
                product_id=str(product_id),
                qty_requested=qty,
                qty_short=qty_left,
            )
        return allocations

    async def reserve(
        self,
        *,
        branch_id: int,
        product_id: UUID,
        allocations: Sequence[BatchAllocation],
        order_id: UUID,
    ) -> None:
        """Apply FEFO allocations: increment ``quantity_reserved`` on
        each batch, write ``reserved`` movements, bump
        ``branch_products.reserved_quantity``.

        Must run in the same transaction as the preceding
        :meth:`allocate_for_order`. Does not change
        ``quantity_remaining`` or ``branch_products.total_quantity`` —
        those move at sale time (``convert_reservation_to_sold``).
        """
        if not allocations:
            return
        total = 0
        for alloc in allocations:
            batch = await self.batches.get_by_id(alloc.batch_id)
            if batch is None:
                raise NotFoundError(code="batch_not_found", batch_id=alloc.batch_id)
            new_reserved = batch.quantity_reserved + alloc.quantity
            if new_reserved > batch.quantity_remaining:
                raise ConflictError(
                    code="reservation_above_remaining",
                    batch_id=batch.id,
                    quantity_remaining=batch.quantity_remaining,
                    new_reserved=new_reserved,
                )
            batch.quantity_reserved = new_reserved
            await self.movements.append(
                StockMovement(
                    inventory_batch_id=batch.id,
                    branch_id=branch_id,
                    product_id=product_id,
                    movement_type=MovementType.RESERVED.value,
                    quantity_change=-alloc.quantity,
                    quantity_after=batch.quantity_remaining,
                    order_id=order_id,
                    admin_user_id=None,
                )
            )
            total += alloc.quantity

        bp = await self.branch_products.get_for_update(branch_id, product_id)
        if bp is None:
            raise NotFoundError(code="branch_product_not_found")
        bp.reserved_quantity += total
        await self.session.flush()

    async def convert_reservation_to_sold(
        self, order_id: UUID, *, actor: AdminUser | None = None
    ) -> None:
        """``preparing → ready_for_pickup / out_for_delivery``: flip
        held → physically dispatched. Decrements both
        ``quantity_remaining`` and ``quantity_reserved`` per batch, plus
        ``total_quantity`` and ``reserved_quantity`` on the cached
        aggregate.
        """
        reserved_movements = await self._reservation_movements(order_id)
        if not reserved_movements:
            raise NotFoundError(code="no_reservations_for_order", order_id=str(order_id))

        # Aggregate per (batch, branch, product) so a multi-line order
        # only one bp lock per branch_product.
        bp_totals: dict[tuple[int, UUID], int] = {}
        for m in reserved_movements:
            qty = -m.quantity_change  # reserved is negative-signed
            batch = await self.batches.get_by_id(m.inventory_batch_id)
            if batch is None:  # pragma: no cover — FK RESTRICT prevents
                raise NotFoundError(code="batch_not_found", batch_id=m.inventory_batch_id)
            batch.quantity_remaining -= qty
            batch.quantity_reserved -= qty
            await self.movements.append(
                StockMovement(
                    inventory_batch_id=batch.id,
                    branch_id=m.branch_id,
                    product_id=m.product_id,
                    movement_type=MovementType.SOLD.value,
                    quantity_change=-qty,
                    quantity_after=batch.quantity_remaining,
                    order_id=order_id,
                    admin_user_id=actor.id if actor else None,
                )
            )
            key = (m.branch_id, m.product_id)
            bp_totals[key] = bp_totals.get(key, 0) + qty

        for (branch_id, product_id), total in bp_totals.items():
            bp = await self.branch_products.get_for_update(branch_id, product_id)
            if bp is None:  # pragma: no cover
                raise NotFoundError(code="branch_product_not_found")
            bp.total_quantity -= total
            bp.reserved_quantity -= total
        await self.session.flush()

    async def release_reservations(self, order_id: UUID, *, actor: AdminUser | None = None) -> None:
        """Pre-dispatch cancel: undo each reservation. Decrements
        ``quantity_reserved`` on batches and on bp aggregate.
        ``quantity_remaining`` does not move (stock never left the
        shelf).
        """
        reserved_movements = await self._reservation_movements(order_id)
        if not reserved_movements:
            return  # idempotent — already released or never reserved

        bp_totals: dict[tuple[int, UUID], int] = {}
        for m in reserved_movements:
            qty = -m.quantity_change
            batch = await self.batches.get_by_id(m.inventory_batch_id)
            if batch is None:  # pragma: no cover
                raise NotFoundError(code="batch_not_found", batch_id=m.inventory_batch_id)
            batch.quantity_reserved -= qty
            await self.movements.append(
                StockMovement(
                    inventory_batch_id=batch.id,
                    branch_id=m.branch_id,
                    product_id=m.product_id,
                    movement_type=MovementType.RELEASED.value,
                    quantity_change=qty,  # positive: released back to free pool
                    quantity_after=batch.quantity_remaining,
                    order_id=order_id,
                    admin_user_id=actor.id if actor else None,
                )
            )
            key = (m.branch_id, m.product_id)
            bp_totals[key] = bp_totals.get(key, 0) + qty

        for (branch_id, product_id), total in bp_totals.items():
            bp = await self.branch_products.get_for_update(branch_id, product_id)
            if bp is None:  # pragma: no cover
                raise NotFoundError(code="branch_product_not_found")
            bp.reserved_quantity -= total
        await self.session.flush()

    async def _reservation_movements(self, order_id: UUID) -> Sequence[StockMovement]:
        """All ``reserved`` movements for an order. Excludes orders that
        already moved past reservation (i.e. have a ``sold`` or
        ``released`` row).
        """
        movements = await self.movements.list_for_order(order_id)
        seen_types = {m.movement_type for m in movements}
        if MovementType.SOLD.value in seen_types or MovementType.RELEASED.value in seen_types:
            return []
        return [m for m in movements if m.movement_type == MovementType.RESERVED.value]

    async def release_pending_orders(
        self,
        *,
        order_ids_to_release: Sequence[UUID],
    ) -> int:
        """Worker hook (Phase 11 schedules it).

        The lookup of which orders to release lives in the orders
        domain (Phase 8). This service only knows how to release a
        given list. Returns the count released.
        """
        n = 0
        for order_id in order_ids_to_release:
            await self.release_reservations(order_id)
            n += 1
        return n

    # ─── Cache reconciliation ──────────────────────────────────────────────

    async def reconcile_branch_product(
        self, *, branch_id: int, product_id: UUID, today: date | None = None
    ) -> tuple[int, int]:
        """Recompute ``branch_products.total_quantity`` from the source
        of truth (sum of ``quantity_remaining`` for non-expired batches
        with expiry > today + 7d) and update the cache.

        Returns ``(old_total, new_total)``.
        """
        today = today or utcnow().date()
        bp = await self.branch_products.get_for_update(branch_id, product_id)
        if bp is None:
            raise NotFoundError(code="branch_product_not_found")
        old_total = bp.total_quantity
        new_total = await self.batches.sum_remaining_non_expired(
            branch_id=branch_id, product_id=product_id, today=today
        )
        bp.total_quantity = new_total
        await self.session.flush()
        return (old_total, new_total)

    # ─── Reports ───────────────────────────────────────────────────────────

    async def list_near_expiry(
        self, *, branch_id: int, days: int, today: date | None = None
    ) -> Sequence[InventoryBatch]:
        if days not in {30, 60, 90}:
            raise ValidationError(code="invalid_days_window", days=days)
        today = today or utcnow().date()
        return await self.batches.list_near_expiry(branch_id=branch_id, today=today, days=days)

    async def list_low_stock(self, *, branch_id: int) -> Sequence[BranchProduct]:
        return await self.branch_products.list_low_stock(branch_id=branch_id)

    # ─── Branch product update (price / threshold / availability) ──────────

    async def update_branch_product(
        self,
        *,
        branch_id: int,
        product_id: UUID,
        payload: BranchProductUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BranchProduct:
        bp = await self.branch_products.get_for_update(branch_id, product_id)
        if bp is None:
            raise NotFoundError(code="branch_product_not_found")
        before = _bp_snapshot(bp)
        if payload.price is not None:
            bp.price = payload.price
        if payload.compare_at_price is not None:
            bp.compare_at_price = payload.compare_at_price
        if payload.is_available is not None:
            bp.is_available = payload.is_available
        if payload.low_stock_threshold is not None:
            bp.low_stock_threshold = payload.low_stock_threshold
        await self.session.flush()
        await self.audit.record(
            admin_user_id=actor.id,
            action="update",
            entity_type="branch_product",
            entity_id=None,
            before=before,
            after=_bp_snapshot(bp),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return bp


# ─── Snapshot helpers (used by audit log) ────────────────────────────────────


def _batch_snapshot(b: InventoryBatch) -> dict[str, Any]:
    return {
        "id": b.id,
        "branch_id": b.branch_id,
        "product_id": str(b.product_id),
        "batch_number": b.batch_number,
        "expiry_date": b.expiry_date.isoformat(),
        "quantity_received": b.quantity_received,
        "quantity_remaining": b.quantity_remaining,
        "quantity_reserved": b.quantity_reserved,
        "cost_price": str(b.cost_price),
    }


def _bp_snapshot(bp: BranchProduct) -> dict[str, Any]:
    return {
        "branch_id": bp.branch_id,
        "product_id": str(bp.product_id),
        "price": str(bp.price),
        "compare_at_price": str(bp.compare_at_price) if bp.compare_at_price is not None else None,
        "is_available": bp.is_available,
        "total_quantity": bp.total_quantity,
        "reserved_quantity": bp.reserved_quantity,
        "low_stock_threshold": bp.low_stock_threshold,
    }
