"""Admin order queue + lifecycle.

* ``GET    /admin/v1/orders``                                 — list with filters
* ``GET    /admin/v1/orders/{id}``                            — full detail
* ``POST   /admin/v1/orders/{id}/confirm``
* ``POST   /admin/v1/orders/{id}/start-preparing``
* ``POST   /admin/v1/orders/{id}/mark-ready``
* ``POST   /admin/v1/orders/{id}/dispatch``       {courier_name, courier_phone}
* ``POST   /admin/v1/orders/{id}/mark-delivered``
* ``POST   /admin/v1/orders/{id}/cancel``         {reason, notes}
* ``POST   /admin/v1/orders/{id}/refund``         {amount, reason}  (Idem-Key REQUIRED)
* ``POST   /admin/v1/orders/{id}/items/{item_id}/swap-batch``  {new_batch_id}

RBAC per PRODUCT §19.5:
* All status transitions: super_admin / branch_manager / pharmacist
* Refund: super_admin / branch_manager only (no pharmacist)
* Branch scoping: non-super_admin actors only see / mutate their branch.

The route returns ``OrderRead`` (customer schema) for compatibility;
``GET /admin/v1/orders/{id}`` uses ``AdminOrderDetail`` for the
admin-only fields (courier info, internal_notes, branch_id).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import or_, select

from app.api.deps import (
    DbSession,
    get_order_lifecycle_service,
    get_order_repository,
)
from app.core.errors import NotFoundError, ValidationError
from app.core.idempotency import body_digest
from app.core.idempotency import check as idem_check
from app.core.idempotency import store as idem_store
from app.core.pagination import Page
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser
from app.domain.orders.admin_schemas import (
    AdminOrderDetail,
    AdminOrderListItem,
    CancelByAdminRequest,
    DispatchRequest,
    RefundRequest,
    SwapBatchRequest,
)
from app.domain.orders.lifecycle import OrderLifecycleService
from app.domain.orders.models import Order
from app.domain.orders.repositories import OrderRepository

router = APIRouter(prefix="/orders", tags=["admin-orders"])


_ORDER_ROLES = ("super_admin", "branch_manager", "pharmacist")
_REFUND_ROLES = ("super_admin", "branch_manager")
_OrderActor = Annotated[AdminUser, Depends(require_role(*_ORDER_ROLES))]
_RefundActor = Annotated[AdminUser, Depends(require_role(*_REFUND_ROLES))]


def _branch_scope(actor: AdminUser, branch_id: int) -> None:
    """Enforce per-branch scoping for non-super admins."""
    from app.core.errors import PermissionDeniedError

    if actor.role == "super_admin":
        return
    if actor.branch_id is not None and actor.branch_id != branch_id:
        raise PermissionDeniedError(
            code="forbidden_branch",
            admin_branch=actor.branch_id,
            target_branch=branch_id,
        )


def _ip_ua(request: Request) -> tuple[str | None, str | None]:
    return (
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )


# ─── List + detail ───────────────────────────────────────────────────────────


@router.get("", response_model=Page[AdminOrderListItem])
async def list_orders(
    actor: _OrderActor,
    session: DbSession,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    branch_id: int | None = None,
    payment_method: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    q: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> Page[AdminOrderListItem]:
    base = select(Order)
    if actor.role != "super_admin" and actor.branch_id is not None:
        base = base.where(Order.branch_id == actor.branch_id)
    elif branch_id is not None:
        base = base.where(Order.branch_id == branch_id)
    if status_filter is not None:
        base = base.where(Order.status == status_filter)
    if payment_method is not None:
        base = base.where(Order.payment_method == payment_method)
    if from_dt is not None:
        base = base.where(Order.placed_at >= from_dt)
    if to_dt is not None:
        base = base.where(Order.placed_at < to_dt)
    if q:
        like = f"%{q}%"
        base = base.where(
            or_(
                Order.order_number.ilike(like),
                Order.recipient_phone.ilike(like),
                Order.recipient_name.ilike(like),
            )
        )

    from sqlalchemy import func

    total_stmt = select(func.count()).select_from(base.subquery())
    items_stmt = (
        base.order_by(Order.placed_at.desc(), Order.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    total = (await session.execute(total_stmt)).scalar_one()
    items = (await session.execute(items_stmt)).scalars().all()
    return Page[AdminOrderListItem](
        items=[AdminOrderListItem.model_validate(o) for o in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_id}", response_model=AdminOrderDetail)
async def get_order(
    order_id: UUID,
    actor: _OrderActor,
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    order = await repo.get_by_id_with_items(order_id)
    if order is None:
        raise NotFoundError(code="order_not_found", order_id=str(order_id))
    _branch_scope(actor, order.branch_id)
    return AdminOrderDetail.model_validate(order)


# ─── Lifecycle transitions ───────────────────────────────────────────────────


@router.post("/{order_id}/confirm", response_model=AdminOrderDetail)
async def confirm_order(
    order_id: UUID,
    request: Request,
    actor: _OrderActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    ip, ua = _ip_ua(request)
    await service.confirm(order_id, actor=actor, ip_address=ip, user_agent=ua)
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    return AdminOrderDetail.model_validate(fresh)


@router.post("/{order_id}/start-preparing", response_model=AdminOrderDetail)
async def start_preparing(
    order_id: UUID,
    request: Request,
    actor: _OrderActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    ip, ua = _ip_ua(request)
    await service.start_preparing(order_id, actor=actor, ip_address=ip, user_agent=ua)
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    return AdminOrderDetail.model_validate(fresh)


@router.post("/{order_id}/mark-ready", response_model=AdminOrderDetail)
async def mark_ready(
    order_id: UUID,
    request: Request,
    actor: _OrderActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    ip, ua = _ip_ua(request)
    await service.mark_ready_for_pickup(order_id, actor=actor, ip_address=ip, user_agent=ua)
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    return AdminOrderDetail.model_validate(fresh)


@router.post("/{order_id}/dispatch", response_model=AdminOrderDetail)
async def dispatch(
    order_id: UUID,
    payload: DispatchRequest,
    request: Request,
    actor: _OrderActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    ip, ua = _ip_ua(request)
    await service.mark_out_for_delivery(
        order_id,
        actor=actor,
        courier_name=payload.courier_name,
        courier_phone=payload.courier_phone,
        ip_address=ip,
        user_agent=ua,
    )
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    return AdminOrderDetail.model_validate(fresh)


@router.post("/{order_id}/mark-delivered", response_model=AdminOrderDetail)
async def mark_delivered(
    order_id: UUID,
    request: Request,
    actor: _OrderActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    ip, ua = _ip_ua(request)
    await service.mark_delivered(order_id, actor=actor, ip_address=ip, user_agent=ua)
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    return AdminOrderDetail.model_validate(fresh)


@router.post("/{order_id}/cancel", response_model=AdminOrderDetail)
async def cancel_order(
    order_id: UUID,
    payload: CancelByAdminRequest,
    request: Request,
    actor: _OrderActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    ip, ua = _ip_ua(request)
    await service.cancel_by_admin(
        order_id,
        actor=actor,
        reason=payload.reason,
        ip_address=ip,
        user_agent=ua,
    )
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    return AdminOrderDetail.model_validate(fresh)


# ─── Refund (Idempotency-Key required) ───────────────────────────────────────


@router.post("/{order_id}/refund", response_model=AdminOrderDetail)
async def refund_order(
    order_id: UUID,
    payload: RefundRequest,
    request: Request,
    actor: _RefundActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdminOrderDetail:
    if not idempotency_key:
        raise ValidationError(code="idempotency_key_required")
    raw = orjson.dumps(payload.model_dump(mode="json"))
    digest = body_digest(raw)
    scope = f"refund:{actor.id}"
    result, stored = await idem_check(idempotency_key, digest, scope=scope)
    if result == "hit_different":
        from app.core.errors import ConflictError

        raise ConflictError(code="idempotency_conflict")
    if result == "hit_same" and stored is not None:
        return AdminOrderDetail.model_validate(stored["body"])

    ip, ua = _ip_ua(request)
    await service.refund(
        order_id,
        actor=actor,
        amount=payload.amount,
        reason=payload.reason,
        ip_address=ip,
        user_agent=ua,
    )
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    detail = AdminOrderDetail.model_validate(fresh)
    await idem_store(
        idempotency_key,
        digest,
        response={"status_code": 200, "body": detail.model_dump(mode="json")},
        scope=scope,
    )
    return detail


# ─── Batch swap ──────────────────────────────────────────────────────────────


@router.post(
    "/{order_id}/items/{item_id}/swap-batch",
    response_model=AdminOrderDetail,
)
async def swap_batch(
    order_id: UUID,
    item_id: int,
    payload: SwapBatchRequest,
    request: Request,
    actor: _OrderActor,
    service: Annotated[OrderLifecycleService, Depends(get_order_lifecycle_service)],
    repo: Annotated[OrderRepository, Depends(get_order_repository)],
) -> AdminOrderDetail:
    ip, ua = _ip_ua(request)
    await service.swap_batch(
        order_id=order_id,
        item_id=item_id,
        new_batch_id=payload.new_batch_id,
        actor=actor,
        ip_address=ip,
        user_agent=ua,
    )
    fresh = await repo.get_by_id_with_items(order_id)
    assert fresh is not None
    return AdminOrderDetail.model_validate(fresh)
