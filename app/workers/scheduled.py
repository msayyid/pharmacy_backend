"""ARQ scheduled jobs (cron-driven).

All cron schedules live in :mod:`app.workers.settings`; this module
just exposes the function bodies. Each function is async, takes a
single ``ctx`` dict (per ARQ convention), opens its own session via
:func:`session_scope` (BACKEND §17.3), and is **idempotent**: re-running
the same minute must produce the same end state.

Reference: BACKEND §17; PHARMACY §18; PRODUCT §10.6, §F-ADM-INV-003.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import orjson
from sqlalchemy import select

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.deliveries.repositories import DeliveryRepository
from app.domain.identity.repositories import OtpRepository
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
from app.domain.inventory.services import InventoryService
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from app.domain.orders.lifecycle import OrderLifecycleService
from app.domain.orders.models import (
    Payment,
    PaymentStatus,
)
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderStatusHistoryRepository,
)
from app.domain.payments.services import PaymentService
from app.integrations.payments.factory import get_payment_client

log = get_logger(__name__)


OTP_RETENTION_DAYS = 7
NEAR_EXPIRY_DAYS = 60
PAYMENT_RECONCILE_AGE_MINUTES = 5
REPORT_TTL_SECONDS = 36 * 3600  # 36h cache for the daily reports


def _utcnow() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


# ─── Daily reports ───────────────────────────────────────────────────────────


async def near_expiry_report(ctx: dict[str, Any]) -> dict[int, int]:
    """Daily 06:00 KG. For each active branch, list batches expiring
    within ``NEAR_EXPIRY_DAYS`` (PRODUCT §F-ADM-INV-003).

    Email integration is deferred to Phase 12 (Q4 default). For now the
    payload is logged + cached in Redis at
    ``v1:report:near_expiry:<date>:<branch_id>`` so the admin UI can
    read it without re-running the query.
    """
    today = _utcnow().date()
    summary: dict[int, int] = {}
    async with session_scope() as session:
        branches = await BranchRepository(session).list_active()
        inv = _inv_service(session)
        for branch in branches:
            batches = await inv.list_near_expiry(
                branch_id=branch.id, days=NEAR_EXPIRY_DAYS, today=today
            )
            payload = [_near_expiry_row(b, today) for b in batches]
            await _cache_report("near_expiry", branch.id, today, payload)
            summary[branch.id] = len(payload)
            log.info(
                "near_expiry_report_branch",
                branch_id=branch.id,
                count=len(payload),
                date=today.isoformat(),
            )
    log.info("near_expiry_report_done", branches=len(summary))
    return summary


async def low_stock_report(ctx: dict[str, Any]) -> dict[int, int]:
    """Daily 06:10 KG. For each active branch, list branch_products at
    or below their threshold (PRODUCT §F-ADM-INV-003)."""
    today = _utcnow().date()
    summary: dict[int, int] = {}
    async with session_scope() as session:
        branches = await BranchRepository(session).list_active()
        inv = _inv_service(session)
        for branch in branches:
            rows = await inv.list_low_stock(branch_id=branch.id)
            payload = [_low_stock_row(bp) for bp in rows]
            await _cache_report("low_stock", branch.id, today, payload)
            summary[branch.id] = len(payload)
            log.info(
                "low_stock_report_branch",
                branch_id=branch.id,
                count=len(payload),
                date=today.isoformat(),
            )
    log.info("low_stock_report_done", branches=len(summary))
    return summary


# ─── Stock maintenance ───────────────────────────────────────────────────────


async def expire_batches(ctx: dict[str, Any]) -> dict[str, int]:
    """Daily 02:00 KG. Mark expired batches.

    For every batch with ``expiry_date <= today`` and
    ``quantity_remaining > 0``: write one ``stock_movements`` row of
    type ``expired`` for the remaining qty, set ``quantity_remaining=0``,
    then ``reconcile_branch_product`` for the affected (branch, product).
    """
    today = _utcnow().date()
    expired_count = 0
    reconciled: set[tuple[int, str]] = set()
    async with session_scope() as session:
        # We need a list of all (branch_id, batch) pairs with expired
        # remaining qty across all branches. The repo's ``list_expired``
        # is per-branch, so we walk the branch list.
        branches = await BranchRepository(session).list_active()
        for branch in branches:
            stmt = (
                select(InventoryBatch)
                .where(
                    InventoryBatch.branch_id == branch.id,
                    InventoryBatch.quantity_remaining > 0,
                    InventoryBatch.expiry_date <= today,
                )
                .with_for_update(skip_locked=True)
            )
            batches = (await session.execute(stmt)).scalars().all()
            for batch in batches:
                qty = int(batch.quantity_remaining)
                session.add(
                    StockMovement(
                        branch_id=batch.branch_id,
                        product_id=batch.product_id,
                        inventory_batch_id=batch.id,
                        movement_type=MovementType.EXPIRED.value,
                        quantity_change=-qty,
                        quantity_after=0,
                        reason="auto_expire_batches_cron",
                        admin_user_id=None,
                        order_id=None,
                    )
                )
                batch.quantity_remaining = 0
                expired_count += 1
                reconciled.add((batch.branch_id, str(batch.product_id)))

        # Recompute the cached total_quantity for every (branch, product)
        # we touched. This collapses any drift introduced by the above
        # update + ensures the storefront sees the new in-stock total.
        inv = _inv_service(session)
        for branch_id, product_id_str in reconciled:
            from uuid import UUID

            await inv.reconcile_branch_product(
                branch_id=branch_id,
                product_id=UUID(product_id_str),
                today=today,
            )
    log.info(
        "expire_batches_done",
        expired_batches=expired_count,
        reconciled_branch_products=len(reconciled),
    )
    return {"expired": expired_count, "reconciled": len(reconciled)}


async def reconcile_stock_cache(ctx: dict[str, Any]) -> dict[str, int]:
    """Daily 03:00 KG. Walk every BranchProduct and recompute its
    ``total_quantity`` cache from the source of truth (sum of
    non-expired batch ``quantity_remaining``). Logs drift on mismatch.
    """
    today = _utcnow().date()
    drift_count = 0
    bp_count = 0
    async with session_scope() as session:
        rows = (await session.execute(select(BranchProduct))).scalars().all()
        inv = _inv_service(session)
        for bp in rows:
            bp_count += 1
            old, new = await inv.reconcile_branch_product(
                branch_id=bp.branch_id,
                product_id=bp.product_id,
                today=today,
            )
            if old != new:
                drift_count += 1
                log.warning(
                    "stock_cache_drift",
                    branch_id=bp.branch_id,
                    product_id=str(bp.product_id),
                    old=old,
                    new=new,
                )
    log.info("reconcile_stock_cache_done", branch_products=bp_count, drift=drift_count)
    return {"branch_products": bp_count, "drift": drift_count}


# ─── Cleanups ────────────────────────────────────────────────────────────────


async def cleanup_otps(ctx: dict[str, Any]) -> int:
    """Daily 04:00 KG. Delete OTP rows older than 7 days
    (consumed or expired, doesn't matter — they're stale)."""
    threshold = _utcnow() - timedelta(days=OTP_RETENTION_DAYS)
    async with session_scope() as session:
        deleted = await OtpRepository(session).delete_older_than(threshold)
    log.info("cleanup_otps_done", deleted=deleted, threshold=threshold.isoformat())
    return deleted


async def cleanup_carts(ctx: dict[str, Any]) -> int:
    """Daily 04:10 KG. Delete carts past their ``expires_at``
    (Phase 8 wrote the helper)."""
    async with session_scope() as session:
        deleted = await CartRepository(session).delete_expired(now=_utcnow())
    log.info("cleanup_carts_done", deleted=deleted)
    return deleted


# ─── Order timeouts + payment reconcile ──────────────────────────────────────


async def release_pending_orders(ctx: dict[str, Any]) -> int:
    """Every 5 min. Cancel orders past their auto-cancel deadline:

    * card_online + placed_at < now-30min → ``payment_failed`` reason
      (gateway timed out without paying)
    * any pending + placed_at < now-24h → ``auto_timeout_unconfirmed``
      reason (admin never confirmed)

    Cancellation goes through :class:`OrderLifecycleService.cancel_by_admin`
    so the same status_history + audit + SMS hooks fire as a manual
    cancel. ``actor`` is a stand-in system AdminUser (``role=super_admin``,
    ``id=None`` is rejected by the audit table FK, so we use the first
    super_admin row — typically the seed admin).
    """
    now = _utcnow()
    cancelled = 0
    async with session_scope() as session:
        from app.domain.identity.models import AdminUser as _AdminUser
        from app.domain.orders.models import PaymentMethod as _PaymentMethod

        actor = (
            (
                await session.execute(
                    select(_AdminUser).where(_AdminUser.role == "super_admin").limit(1)
                )
            )
            .scalars()
            .first()
        )
        if actor is None:
            log.warning("release_pending_orders_skip_no_super_admin")
            return 0

        orders = await OrderRepository(session).list_pending_for_timeout(now=now)
        if not orders:
            return 0

        lifecycle = _lifecycle_service(session)
        for order in orders:
            reason = (
                "payment_failed"
                if order.payment_method == _PaymentMethod.CARD_ONLINE.value
                else "auto_timeout_unconfirmed"
            )
            try:
                await lifecycle.cancel_by_admin(
                    order.id,
                    actor=actor,
                    reason=reason,
                )
                cancelled += 1
            except Exception as exc:
                log.warning(
                    "release_pending_orders_skip",
                    order_id=str(order.id),
                    error=str(exc),
                )
    log.info("release_pending_orders_done", cancelled=cancelled, total_seen=len(orders))
    return cancelled


async def payment_reconcile(ctx: dict[str, Any]) -> dict[str, int]:
    """Every 5 min, offset 2. For every pending non-refund Payment row
    older than ``PAYMENT_RECONCILE_AGE_MINUTES``, ask the gateway whether
    it actually settled (``client.verify_status``). If yes, run the
    same handle_webhook path that a real webhook would.

    Idempotent: re-running with no new pending payments is a no-op.
    """
    cutoff = _utcnow() - timedelta(minutes=PAYMENT_RECONCILE_AGE_MINUTES)
    client = get_payment_client()
    reconciled = 0
    failed = 0
    skipped = 0
    async with session_scope() as session:
        stmt = (
            select(Payment)
            .where(
                Payment.status == PaymentStatus.PENDING.value,
                Payment.is_refund == False,  # noqa: E712 — SQL boolean
                Payment.created_at < cutoff,
                Payment.provider_transaction_id.is_not(None),
            )
            .with_for_update(skip_locked=True)
            .limit(50)
        )
        pending = (await session.execute(stmt)).scalars().all()
        if not pending:
            return {"reconciled": 0, "failed": 0, "skipped": 0}

        svc = PaymentService(session=session)
        for payment in pending:
            txn_id = payment.provider_transaction_id
            assert txn_id is not None  # filtered above; guarded for mypy
            try:
                event = await client.verify_status(provider_transaction_id=txn_id)
            except NotImplementedError:
                # Real adapter scaffold — pending vendor verification.
                skipped += 1
                continue
            except Exception as exc:
                log.warning(
                    "payment_reconcile_provider_error",
                    payment_id=str(payment.id),
                    error=str(exc),
                )
                failed += 1
                continue
            if event is None:
                skipped += 1
                continue
            outcome = await svc.handle_webhook(event, provider=client.provider)
            if outcome.status == "applied":
                reconciled += 1
            else:
                skipped += 1
    log.info(
        "payment_reconcile_done",
        reconciled=reconciled,
        failed=failed,
        skipped=skipped,
    )
    return {"reconciled": reconciled, "failed": failed, "skipped": skipped}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _inv_service(session: Any) -> InventoryService:
    return InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )


def _lifecycle_service(session: Any) -> OrderLifecycleService:
    return OrderLifecycleService(
        session=session,
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        batches=InventoryBatchRepository(session),
        branch_products=BranchProductRepository(session),
        movements=StockMovementRepository(session),
        inventory=_inv_service(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
        deliveries=DeliveryRepository(session),
    )


def _near_expiry_row(batch: InventoryBatch, today: Any) -> dict[str, Any]:
    days = (batch.expiry_date - today).days
    return {
        "batch_id": batch.id,
        "product_id": str(batch.product_id),
        "batch_number": batch.batch_number,
        "expiry_date": batch.expiry_date.isoformat(),
        "days_remaining": days,
        "quantity_remaining": int(batch.quantity_remaining),
    }


def _low_stock_row(bp: BranchProduct) -> dict[str, Any]:
    available = max(int(bp.total_quantity) - int(bp.reserved_quantity), 0)
    return {
        "product_id": str(bp.product_id),
        "total_quantity": int(bp.total_quantity),
        "reserved_quantity": int(bp.reserved_quantity),
        "available": available,
        "low_stock_threshold": int(bp.low_stock_threshold),
    }


async def _cache_report(
    name: str,
    branch_id: int,
    date: Any,
    payload: list[dict[str, Any]],
) -> None:
    """Write the report payload to Redis. Best-effort; no-ops without Redis."""
    try:
        redis = get_redis()
    except RuntimeError:
        return
    key = f"v1:report:{name}:{date.isoformat()}:{branch_id}"
    body = orjson.dumps({"branch_id": branch_id, "date": date.isoformat(), "rows": payload})
    await redis.set(key, body, ex=REPORT_TTL_SECONDS)


_ = (json, Decimal)  # imports kept for stable JSON serialisation paths
