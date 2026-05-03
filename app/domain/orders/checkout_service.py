"""Checkout service — quote + place_order (the critical transaction).

This is the heart of the system. The :meth:`place_order` flow:

1. Idempotency-key check (``hit_same`` returns cached, ``hit_different``
   returns 409, ``miss`` proceeds).
2. Re-load cart with current branch_products (locked).
3. Validate prices unchanged from snapshots and stock available.
4. ``InventoryService.allocate_for_order`` → FEFO plan per cart line.
5. Allocate ``order_number`` via the per-year sequence (locked + bumped
   in this same transaction).
6. Insert ``Order`` (subtotal/delivery_fee/total computed).
7. Insert one ``OrderItem`` **per allocation** (cart line spanning 2
   batches → 2 items; DECISION_LOG'd).
8. ``InventoryService.reserve(allocations, order_id)`` — Phase 6 method
   writes ``reserved`` movements + bumps ``bp.reserved_quantity``.
9. Insert ``OrderStatusHistory(NULL → pending)``.
10. Card-payment scaffold: stub a payment_redirect_url (Phase 10 wires
    the real gateway).
11. Clear cart items.
12. Idempotency store + return response.

Reference: PRODUCT_BLUEPRINT.md §9, §11, §17.1; PHARMACY_BLUEPRINT_2.md §11.4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core import idempotency as idem
from app.core.errors import (
    AppError,
    NotFoundError,
    ValidationError,
)
from app.core.i18n import t as translate
from app.core.types import uuid7
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User, UserAddress
from app.domain.identity.repositories import UserAddressRepository
from app.domain.inventory.repositories import (
    BranchProductRepository,
    InventoryBatchRepository,
)
from app.domain.inventory.schemas import BatchAllocation
from app.domain.inventory.services import InventoryService
from app.domain.orders.models import (
    Cart,
    CartItem,
    DeliveryMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderSequenceRepository,
    OrderStatusHistoryRepository,
)
from app.domain.orders.schemas import (
    PlaceOrderRequest,
    PlaceOrderResponse,
    PriceConflict,
    StockConflict,
)
from app.integrations.payments.base import PaymentClient
from app.integrations.sms.base import SmsMessage, SmsQueue

# ─── Pricing helpers ─────────────────────────────────────────────────────────


FREE_DELIVERY_THRESHOLD = Decimal("1500")  # KGS — PRODUCT §11.4
DELIVERY_FEE = Decimal("200")  # KGS, flat


def compute_delivery_fee(*, subtotal: Decimal, delivery_method: str) -> Decimal:
    """Per PRODUCT §11.4: pickup is free; delivery is 200 KGS unless
    subtotal ≥ 1500 KGS."""
    if delivery_method == DeliveryMethod.PICKUP.value:
        return Decimal("0")
    if subtotal >= FREE_DELIVERY_THRESHOLD:
        return Decimal("0")
    return DELIVERY_FEE


def free_delivery_remaining(subtotal: Decimal) -> Decimal:
    if subtotal >= FREE_DELIVERY_THRESHOLD:
        return Decimal("0")
    return FREE_DELIVERY_THRESHOLD - subtotal


# ─── Errors specific to checkout ─────────────────────────────────────────────


class CheckoutValidationError(AppError):
    """Composite 409 with structured stock + price conflict details."""

    code = "checkout_conflict"
    status_code = 409
    message = "Checkout has unresolved conflicts"


class IdempotencyConflictError(AppError):
    code = "idempotency_conflict"
    status_code = 409
    message = "Idempotency-Key reused with a different body"


class IdempotencyReplayError(AppError):
    """Sentinel — caught by the route to return the cached response."""

    code = "idempotency_replay"
    status_code = 200


# ─── CheckoutService ─────────────────────────────────────────────────────────


class CheckoutService:
    def __init__(
        self,
        *,
        carts: CartRepository,
        orders: OrderRepository,
        order_history: OrderStatusHistoryRepository,
        order_sequence: OrderSequenceRepository,
        products: ProductRepository,
        branch_products: BranchProductRepository,
        batches: InventoryBatchRepository,
        addresses: UserAddressRepository,
        inventory: InventoryService,
        sms_queue: SmsQueue | None = None,
        payment_client: PaymentClient | None = None,
        payment_return_url_template: str = "https://pharmacy.kg/orders/{order_number}",
    ) -> None:
        self.carts = carts
        self.orders = orders
        self.order_history = order_history
        self.order_sequence = order_sequence
        self.products = products
        self.branch_products = branch_products
        self.batches = batches
        self.addresses = addresses
        self.inventory = inventory
        self.sms_queue = sms_queue
        self.payment_client = payment_client
        self.payment_return_url_template = payment_return_url_template

    # ─── Quote ─────────────────────────────────────────────────────────────

    async def quote(
        self,
        *,
        cart: Cart,
        delivery_method: str,
        payment_method: str,
    ) -> dict[str, Any]:
        """Compute totals + surface stock/price diffs. Does NOT reserve."""
        if not cart.items:
            raise ValidationError(code="cart_empty")

        stock_conflicts: list[StockConflict] = []
        price_conflicts: list[PriceConflict] = []
        cold_chain_warning = False

        subtotal = Decimal("0")
        for item in cart.items:
            product = await self.products.get_by_id(item.product_id)
            bp = await self.branch_products.get(cart.branch_id, item.product_id)
            available = (
                max(int(bp.total_quantity) - int(bp.reserved_quantity), 0) if bp is not None else 0
            )
            if available < item.quantity:
                stock_conflicts.append(
                    StockConflict(
                        cart_item_id=item.id,
                        product_id=item.product_id,
                        requested_quantity=item.quantity,
                        available_quantity=available,
                    )
                )
            current_price = bp.price if bp is not None else Decimal(0)
            if bp is not None and current_price != item.price_snapshot:
                price_conflicts.append(
                    PriceConflict(
                        cart_item_id=item.id,
                        product_id=item.product_id,
                        snapshot_price=item.price_snapshot,
                        current_price=current_price,
                    )
                )
            if (
                product is not None
                and product.requires_cold_chain
                and delivery_method == DeliveryMethod.DELIVERY.value
            ):
                cold_chain_warning = True
            # Subtotal uses CURRENT price (the customer must accept any
            # diff before placing the order).
            subtotal += current_price * item.quantity

        delivery_fee = compute_delivery_fee(subtotal=subtotal, delivery_method=delivery_method)
        discount_amount = Decimal("0")
        total = subtotal + delivery_fee - discount_amount

        return {
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "discount_amount": discount_amount,
            "total": total,
            "currency": cart.currency,
            "free_delivery_threshold": FREE_DELIVERY_THRESHOLD,
            "free_delivery_remaining": free_delivery_remaining(subtotal),
            "cold_chain_warning": cold_chain_warning,
            "stock_conflicts": stock_conflicts,
            "price_conflicts": price_conflicts,
        }

    # ─── Place order — THE transaction ─────────────────────────────────────

    async def place_order(  # noqa: PLR0912, PLR0915 — long-by-design transaction
        self,
        *,
        cart: Cart,
        user: User,
        payload: PlaceOrderRequest,
        idempotency_key: str,
        body_digest: str,
    ) -> PlaceOrderResponse:
        idem_scope = f"checkout:{user.id}"

        # 1) Idempotency check.
        result, stored = await idem.check(idempotency_key, body_digest, scope=idem_scope)
        if result == "hit_different":
            raise IdempotencyConflictError(code="idempotency_conflict")
        if result == "hit_same" and stored is not None:
            return PlaceOrderResponse.model_validate(stored["body"])

        # 2) Validate cart not empty / not expired.
        if not cart.items:
            raise ValidationError(code="cart_empty")
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        if cart.expires_at < now:
            raise ValidationError(code="cart_expired", cart_id=str(cart.id))

        # 3) Resolve delivery address (snapshot).
        delivery_address: dict[str, Any] | None = None
        if payload.delivery_method == DeliveryMethod.DELIVERY.value:
            delivery_address = await self._resolve_address(user=user, payload=payload)

        # 4) Re-validate prices + stock under lock.
        stock_conflicts: list[StockConflict] = []
        price_conflicts: list[PriceConflict] = []
        subtotal = Decimal("0")
        per_line_alloc: list[tuple[CartItem, list[BatchAllocation]]] = []

        for item in cart.items:
            bp = await self.branch_products.get_for_update(cart.branch_id, item.product_id)
            if bp is None or not bp.is_available:
                stock_conflicts.append(
                    StockConflict(
                        cart_item_id=item.id,
                        product_id=item.product_id,
                        requested_quantity=item.quantity,
                        available_quantity=0,
                    )
                )
                continue
            current_price = bp.price
            if current_price != item.price_snapshot:
                price_conflicts.append(
                    PriceConflict(
                        cart_item_id=item.id,
                        product_id=item.product_id,
                        snapshot_price=item.price_snapshot,
                        current_price=current_price,
                    )
                )
            available = max(int(bp.total_quantity) - int(bp.reserved_quantity), 0)
            if available < item.quantity:
                stock_conflicts.append(
                    StockConflict(
                        cart_item_id=item.id,
                        product_id=item.product_id,
                        requested_quantity=item.quantity,
                        available_quantity=available,
                    )
                )
                continue
            # Inline FEFO allocation (locks batches via Phase 6 helper).
            try:
                allocations = await self.inventory.allocate_for_order(
                    branch_id=cart.branch_id,
                    product_id=item.product_id,
                    qty=item.quantity,
                )
            except Exception as e:
                # OutOfStockError surfaces here on a tighter race.
                from app.core.errors import OutOfStockError as OOSErr

                if isinstance(e, OOSErr):
                    stock_conflicts.append(
                        StockConflict(
                            cart_item_id=item.id,
                            product_id=item.product_id,
                            requested_quantity=item.quantity,
                            available_quantity=available,
                        )
                    )
                    continue
                raise
            per_line_alloc.append((item, list(allocations)))
            subtotal += current_price * item.quantity

        if stock_conflicts or price_conflicts:
            raise CheckoutValidationError(
                code="checkout_conflict",
                stock_conflicts=[c.model_dump(mode="json") for c in stock_conflicts],
                price_conflicts=[c.model_dump(mode="json") for c in price_conflicts],
            )

        delivery_fee = compute_delivery_fee(
            subtotal=subtotal, delivery_method=payload.delivery_method
        )
        discount_amount = Decimal("0")
        total = subtotal + delivery_fee - discount_amount

        # 5) Allocate order_number.
        year = now.year
        order_number = await self.order_sequence.format_order_number(year=year)

        # 6) Insert order.
        order = Order(
            id=uuid7(),
            order_number=order_number,
            user_id=user.id,
            branch_id=cart.branch_id,
            status=OrderStatus.PENDING.value,
            payment_status=PaymentStatus.PENDING.value,
            payment_method=payload.payment_method,
            delivery_method=payload.delivery_method,
            recipient_name=payload.recipient_name,
            recipient_phone=payload.recipient_phone,
            delivery_address=delivery_address,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            discount_amount=discount_amount,
            total=total,
            currency=cart.currency,
            customer_notes=payload.customer_notes,
            placed_at=now,
        )
        await self.orders.add(order)

        # 7) Insert order_items — one per allocation.
        for cart_item, allocations in per_line_alloc:
            product = await self.products.get_by_id_with_full(cart_item.product_id)
            assert product is not None
            ru = next(
                (t for t in product.translations if t.language_code == "ru"),
                None,
            )
            unit_price = next(
                bp.price
                for bp in [await self.branch_products.get(cart.branch_id, cart_item.product_id)]
                if bp is not None
            )
            for alloc in allocations:
                batch = await self.batches.get_by_id(alloc.batch_id)
                self.orders.session.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        inventory_batch_id=alloc.batch_id,
                        product_name_snapshot=ru.name if ru else product.sku,
                        product_sku_snapshot=product.sku,
                        batch_number_snapshot=batch.batch_number if batch else None,
                        expiry_date_snapshot=batch.expiry_date if batch else None,
                        quantity=alloc.quantity,
                        unit_price=unit_price,
                        line_total=unit_price * alloc.quantity,
                    )
                )
        await self.orders.session.flush()

        # 8) Reserve inventory — writes 'reserved' movements + bumps bp.
        for cart_item, allocations in per_line_alloc:
            await self.inventory.reserve(
                branch_id=cart.branch_id,
                product_id=cart_item.product_id,
                allocations=allocations,
                order_id=order.id,
            )

        # 9) Status history NULL → pending.
        await self.order_history.append(
            order_id=order.id,
            from_status=None,
            to_status=OrderStatus.PENDING.value,
            changed_by_system=True,
        )

        # 10) Card-payment intent (Phase 10): call the gateway,
        # persist a Payment row, return the redirect URL. Falls back
        # to a stub URL if no payment_client is wired (older test
        # fixtures); production deps always inject one.
        payment_redirect_url: str | None = None
        if payload.payment_method == PaymentMethod.CARD_ONLINE.value:
            if self.payment_client is not None:
                from app.domain.payments.services import PaymentService

                intent = await self.payment_client.create_intent(
                    order_id=str(order.id),
                    order_number=order.order_number,
                    amount=order.total,
                    currency=order.currency,
                    recipient_phone=order.recipient_phone,
                    return_url=self.payment_return_url_template.format(
                        order_number=order.order_number
                    ),
                )
                payment_svc = PaymentService(session=self.orders.session)
                await payment_svc.record_charge_initiated(
                    order_id=order.id,
                    provider=self.payment_client.provider,
                    provider_transaction_id=intent.provider_transaction_id,
                    amount=order.total,
                    currency=order.currency,
                    raw_response=intent.raw,
                )
                payment_redirect_url = intent.redirect_url
            else:
                payment_redirect_url = f"https://payments.example.com/pay/{order.order_number}"

        # 11) Clear cart items.
        await self.carts.clear_items(cart.id)

        # 11a) Customer-facing SMS (PRODUCT §14.2 — order_placed).
        if self.sms_queue is not None and order.recipient_phone:
            body = translate(
                "sms.order_placed",
                "ru",  # MVP: SMS in RU; Phase 12 reads user.preferred_language.
                order_no=order.order_number,
            )
            await self.sms_queue.enqueue(
                SmsMessage(
                    phone=order.recipient_phone,
                    body=body,
                    purpose="order_placed",
                )
            )

        # Build response.
        response = PlaceOrderResponse(
            order_id=order.id,
            order_number=order.order_number,
            status=order.status,
            payment_status=order.payment_status,
            payment_method=order.payment_method,
            delivery_method=order.delivery_method,
            total=order.total,
            currency=order.currency,
            placed_at=order.placed_at,
            payment_redirect_url=payment_redirect_url,
        )

        # 12) Idempotency store.
        await idem.store(
            idempotency_key,
            body_digest,
            response={"status_code": 201, "body": response.model_dump(mode="json")},
            scope=idem_scope,
        )
        return response

    # ─── Helpers ──────────────────────────────────────────────────────────

    async def _resolve_address(self, *, user: User, payload: PlaceOrderRequest) -> dict[str, Any]:
        if payload.address is not None:
            return payload.address.model_dump(mode="json")
        if payload.address_id is None:
            raise ValidationError(code="address_required_for_delivery")
        addr = await self.addresses.get_by_id_for_user(payload.address_id, user.id)
        if addr is None:
            raise NotFoundError(code="address_not_found", address_id=payload.address_id)
        return _address_snapshot(addr)


def _address_snapshot(addr: UserAddress) -> dict[str, Any]:
    return {
        "city": addr.city,
        "address_line": addr.address_line,
        "landmark": addr.landmark,
        "label": addr.label,
        "recipient_name": addr.recipient_name,
        "recipient_phone": addr.recipient_phone,
    }
