"""Cart service — guest + user cart with merge-on-login.

* :meth:`get_or_create` — returns the active cart for a user OR a
  guest-session-id; creates one bound to the storefront branch.
* :meth:`add_item` / :meth:`update_qty` / :meth:`remove_item` —
  re-validates stock + price and snapshots the price at write time.
* :meth:`clear` — removes all items but keeps the cart row.
* :meth:`merge_guest_into_user` — additive merge on login (sums same-
  product qty, capped at ``max_per_order``); deletes the guest cart.
* :meth:`expire_check` — raises :class:`CartExpiredError` past the
  30-day TTL.

Reference: PRODUCT_BLUEPRINT.md §F-CART-001 / §17.1; PHARMACY_BLUEPRINT_2.md §7.1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.errors import (
    AppError,
    NotFoundError,
    OutOfStockError,
    ValidationError,
)
from app.domain.catalog.models import Product
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User
from app.domain.inventory.models import BranchProduct
from app.domain.inventory.repositories import BranchProductRepository
from app.domain.orders.models import Cart, CartItem
from app.domain.orders.repositories import CartRepository


class CartExpiredError(AppError):
    """Raised when the cart is past its ``expires_at`` (30-day TTL)."""

    code = "cart_expired"
    status_code = 410
    message = "Cart has expired"


class CartService:
    def __init__(
        self,
        *,
        carts: CartRepository,
        products: ProductRepository,
        branch_products: BranchProductRepository,
    ) -> None:
        self.carts = carts
        self.products = products
        self.branch_products = branch_products

    # ─── Lookup / create ───────────────────────────────────────────────────

    async def get_or_create(
        self,
        *,
        branch_id: int,
        user: User | None,
        session_id: str | None,
    ) -> Cart:
        """Resolve the active cart for the caller, creating one if needed.

        Logged-in users always look up by ``user_id``. Guests look up by
        ``session_id``. ``user is None and session_id is None`` is a
        programmer error.
        """
        if user is None and session_id is None:
            raise ValidationError(code="cart_owner_required")

        cart: Cart | None = None
        if user is not None:
            cart = await self.carts.get_by_user(user.id)
        elif session_id is not None:
            cart = await self.carts.get_by_session(session_id)

        if cart is None:
            cart = await self.carts.create(
                branch_id=branch_id,
                user_id=user.id if user is not None else None,
                session_id=session_id if user is None else None,
            )
        return cart

    # ─── Add / update / remove ─────────────────────────────────────────────

    async def add_item(self, *, cart: Cart, product_id: UUID, quantity: int) -> CartItem:
        """Add or top-up a line. Caps at ``Product.max_per_order`` and
        ``branch_products.available``. Snapshots the current price.
        """
        self._must_not_be_expired(cart)
        product = await self.products.get_by_id(product_id)
        if product is None or product.deleted_at is not None or not product.is_active:
            raise NotFoundError(code="product_not_found", product_id=str(product_id))
        bp = await self.branch_products.get(cart.branch_id, product_id)
        if bp is None or not bp.is_available:
            raise OutOfStockError(
                code="product_unavailable",
                product_id=str(product_id),
            )

        # Look for an existing line.
        existing = await self._get_item(cart.id, product_id)
        target_qty = (existing.quantity if existing else 0) + quantity
        target_qty = self._cap_quantity(product, target_qty)
        self._enforce_stock(bp, target_qty)

        if existing is None:
            item = CartItem(
                cart_id=cart.id,
                product_id=product_id,
                quantity=target_qty,
                price_snapshot=bp.price,
            )
            self.carts.session.add(item)
            await self.carts.session.flush()
            return item
        existing.quantity = target_qty
        existing.price_snapshot = bp.price
        await self.carts.session.flush()
        return existing

    async def update_qty(self, *, cart: Cart, item_id: int, quantity: int) -> CartItem:
        self._must_not_be_expired(cart)
        item = await self._get_item_by_id(cart.id, item_id)
        product = await self.products.get_by_id(item.product_id)
        if product is None:  # pragma: no cover — FK CASCADE prevents
            raise NotFoundError(code="product_not_found")
        bp = await self.branch_products.get(cart.branch_id, item.product_id)
        if bp is None:
            raise OutOfStockError(code="product_unavailable")

        capped = self._cap_quantity(product, quantity)
        self._enforce_stock(bp, capped)
        item.quantity = capped
        item.price_snapshot = bp.price
        await self.carts.session.flush()
        return item

    async def remove_item(self, *, cart: Cart, item_id: int) -> None:
        self._must_not_be_expired(cart)
        item = await self._get_item_by_id(cart.id, item_id)
        await self.carts.session.delete(item)
        await self.carts.session.flush()

    async def clear(self, *, cart: Cart) -> int:
        return await self.carts.clear_items(cart.id)

    # ─── Merge guest cart on login ────────────────────────────────────────

    async def merge_guest_into_user(self, *, user: User, session_id: str, branch_id: int) -> Cart:
        """Login hook: merge guest cart (by ``session_id``) into the
        user's cart (creating one if missing).

        Additive: same-product lines have their quantities summed, then
        re-capped at ``max_per_order``. Then the guest cart row is
        deleted (FK CASCADE removes its items).
        """
        guest = await self.carts.get_by_session(session_id)
        if guest is None:
            return await self.get_or_create(branch_id=branch_id, user=user, session_id=None)

        user_cart = await self.carts.get_by_user(user.id)
        if user_cart is None:
            # Promote the guest cart to a user cart.
            guest.user_id = user.id
            guest.session_id = None
            await self.carts.session.flush()
            return guest

        # Both carts exist — merge guest items into user_cart.
        user_items_by_product = {i.product_id: i for i in user_cart.items}
        for guest_item in guest.items:
            existing = user_items_by_product.get(guest_item.product_id)
            product = await self.products.get_by_id(guest_item.product_id)
            target_qty = (existing.quantity if existing else 0) + guest_item.quantity
            if product is not None:
                target_qty = self._cap_quantity(product, target_qty)
            if existing is None:
                self.carts.session.add(
                    CartItem(
                        cart_id=user_cart.id,
                        product_id=guest_item.product_id,
                        quantity=target_qty,
                        price_snapshot=guest_item.price_snapshot,
                    )
                )
            else:
                existing.quantity = target_qty
        await self.carts.session.delete(guest)
        await self.carts.session.flush()
        return user_cart

    # ─── Expiry ────────────────────────────────────────────────────────────

    def _must_not_be_expired(self, cart: Cart) -> None:
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        if cart.expires_at < now:
            raise CartExpiredError(code="cart_expired", cart_id=str(cart.id))

    # ─── Helpers ──────────────────────────────────────────────────────────

    async def _get_item(self, cart_id: UUID, product_id: UUID) -> CartItem | None:
        stmt = select(CartItem).where(
            CartItem.cart_id == cart_id, CartItem.product_id == product_id
        )
        return (await self.carts.session.execute(stmt)).scalar_one_or_none()

    async def _get_item_by_id(self, cart_id: UUID, item_id: int) -> CartItem:
        stmt = select(CartItem).where(CartItem.cart_id == cart_id, CartItem.id == item_id)
        item = (await self.carts.session.execute(stmt)).scalar_one_or_none()
        if item is None:
            raise NotFoundError(code="cart_item_not_found", item_id=item_id)
        return item

    @staticmethod
    def _cap_quantity(product: Product, quantity: int) -> int:
        if quantity < 1:
            raise ValidationError(code="quantity_must_be_positive", quantity=quantity)
        if product.max_per_order is not None and quantity > product.max_per_order:
            return int(product.max_per_order)
        return quantity

    @staticmethod
    def _enforce_stock(bp: BranchProduct, quantity: int) -> None:
        available = max(int(bp.total_quantity) - int(bp.reserved_quantity), 0)
        if available < quantity:
            raise OutOfStockError(
                code="insufficient_stock",
                requested=quantity,
                available=available,
            )

    # ─── Read helpers (used by routes for response shaping) ───────────────

    async def get_with_items(self, cart_id: UUID) -> Cart | None:
        return await self.carts.get_by_id_with_items(cart_id)

    async def hydrate_line_context(self, *, cart: Cart) -> dict[int, dict[str, Any]]:
        """Return per-cart-item enrichment for the response: current
        price, available quantity, primary translation name + slug,
        thumbnail.

        One product-by-product loop is fine for cart sizes (≤ a few
        items); ``ProductRepository.get_by_id_with_full`` handles the
        eager loads.
        """
        out: dict[int, dict[str, Any]] = {}
        for it in cart.items:
            product = await self.products.get_by_id_with_full(it.product_id)
            bp = await self.branch_products.get(cart.branch_id, it.product_id)
            ru_name = None
            if product is not None:
                ru = next(
                    (t for t in product.translations if t.language_code == "ru"),
                    None,
                )
                ru_name = ru.name if ru is not None else product.sku
            available = (
                max(int(bp.total_quantity) - int(bp.reserved_quantity), 0) if bp is not None else 0
            )
            current_price = bp.price if bp is not None else Decimal(0)
            line_total = it.price_snapshot * it.quantity
            out[it.id] = {
                "product_name": ru_name,
                "product_slug": product.slug if product is not None else None,
                "thumbnail_url": _primary_thumb(product),
                "current_price": current_price,
                "available_quantity": available,
                "is_in_stock": available > 0,
                "line_total": line_total,
            }
        return out


# ─── Internals ───────────────────────────────────────────────────────────────


def _primary_thumb(product: Product | None) -> str | None:
    if product is None:
        return None
    for img in product.images:
        if img.is_primary:
            return img.thumbnail_url
    return product.images[0].thumbnail_url if product.images else None
