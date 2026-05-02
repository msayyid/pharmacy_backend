"""Customer-facing OrderService — list / get / cancel / reorder.

* :meth:`list_for_user` — paginated history.
* :meth:`get_for_user` — full detail; 404 on miss; 403 on cross-user.
* :meth:`get_status` — slim shape for polling.
* :meth:`cancel_by_customer` — only ``pending`` / ``confirmed``;
  releases stock reservations via Phase 6 ``release_reservations``.
* :meth:`reorder` — adds prior items to the current cart with current
  prices/stock; per-line annotations for out_of_stock / price_changed
  / product_deleted.

Reference: PRODUCT_BLUEPRINT.md §F-ORD-001/002, §F-ACC-004 (reorder),
§9 (state machine), §17.2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User
from app.domain.inventory.repositories import BranchProductRepository
from app.domain.inventory.services import InventoryService
from app.domain.orders.cart_service import CartService
from app.domain.orders.models import Order, OrderStatus
from app.domain.orders.repositories import (
    OrderRepository,
    OrderStatusHistoryRepository,
)
from app.domain.orders.schemas import ReorderResponseLine

# Statuses from which the customer is allowed to self-cancel.
_CUSTOMER_CANCELLABLE = frozenset({OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value})


class OrderService:
    def __init__(
        self,
        *,
        orders: OrderRepository,
        order_history: OrderStatusHistoryRepository,
        cart_service: CartService,
        products: ProductRepository,
        branch_products: BranchProductRepository,
        inventory: InventoryService,
    ) -> None:
        self.orders = orders
        self.order_history = order_history
        self.cart_service = cart_service
        self.products = products
        self.branch_products = branch_products
        self.inventory = inventory

    # ─── Reads ─────────────────────────────────────────────────────────────

    async def list_for_user(
        self, *, user: User, page: int = 1, page_size: int = 24
    ) -> tuple[list[Order], int]:
        items, total = await self.orders.list_for_user_paginated(
            user_id=user.id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return (list(items), total)

    async def get_for_user(self, *, user: User, order_number: str) -> Order:
        order = await self.orders.get_by_number_with_items(order_number)
        if order is None:
            raise NotFoundError(code="order_not_found", order_number=order_number)
        if order.user_id != user.id:
            raise PermissionDeniedError(code="forbidden_order")
        return order

    async def get_status_for_user(self, *, user: User, order_number: str) -> Order:
        # Same check as get_for_user but returns the lighter shape — the
        # route projects to ``OrderStatusRead``.
        return await self.get_for_user(user=user, order_number=order_number)

    # ─── Cancel ────────────────────────────────────────────────────────────

    async def cancel_by_customer(
        self, *, user: User, order_number: str, reason: str | None = None
    ) -> Order:
        order = await self.orders.get_by_number_with_items(order_number)
        if order is None:
            raise NotFoundError(code="order_not_found", order_number=order_number)
        if order.user_id != user.id:
            raise PermissionDeniedError(code="forbidden_order")
        if order.status not in _CUSTOMER_CANCELLABLE:
            raise ConflictError(
                code="order_not_cancellable_by_customer",
                status=order.status,
            )

        from_status = order.status
        order.status = OrderStatus.CANCELLED.value
        order.cancelled_at = datetime.now(tz=UTC).replace(tzinfo=None)
        order.cancel_reason = reason or "customer_request"

        # Release any stock reservations for this order.
        await self.inventory.release_reservations(order.id)

        # Refund placeholder for paid card orders — Phase 10 wires the
        # gateway refund task.
        if order.payment_status == "paid":
            order.cancel_reason = f"{order.cancel_reason}|refund_pending"

        await self.order_history.append(
            order_id=order.id,
            from_status=from_status,
            to_status=order.status,
            changed_by_system=False,
            notes=reason,
        )
        return order

    # ─── Reorder ───────────────────────────────────────────────────────────

    async def reorder(
        self,
        *,
        user: User,
        order_number: str,
        cart_branch_id: int,
    ) -> tuple[UUID, list[ReorderResponseLine]]:
        """Add the order's items to the user's current cart with
        annotations.

        Out-of-stock items are surfaced as ``out_of_stock`` and not
        added. Deleted products surface as ``product_deleted``. Items
        that exceed ``max_per_order`` get capped and flagged.
        """
        order = await self.orders.get_by_number_with_items(order_number)
        if order is None:
            raise NotFoundError(code="order_not_found", order_number=order_number)
        if order.user_id != user.id:
            raise PermissionDeniedError(code="forbidden_order")

        cart = await self.cart_service.get_or_create(
            branch_id=cart_branch_id, user=user, session_id=None
        )

        # Group order_items by product_id so the reorder reflects cart
        # lines (one per product), not per-batch lines.
        per_product_qty: dict[UUID | None, int] = {}
        snapshots: dict[UUID | None, Any] = {}
        for it in order.items:
            per_product_qty[it.product_id] = per_product_qty.get(it.product_id, 0) + it.quantity
            snapshots.setdefault(
                it.product_id,
                {
                    "name": it.product_name_snapshot,
                    "sku": it.product_sku_snapshot,
                    "snapshot_price": it.unit_price,
                },
            )

        lines: list[ReorderResponseLine] = []
        for product_id, qty in per_product_qty.items():
            snap = snapshots[product_id]
            if product_id is None:
                lines.append(
                    ReorderResponseLine(
                        product_id=None,
                        product_name_snapshot=snap["name"],
                        product_sku_snapshot=snap["sku"],
                        quantity_requested=qty,
                        added_to_cart=False,
                        reason="product_deleted",
                        snapshot_price=snap["snapshot_price"],
                        current_price=None,
                    )
                )
                continue
            product = await self.products.get_by_id(product_id)
            if product is None or product.deleted_at is not None or not product.is_active:
                lines.append(
                    ReorderResponseLine(
                        product_id=product_id,
                        product_name_snapshot=snap["name"],
                        product_sku_snapshot=snap["sku"],
                        quantity_requested=qty,
                        added_to_cart=False,
                        reason="product_deleted",
                        snapshot_price=snap["snapshot_price"],
                        current_price=None,
                    )
                )
                continue
            bp = await self.branch_products.get(cart.branch_id, product_id)
            available = (
                max(int(bp.total_quantity) - int(bp.reserved_quantity), 0) if bp is not None else 0
            )
            current_price = bp.price if bp is not None else None
            if available <= 0 or bp is None or not bp.is_available:
                lines.append(
                    ReorderResponseLine(
                        product_id=product_id,
                        product_name_snapshot=snap["name"],
                        product_sku_snapshot=snap["sku"],
                        quantity_requested=qty,
                        added_to_cart=False,
                        reason="out_of_stock",
                        snapshot_price=snap["snapshot_price"],
                        current_price=current_price,
                    )
                )
                continue

            # Cap to available + max_per_order (CartService.add_item
            # caps internally; we pre-flag if a cap is going to apply
            # so the UI tells the customer).
            cap_max_per_order = product.max_per_order if product.max_per_order is not None else qty
            target = min(qty, available, cap_max_per_order)
            try:
                await self.cart_service.add_item(cart=cart, product_id=product_id, quantity=target)
            except Exception:
                lines.append(
                    ReorderResponseLine(
                        product_id=product_id,
                        product_name_snapshot=snap["name"],
                        product_sku_snapshot=snap["sku"],
                        quantity_requested=qty,
                        added_to_cart=False,
                        reason="out_of_stock",
                        snapshot_price=snap["snapshot_price"],
                        current_price=current_price,
                    )
                )
                continue

            reason = "added"
            if current_price is not None and current_price != snap["snapshot_price"]:
                reason = "price_changed"
            elif target < qty:
                reason = "max_per_order_capped"
            lines.append(
                ReorderResponseLine(
                    product_id=product_id,
                    product_name_snapshot=snap["name"],
                    product_sku_snapshot=snap["sku"],
                    quantity_requested=qty,
                    added_to_cart=True,
                    reason=reason,
                    snapshot_price=snap["snapshot_price"],
                    current_price=current_price,
                )
            )

        return (cart.id, lines)
