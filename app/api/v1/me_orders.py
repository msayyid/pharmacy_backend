"""Customer-facing order history + cancel + reorder.

* ``GET /api/v1/me/orders``                          — paginated history
* ``GET /api/v1/me/orders/{order_number}``           — full detail
* ``GET /api/v1/me/orders/{order_number}/status``    — slim polling shape
* ``POST /api/v1/me/orders/{order_number}/cancel``   — customer cancel
* ``POST /api/v1/me/orders/{order_number}/reorder``  — re-add to cart
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    BranchIdDep,
    get_customer_order_service,
)
from app.core.pagination import Page
from app.domain.identity.dependencies import CurrentUser
from app.domain.orders.order_service import OrderService
from app.domain.orders.schemas import (
    CancelOrderRequest,
    OrderListItem,
    OrderRead,
    OrderStatusRead,
    ReorderResponse,
)

router = APIRouter(prefix="/me/orders", tags=["customer-orders"])


@router.get("", response_model=Page[OrderListItem])
async def list_orders(
    user: CurrentUser,
    service: Annotated[OrderService, Depends(get_customer_order_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> Page[OrderListItem]:
    items, total = await service.list_for_user(user=user, page=page, page_size=page_size)
    return Page[OrderListItem](
        items=[
            OrderListItem(
                id=o.id,
                order_number=o.order_number,
                status=o.status,
                payment_status=o.payment_status,
                total=o.total,
                currency=o.currency,
                placed_at=o.placed_at,
                item_count=None,
            )
            for o in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_number}", response_model=OrderRead)
async def get_order(
    order_number: str,
    user: CurrentUser,
    service: Annotated[OrderService, Depends(get_customer_order_service)],
) -> OrderRead:
    order = await service.get_for_user(user=user, order_number=order_number)
    return OrderRead.model_validate(order)


@router.get("/{order_number}/status", response_model=OrderStatusRead)
async def get_order_status(
    order_number: str,
    user: CurrentUser,
    service: Annotated[OrderService, Depends(get_customer_order_service)],
) -> OrderStatusRead:
    order = await service.get_status_for_user(user=user, order_number=order_number)
    return OrderStatusRead(
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        confirmed_at=order.confirmed_at,
        delivered_at=order.delivered_at,
        cancelled_at=order.cancelled_at,
    )


@router.post("/{order_number}/cancel", response_model=OrderRead)
async def cancel_order(
    order_number: str,
    payload: CancelOrderRequest,
    user: CurrentUser,
    service: Annotated[OrderService, Depends(get_customer_order_service)],
) -> OrderRead:
    await service.cancel_by_customer(user=user, order_number=order_number, reason=payload.reason)
    # Re-fetch to get the appended status_history row.
    fresh = await service.get_for_user(user=user, order_number=order_number)
    return OrderRead.model_validate(fresh)


@router.post("/{order_number}/reorder", response_model=ReorderResponse)
async def reorder(
    order_number: str,
    user: CurrentUser,
    branch_id: BranchIdDep,
    service: Annotated[OrderService, Depends(get_customer_order_service)],
) -> ReorderResponse:
    cart_id, lines = await service.reorder(
        user=user, order_number=order_number, cart_branch_id=branch_id
    )
    return ReorderResponse(cart_id=cart_id, lines=lines)
