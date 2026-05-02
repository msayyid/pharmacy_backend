"""Customer checkout — quote + place_order.

* ``POST /api/v1/checkout/quote``  — recompute totals + surface diffs.
* ``POST /api/v1/checkout/place``  — the critical transaction.
                                     ``Idempotency-Key`` header REQUIRED.
"""

from __future__ import annotations

from typing import Annotated

import orjson
from fastapi import APIRouter, Depends, Header, Request, status

from app.api.deps import (
    BranchIdDep,
    CartOwner,
    get_cart_service,
    get_checkout_service,
)
from app.core.errors import ValidationError
from app.core.idempotency import body_digest
from app.domain.identity.dependencies import CurrentUser
from app.domain.orders.cart_service import CartService
from app.domain.orders.checkout_service import CheckoutService
from app.domain.orders.schemas import (
    CartItemRead,
    CheckoutQuoteRequest,
    CheckoutQuoteResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
)

router = APIRouter(prefix="/checkout", tags=["customer-checkout"])


@router.post("/quote", response_model=CheckoutQuoteResponse)
async def quote(
    payload: CheckoutQuoteRequest,
    owner: CartOwner,
    branch_id: BranchIdDep,
    cart_service: Annotated[CartService, Depends(get_cart_service)],
    checkout: Annotated[CheckoutService, Depends(get_checkout_service)],
) -> CheckoutQuoteResponse:
    user, session_id = owner
    cart = await cart_service.get_or_create(branch_id=branch_id, user=user, session_id=session_id)
    full = await cart_service.get_with_items(cart.id)
    assert full is not None
    line_ctx = await cart_service.hydrate_line_context(cart=full)
    items_read = [
        CartItemRead(
            id=it.id,
            product_id=it.product_id,
            product_name=line_ctx.get(it.id, {}).get("product_name"),
            product_slug=line_ctx.get(it.id, {}).get("product_slug"),
            thumbnail_url=line_ctx.get(it.id, {}).get("thumbnail_url"),
            quantity=it.quantity,
            price_snapshot=it.price_snapshot,
            current_price=line_ctx.get(it.id, {}).get("current_price"),
            available_quantity=line_ctx.get(it.id, {}).get("available_quantity"),
            is_in_stock=line_ctx.get(it.id, {}).get("is_in_stock"),
            line_total=line_ctx.get(it.id, {}).get("line_total"),
            added_at=it.added_at,
            updated_at=it.updated_at,
        )
        for it in full.items
    ]
    quote_data = await checkout.quote(
        cart=full,
        delivery_method=payload.delivery_method,
        payment_method=payload.payment_method,
    )
    return CheckoutQuoteResponse(items=items_read, **quote_data)


@router.post(
    "/place",
    response_model=PlaceOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def place_order(
    payload: PlaceOrderRequest,
    request: Request,
    user: CurrentUser,
    branch_id: BranchIdDep,
    cart_service: Annotated[CartService, Depends(get_cart_service)],
    checkout: Annotated[CheckoutService, Depends(get_checkout_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PlaceOrderResponse:
    if not idempotency_key:
        raise ValidationError(code="idempotency_key_required")
    cart = await cart_service.get_or_create(branch_id=branch_id, user=user, session_id=None)
    full = await cart_service.get_with_items(cart.id)
    assert full is not None

    raw_body = orjson.dumps(payload.model_dump(mode="json"))
    digest = body_digest(raw_body)
    return await checkout.place_order(
        cart=full,
        user=user,
        payload=payload,
        idempotency_key=idempotency_key,
        body_digest=digest,
    )
