"""ReportService — sales aggregations + top-products.

Cached for 5 minutes per ``(branch_id, from, to)`` triple. CSV export
is per-row; the route wraps the iterator in a ``StreamingResponse``.

Cancelled and refunded orders are excluded from revenue but counted
separately (DECISION_LOG'd).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get_or_set
from app.domain.reports.schemas import (
    SalesReport,
    SalesSummary,
    TopProductRow,
)

REPORT_TTL = 300  # 5 minutes (BACKEND §18.4)


def sales_cache_key(branch_id: int | None, from_dt: datetime, to_dt: datetime) -> str:
    branch = branch_id if branch_id is not None else "all"
    return f"v1:report:sales:{branch}:{from_dt.isoformat()}:{to_dt.isoformat()}"


def top_products_cache_key(
    branch_id: int | None, from_dt: datetime, to_dt: datetime, limit: int
) -> str:
    branch = branch_id if branch_id is not None else "all"
    return f"v1:report:top:{branch}:{from_dt.isoformat()}:{to_dt.isoformat()}:{limit}"


class ReportService:
    """Sales + top-products aggregations with TTL cache."""

    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session

    # ─── Sales report ──────────────────────────────────────────────────────

    async def sales_report(
        self,
        *,
        branch_id: int | None,
        from_dt: datetime,
        to_dt: datetime,
        top_n: int = 10,
    ) -> SalesReport:
        async def _loader() -> dict[str, Any]:
            summary = await self._sales_summary(branch_id, from_dt, to_dt)
            top = await self._top_products(branch_id, from_dt, to_dt, top_n)
            return {
                "summary": summary.model_dump(mode="json"),
                "top_products": [t.model_dump(mode="json") for t in top],
            }

        cached = await cache_get_or_set(
            sales_cache_key(branch_id, from_dt, to_dt),
            REPORT_TTL,
            _loader,
        )
        return SalesReport.model_validate(cached)

    async def top_products(
        self,
        *,
        branch_id: int | None,
        from_dt: datetime,
        to_dt: datetime,
        limit: int = 10,
    ) -> list[TopProductRow]:
        async def _loader() -> list[dict[str, Any]]:
            rows = await self._top_products(branch_id, from_dt, to_dt, limit)
            return [r.model_dump(mode="json") for r in rows]

        cached = await cache_get_or_set(
            top_products_cache_key(branch_id, from_dt, to_dt, limit),
            REPORT_TTL,
            _loader,
        )
        return [TopProductRow.model_validate(r) for r in cached]

    # ─── CSV streaming ─────────────────────────────────────────────────────

    @staticmethod
    def stream_csv(
        rows: Iterable[dict[str, Any]],
        *,
        columns: list[str],
        bom: bool = True,
    ) -> Iterable[bytes]:
        """Yield UTF-8 CSV bytes. Optional BOM for Excel compatibility."""
        if bom:
            yield "﻿".encode()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        yield buf.getvalue().encode()
        buf.truncate(0)
        buf.seek(0)
        for row in rows:
            writer.writerow([_csv_cell(row.get(c)) for c in columns])
            yield buf.getvalue().encode()
            buf.truncate(0)
            buf.seek(0)

    # ─── Internal SQL ──────────────────────────────────────────────────────

    async def _sales_summary(
        self, branch_id: int | None, from_dt: datetime, to_dt: datetime
    ) -> SalesSummary:
        params: dict[str, Any] = {"from_dt": from_dt, "to_dt": to_dt}
        branch_clause = ""
        if branch_id is not None:
            branch_clause = "AND o.branch_id = :branch_id"
            params["branch_id"] = branch_id

        stmt = text(
            f"""
            SELECT
              COALESCE(
                SUM(CASE WHEN o.status NOT IN ('cancelled', 'refunded')
                          THEN o.total ELSE 0 END), 0) AS revenue,
              COALESCE(
                SUM(CASE WHEN o.status NOT IN ('cancelled', 'refunded')
                          THEN oi_qty.qty ELSE 0 END), 0) AS units,
              SUM(CASE WHEN o.status NOT IN ('cancelled', 'refunded')
                        THEN 1 ELSE 0 END) AS order_count,
              SUM(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count,
              SUM(CASE WHEN o.status = 'refunded' THEN 1 ELSE 0 END) AS refunded_count
            FROM orders o
            LEFT JOIN (
              SELECT order_id, SUM(quantity) AS qty
              FROM order_items
              GROUP BY order_id
            ) oi_qty ON oi_qty.order_id = o.id
            WHERE o.placed_at >= :from_dt
              AND o.placed_at < :to_dt
              {branch_clause}
            """  # noqa: S608 — only static fragments are interpolated
        )
        result = (await self.session.execute(stmt, params)).mappings().one()
        revenue = _to_decimal(result["revenue"])
        units = int(result["units"] or 0)
        order_count = int(result["order_count"] or 0)
        aov = revenue / order_count if order_count > 0 else Decimal("0")
        return SalesSummary(
            branch_id=branch_id,
            from_dt=from_dt,
            to_dt=to_dt,
            revenue=revenue,
            units=units,
            order_count=order_count,
            average_order_value=aov.quantize(Decimal("0.01")),
            cancelled_count=int(result["cancelled_count"] or 0),
            refunded_count=int(result["refunded_count"] or 0),
        )

    async def _top_products(
        self,
        branch_id: int | None,
        from_dt: datetime,
        to_dt: datetime,
        limit: int,
    ) -> list[TopProductRow]:
        params: dict[str, Any] = {
            "from_dt": from_dt,
            "to_dt": to_dt,
            "limit": limit,
        }
        branch_clause = ""
        if branch_id is not None:
            branch_clause = "AND o.branch_id = :branch_id"
            params["branch_id"] = branch_id

        stmt = text(
            f"""
            SELECT
              oi.product_id  AS product_id,
              MIN(oi.product_sku_snapshot)  AS sku,
              MIN(oi.product_name_snapshot) AS name,
              SUM(oi.quantity)              AS units,
              SUM(oi.line_total)            AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.placed_at >= :from_dt
              AND o.placed_at < :to_dt
              AND o.status NOT IN ('cancelled', 'refunded')
              {branch_clause}
            GROUP BY oi.product_id
            ORDER BY units DESC, revenue DESC
            LIMIT :limit
            """
        )
        rows = (await self.session.execute(stmt, params)).mappings().all()
        return [_row_to_top_product(r) for r in rows]


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _row_to_top_product(r: RowMapping) -> TopProductRow:
    return TopProductRow(
        product_id=_load_uuid(r["product_id"]),
        sku=str(r["sku"]) if r["sku"] is not None else "",
        name=str(r["name"]) if r["name"] is not None else "",
        units=int(r["units"] or 0),
        revenue=_to_decimal(r["revenue"]),
    )


def _load_uuid(value: Any) -> UUID | None:
    """Decode the byte-swapped ``BINARY(16)`` from raw ``text()`` output.

    Mirrors :func:`app.core.types.GUID.process_result_value` — needed
    because raw-text queries bypass the ``TypeDecorator``.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    b: bytes = value
    original = b[4:8] + b[2:4] + b[0:2] + b[8:]
    return UUID(bytes=original)


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
