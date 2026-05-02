"""Orders domain — request and response schemas.

Per BACKEND §10:
* ``XxxCreate`` / ``XxxRequest`` — POST/PATCH bodies (``extra="forbid"``).
* ``XxxRead`` — response, ``from_attributes=True``.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── Cart ────────────────────────────────────────────────────────────────────


class CartItemAdd(BaseModel):
    """POST /api/v1/cart/items."""

    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    quantity: Annotated[int, Field(ge=1, le=999)]


class CartItemUpdate(BaseModel):
    """PATCH /api/v1/cart/items/{id}."""

    model_config = ConfigDict(extra="forbid")
    quantity: Annotated[int, Field(ge=1, le=999)]


class CartItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: UUID
    product_name: str | None = None  # service-side fill
    product_slug: str | None = None
    thumbnail_url: str | None = None
    quantity: int
    price_snapshot: Decimal
    current_price: Decimal | None = None  # filled by quote / cart-read
    available_quantity: int | None = None
    is_in_stock: bool | None = None
    line_total: Decimal | None = None
    added_at: datetime
    updated_at: datetime


class CartTotalsRead(BaseModel):
    subtotal: Decimal
    delivery_fee: Decimal | None = None  # filled at quote time
    discount_amount: Decimal = Decimal("0")
    total: Decimal | None = None
    free_delivery_threshold: Decimal | None = None
    free_delivery_remaining: Decimal | None = None
    currency: str = "KGS"


class CartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    branch_id: int
    currency: str
    items: list[CartItemRead]
    totals: CartTotalsRead
    expires_at: datetime


# ─── Checkout ────────────────────────────────────────────────────────────────


_PaymentMethodLiteral = Literal[
    "cash_on_delivery",
    "card_online",
    "mbank",
    "elsom",
    "odengi",
    "balance_kg",
    "bank_transfer",
]
_DeliveryMethodLiteral = Literal["delivery", "pickup"]


class CheckoutQuoteRequest(BaseModel):
    """POST /api/v1/checkout/quote.

    ``address_id`` is required for delivery; pickup ignores it.
    """

    model_config = ConfigDict(extra="forbid")
    address_id: int | None = None
    delivery_method: _DeliveryMethodLiteral
    payment_method: _PaymentMethodLiteral = "cash_on_delivery"


class StockConflict(BaseModel):
    """One row of the 409 ``out_of_stock`` body."""

    cart_item_id: int
    product_id: UUID
    requested_quantity: int
    available_quantity: int


class PriceConflict(BaseModel):
    cart_item_id: int
    product_id: UUID
    snapshot_price: Decimal
    current_price: Decimal


class CheckoutQuoteResponse(BaseModel):
    items: list[CartItemRead]
    subtotal: Decimal
    delivery_fee: Decimal
    discount_amount: Decimal
    total: Decimal
    currency: str = "KGS"
    free_delivery_threshold: Decimal | None = None
    free_delivery_remaining: Decimal | None = None
    cold_chain_warning: bool = False
    stock_conflicts: list[StockConflict] = Field(default_factory=list)
    price_conflicts: list[PriceConflict] = Field(default_factory=list)


class PlaceOrderAddress(BaseModel):
    """Inline address for guests / new addresses at checkout."""

    model_config = ConfigDict(extra="forbid")
    city: Annotated[str, Field(min_length=1, max_length=80)]
    address_line: Annotated[str, Field(min_length=1, max_length=500)]
    landmark: Annotated[str | None, Field(max_length=255)] = None
    apartment: Annotated[str | None, Field(max_length=40)] = None
    floor: Annotated[str | None, Field(max_length=20)] = None
    entrance: Annotated[str | None, Field(max_length=20)] = None
    intercom_code: Annotated[str | None, Field(max_length=20)] = None
    delivery_notes: Annotated[str | None, Field(max_length=500)] = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None


class PlaceOrderRequest(BaseModel):
    """POST /api/v1/checkout/place — Idempotency-Key header REQUIRED."""

    model_config = ConfigDict(extra="forbid")
    address_id: int | None = None
    address: PlaceOrderAddress | None = None
    delivery_method: _DeliveryMethodLiteral
    payment_method: _PaymentMethodLiteral
    recipient_name: Annotated[str, Field(min_length=1, max_length=160)]
    recipient_phone: Annotated[str, Field(min_length=1, max_length=20)]
    customer_notes: Annotated[str | None, Field(max_length=2000)] = None


class PlaceOrderResponse(BaseModel):
    order_id: UUID
    order_number: str
    status: str
    payment_status: str
    payment_method: str
    delivery_method: str
    total: Decimal
    currency: str
    placed_at: datetime
    payment_redirect_url: str | None = None  # card_online only


# ─── Customer order views ────────────────────────────────────────────────────


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: UUID | None = None
    inventory_batch_id: int | None = None
    product_name_snapshot: str
    product_sku_snapshot: str
    batch_number_snapshot: str | None = None
    expiry_date_snapshot: _date | None = None
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_status: str | None = None
    to_status: str
    changed_by_system: bool
    notes: str | None = None
    created_at: datetime


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_number: str
    branch_id: int
    status: str
    payment_status: str
    payment_method: str
    delivery_method: str
    recipient_name: str
    recipient_phone: str
    delivery_address: dict[str, Any] | None = None
    subtotal: Decimal
    delivery_fee: Decimal
    discount_amount: Decimal
    total: Decimal
    currency: str
    customer_notes: str | None = None
    cancel_reason: str | None = None
    placed_at: datetime
    confirmed_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    items: list[OrderItemRead]
    history: list[OrderStatusHistoryRead]


class OrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_number: str
    status: str
    payment_status: str
    total: Decimal
    currency: str
    placed_at: datetime
    item_count: int | None = None  # service-filled when convenient


class OrderStatusRead(BaseModel):
    """Slim shape for ``GET /me/orders/{order_number}/status`` polling."""

    model_config = ConfigDict(from_attributes=True)
    order_number: str
    status: str
    payment_status: str
    confirmed_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None


class CancelOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str | None, Field(max_length=500)] = None


class ReorderResponseLine(BaseModel):
    """One annotated line returned by ``POST /me/orders/{n}/reorder``.

    The service adds in-stock items to the current cart and surfaces
    the rest with reasons (out_of_stock / price_changed / product_deleted)
    so the UI can prompt the customer to remove or substitute.
    """

    product_id: UUID | None = None
    product_name_snapshot: str
    product_sku_snapshot: str
    quantity_requested: int
    added_to_cart: bool
    reason: Literal[
        "added", "out_of_stock", "price_changed", "product_deleted", "max_per_order_capped"
    ]
    snapshot_price: Decimal | None = None
    current_price: Decimal | None = None


class ReorderResponse(BaseModel):
    cart_id: UUID
    lines: list[ReorderResponseLine]
