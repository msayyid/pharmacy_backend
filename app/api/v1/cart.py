"""Customer cart — guest + authenticated.

* ``GET /api/v1/cart``                       — current cart (creates if missing)
* ``POST /api/v1/cart/items``                — add or top-up
* ``PATCH /api/v1/cart/items/{id}``          — update qty
* ``DELETE /api/v1/cart/items/{id}``         — remove
* ``POST /api/v1/cart/clear``                — clear all items

Guest carts use the ``pharmacy_cart_session`` cookie (HttpOnly, 30-day).
On login, ``CartService.merge_guest_into_user`` is invoked from the
auth flow.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import (
    GUEST_CART_COOKIE,
    GUEST_CART_COOKIE_TTL,
    BranchIdDep,
    CartOwner,
    get_cart_service,
)
from app.core.errors import NotFoundError, ValidationError
from app.domain.orders.cart_service import CartService
from app.domain.orders.models import Cart
from app.domain.orders.schemas import (
    CartItemAdd,
    CartItemRead,
    CartItemUpdate,
    CartRead,
    CartTotalsRead,
)

router = APIRouter(prefix="/cart", tags=["customer-cart"])


def _ensure_session_cookie(
    response: Response,
    owner: tuple[object, str | None],
    request: Request,
) -> str | None:
    """If the caller is a guest with no session cookie, mint one."""
    user, session_id = owner
    if user is not None:
        return None
    if session_id is None:
        session_id = secrets.token_urlsafe(24)
        response.set_cookie(
            GUEST_CART_COOKIE,
            session_id,
            max_age=GUEST_CART_COOKIE_TTL,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )
    return str(session_id) if session_id is not None else None


async def _build_cart_read(cart: Cart, *, service: CartService) -> CartRead:
    """Hydrate a Cart ORM into the response shape."""
    # Refresh the items collection async-safely. The cart instance is
    # in the session's identity map; selectinload from a separate query
    # would still return the cached collection, so we explicitly
    # re-load ``items`` here.
    await service.carts.session.refresh(cart, ["items"])
    full = cart
    assert full is not None
    line_ctx = await service.hydrate_line_context(cart=full)
    items: list[CartItemRead] = []
    subtotal = 0
    for it in full.items:
        ctx = line_ctx.get(it.id, {})
        line_total = ctx.get("line_total")
        if line_total is not None:
            subtotal += line_total
        items.append(
            CartItemRead(
                id=it.id,
                product_id=it.product_id,
                product_name=ctx.get("product_name"),
                product_slug=ctx.get("product_slug"),
                thumbnail_url=ctx.get("thumbnail_url"),
                quantity=it.quantity,
                price_snapshot=it.price_snapshot,
                current_price=ctx.get("current_price"),
                available_quantity=ctx.get("available_quantity"),
                is_in_stock=ctx.get("is_in_stock"),
                line_total=line_total,
                added_at=it.added_at,
                updated_at=it.updated_at,
            )
        )
    totals = CartTotalsRead(
        subtotal=subtotal,
        currency=full.currency,
    )
    return CartRead(
        id=full.id,
        branch_id=full.branch_id,
        currency=full.currency,
        items=items,
        totals=totals,
        expires_at=full.expires_at,
    )


@router.get("", response_model=CartRead)
async def get_cart(
    request: Request,
    response: Response,
    owner: CartOwner,
    branch_id: BranchIdDep,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartRead:
    user, session_id = owner
    session_id = _ensure_session_cookie(response, owner, request) or session_id
    cart = await service.get_or_create(branch_id=branch_id, user=user, session_id=session_id)
    return await _build_cart_read(cart, service=service)


@router.post("/items", response_model=CartRead, status_code=status.HTTP_201_CREATED)
async def add_item(
    payload: CartItemAdd,
    request: Request,
    response: Response,
    owner: CartOwner,
    branch_id: BranchIdDep,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartRead:
    user, session_id = owner
    session_id = _ensure_session_cookie(response, owner, request) or session_id
    cart = await service.get_or_create(branch_id=branch_id, user=user, session_id=session_id)
    await service.add_item(cart=cart, product_id=payload.product_id, quantity=payload.quantity)
    return await _build_cart_read(cart, service=service)


@router.patch("/items/{item_id}", response_model=CartRead)
async def update_item(
    item_id: int,
    payload: CartItemUpdate,
    owner: CartOwner,
    branch_id: BranchIdDep,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartRead:
    user, session_id = owner
    if user is None and session_id is None:
        raise ValidationError(code="cart_owner_required")
    cart = await service.get_or_create(branch_id=branch_id, user=user, session_id=session_id)
    await service.update_qty(cart=cart, item_id=item_id, quantity=payload.quantity)
    return await _build_cart_read(cart, service=service)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_item(
    item_id: int,
    owner: CartOwner,
    branch_id: BranchIdDep,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> None:
    user, session_id = owner
    if user is None and session_id is None:
        raise NotFoundError(code="cart_not_found")
    cart = await service.get_or_create(branch_id=branch_id, user=user, session_id=session_id)
    await service.remove_item(cart=cart, item_id=item_id)


@router.post("/clear", response_model=CartRead)
async def clear_cart(
    owner: CartOwner,
    branch_id: BranchIdDep,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartRead:
    user, session_id = owner
    if user is None and session_id is None:
        raise NotFoundError(code="cart_not_found")
    cart = await service.get_or_create(branch_id=branch_id, user=user, session_id=session_id)
    await service.clear(cart=cart)
    return await _build_cart_read(cart, service=service)
