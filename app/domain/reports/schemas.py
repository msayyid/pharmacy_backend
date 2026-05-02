"""Report response schemas (sales, top-products, audit-log entries)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TopProductRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: UUID | None = None
    sku: str
    name: str
    units: int
    revenue: Decimal


class SalesSummary(BaseModel):
    """Headline numbers for ``GET /admin/v1/reports/sales``."""

    branch_id: int | None = None
    from_dt: datetime
    to_dt: datetime
    revenue: Decimal
    units: int
    order_count: int
    average_order_value: Decimal
    cancelled_count: int
    refunded_count: int
    currency: str = "KGS"


class SalesReport(BaseModel):
    summary: SalesSummary
    top_products: list[TopProductRow]


class TopProductsResponse(BaseModel):
    branch_id: int | None = None
    from_dt: datetime
    to_dt: datetime
    items: list[TopProductRow]
