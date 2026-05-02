"""Inventory domain — Pydantic schemas (request bodies + read shapes).

Per BACKEND §10:
* ``XxxCreate`` / ``XxxRequest`` — request bodies (``extra="forbid"``).
* ``XxxRead`` — response, ``from_attributes=True``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── Suppliers ────────────────────────────────────────────────────────────────


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=160)]
    contact_phone: Annotated[str | None, Field(max_length=20)] = None
    contact_email: Annotated[str | None, Field(max_length=255)] = None
    address: str | None = None
    notes: str | None = None
    is_active: bool = True


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str | None, Field(max_length=160)] = None
    contact_phone: Annotated[str | None, Field(max_length=20)] = None
    contact_email: Annotated[str | None, Field(max_length=255)] = None
    address: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    contact_phone: str | None = None
    contact_email: str | None = None
    address: str | None = None
    notes: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ─── Branches ────────────────────────────────────────────────────────────────


class BranchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    address: str
    city: str
    phone: str | None = None
    timezone: str
    is_active: bool


# ─── Branch products (per-branch availability + price + cached stock) ────────


class BranchProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    branch_id: int
    product_id: UUID
    price: Decimal
    compare_at_price: Decimal | None = None
    currency: str
    is_available: bool
    total_quantity: int
    reserved_quantity: int
    low_stock_threshold: int
    updated_at: datetime


class BranchProductUpdate(BaseModel):
    """PATCH /admin/v1/branches/{branch_id}/inventory/products/{product_id}."""

    model_config = ConfigDict(extra="forbid")
    price: Annotated[Decimal | None, Field(ge=0, max_digits=12, decimal_places=2)] = None
    compare_at_price: Annotated[Decimal | None, Field(ge=0, max_digits=12, decimal_places=2)] = None
    is_available: bool | None = None
    low_stock_threshold: Annotated[int | None, Field(ge=0)] = None


# ─── Inventory batches ───────────────────────────────────────────────────────


class BatchReceiveRequest(BaseModel):
    """POST /admin/v1/branches/{branch_id}/inventory/batches."""

    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    supplier_id: int | None = None
    batch_number: Annotated[str, Field(min_length=1, max_length=60)]
    expiry_date: date
    manufacture_date: date | None = None
    quantity_received: Annotated[int, Field(gt=0)]
    cost_price: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)] = "KGS"
    # Set to True to bypass the ≤7-day hard block (rare, super_admin only).
    override_short_expiry: bool = False


class BatchAdjustRequest(BaseModel):
    """PATCH /admin/v1/inventory/batches/{batch_id}.

    ``movement_type`` is restricted to manual-correction kinds; sales /
    reservations / restocks are handled by other service paths.
    """

    model_config = ConfigDict(extra="forbid")
    quantity_change: int  # signed: negative = damage / write-off, positive = re-count up
    movement_type: Literal["damaged", "adjusted"]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class BatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    branch_id: int
    product_id: UUID
    supplier_id: int | None = None
    batch_number: str
    expiry_date: date
    manufacture_date: date | None = None
    quantity_received: int
    quantity_remaining: int
    cost_price: Decimal
    currency: str
    received_at: datetime
    created_at: datetime
    updated_at: datetime


class BatchReceiveResponse(BaseModel):
    """Wraps ``BatchRead`` with two service-layer flags the admin UI uses
    to render warnings / next-step prompts.

    * ``is_short_dated`` — expiry within 60 days (PRODUCT §10.5 soft warn).
    * ``branch_product_pending_pricing`` — first-receive auto-created the
      ``branch_products`` row at price=0, is_available=False; admin must
      set a price before storefront shows the product.
    """

    model_config = ConfigDict(from_attributes=True)
    batch: BatchRead
    is_short_dated: bool
    branch_product_pending_pricing: bool


# ─── Stock movements (audit) ─────────────────────────────────────────────────


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inventory_batch_id: int
    branch_id: int
    product_id: UUID
    movement_type: str
    quantity_change: int
    quantity_after: int
    order_id: UUID | None = None
    admin_user_id: int | None = None
    reason: str | None = None
    created_at: datetime


# ─── Reports ─────────────────────────────────────────────────────────────────


class NearExpiryRow(BaseModel):
    """Row in /admin/v1/branches/{id}/reports/near-expiry."""

    model_config = ConfigDict(from_attributes=True)
    batch_id: int
    product_id: UUID
    product_sku: str
    product_name: str
    batch_number: str
    expiry_date: date
    quantity_remaining: int
    days_left: int


class LowStockRow(BaseModel):
    """Row in /admin/v1/branches/{id}/reports/low-stock."""

    model_config = ConfigDict(from_attributes=True)
    branch_id: int
    product_id: UUID
    product_sku: str
    product_name: str
    total_quantity: int
    reserved_quantity: int
    low_stock_threshold: int


# ─── Allocation result (used by Phase 8 place-order, surfaced in tests) ─────


class BatchAllocation(BaseModel):
    """One slice of a multi-batch FEFO allocation.

    Returned by ``InventoryService.allocate_for_order``; consumed by
    ``InventoryService.reserve``. Phase 8's place-order writes the
    matching ``order_items`` snapshot per allocation.
    """

    model_config = ConfigDict(from_attributes=True)
    batch_id: int
    batch_number: str
    expiry_date: date
    quantity: int
