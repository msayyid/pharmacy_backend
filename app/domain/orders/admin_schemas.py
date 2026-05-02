"""Admin order schemas — request bodies + admin-flavoured response shapes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.orders.schemas import OrderItemRead, OrderStatusHistoryRead

# ─── Cancel / Refund / Dispatch / Swap ───────────────────────────────────────


_CANCEL_REASON_LITERAL = Literal[
    "customer_changed_mind",
    "out_of_stock_at_picking",
    "customer_unreachable",
    "customer_refused_at_door",
    "payment_failed",
    "auto_timeout_unconfirmed",
    "other",
]


class CancelByAdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: _CANCEL_REASON_LITERAL
    notes: Annotated[str | None, Field(max_length=500)] = None


class DispatchRequest(BaseModel):
    """POST /admin/v1/orders/{id}/dispatch."""

    model_config = ConfigDict(extra="forbid")
    courier_name: Annotated[str, Field(min_length=1, max_length=160)]
    courier_phone: Annotated[str, Field(min_length=1, max_length=20)]


class RefundRequest(BaseModel):
    """POST /admin/v1/orders/{id}/refund.

    ``amount`` must be ≤ ``order.total``. Idempotency-Key header
    REQUIRED on the route.
    """

    model_config = ConfigDict(extra="forbid")
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class SwapBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_batch_id: int


# ─── List + detail ──────────────────────────────────────────────────────────


class AdminOrderListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_number: str
    user_id: UUID | None = None
    branch_id: int
    status: str
    payment_status: str
    payment_method: str
    delivery_method: str
    recipient_name: str
    recipient_phone: str
    total: Decimal
    currency: str
    placed_at: datetime
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None


class AdminOrderDetail(BaseModel):
    """Admin detail view — same shape as customer ``OrderRead`` plus
    ``user_id`` / ``internal_notes`` / courier info / branch_id.
    """

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_number: str
    user_id: UUID | None = None
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
    internal_notes: str | None = None
    cancel_reason: str | None = None
    courier_name: str | None = None
    courier_phone: str | None = None
    placed_at: datetime
    confirmed_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    items: list[OrderItemRead]
    history: list[OrderStatusHistoryRead]


# ─── Audit log entries (admin viewer) ────────────────────────────────────────


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    admin_user_id: int | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    changes: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
