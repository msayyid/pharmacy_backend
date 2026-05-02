"""Admin reports — sales summary + top products + CSV export.

* ``GET /admin/v1/reports/sales?from=&to=&branch=&format=json|csv``
* ``GET /admin/v1/reports/top-products?from=&to=&branch=&limit=&format=json|csv``
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_report_service
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser
from app.domain.reports.schemas import TopProductsResponse
from app.domain.reports.services import ReportService

router = APIRouter(prefix="/reports", tags=["admin-reports"])

_REPORT_ROLES = ("super_admin", "branch_manager", "pharmacist")
_ReportActor = Annotated[AdminUser, Depends(require_role(*_REPORT_ROLES))]


def _scope_branch(actor: AdminUser, branch: int | None) -> int | None:
    """Non-super admins are pinned to their own branch_id, ignoring
    the query param. Super admins can pass any branch_id (or None for
    "all branches")."""
    if actor.role == "super_admin":
        return branch
    return actor.branch_id


@router.get("/sales")
async def sales_report(
    actor: _ReportActor,
    service: Annotated[ReportService, Depends(get_report_service)],
    from_dt: Annotated[datetime, Query(alias="from")],
    to_dt: Annotated[datetime, Query(alias="to")],
    branch: int | None = None,
    fmt: Annotated[str, Query(alias="format", pattern="^(json|csv)$")] = "json",
) -> Any:
    branch_id = _scope_branch(actor, branch)
    report = await service.sales_report(branch_id=branch_id, from_dt=from_dt, to_dt=to_dt, top_n=10)
    if fmt == "csv":
        rows = [
            {
                "kind": "summary",
                "revenue": str(report.summary.revenue),
                "units": report.summary.units,
                "order_count": report.summary.order_count,
                "average_order_value": str(report.summary.average_order_value),
                "cancelled_count": report.summary.cancelled_count,
                "refunded_count": report.summary.refunded_count,
                "from_dt": report.summary.from_dt,
                "to_dt": report.summary.to_dt,
                "branch_id": report.summary.branch_id,
            }
        ]
        return StreamingResponse(
            ReportService.stream_csv(
                rows,
                columns=[
                    "kind",
                    "revenue",
                    "units",
                    "order_count",
                    "average_order_value",
                    "cancelled_count",
                    "refunded_count",
                    "from_dt",
                    "to_dt",
                    "branch_id",
                ],
            ),
            media_type="text/csv; charset=utf-8",
            headers={
                "content-disposition": (
                    "attachment; filename="
                    f"sales-{from_dt.date().isoformat()}_"
                    f"{to_dt.date().isoformat()}.csv"
                ),
            },
        )
    return report


@router.get("/top-products")
async def top_products(
    actor: _ReportActor,
    service: Annotated[ReportService, Depends(get_report_service)],
    from_dt: Annotated[datetime, Query(alias="from")],
    to_dt: Annotated[datetime, Query(alias="to")],
    branch: int | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    fmt: Annotated[str, Query(alias="format", pattern="^(json|csv)$")] = "json",
) -> Any:
    branch_id = _scope_branch(actor, branch)
    rows = await service.top_products(
        branch_id=branch_id, from_dt=from_dt, to_dt=to_dt, limit=limit
    )
    if fmt == "csv":
        dict_rows = [
            {
                "product_id": str(r.product_id) if r.product_id else "",
                "sku": r.sku,
                "name": r.name,
                "units": r.units,
                "revenue": str(r.revenue),
            }
            for r in rows
        ]
        return StreamingResponse(
            ReportService.stream_csv(
                dict_rows,
                columns=["product_id", "sku", "name", "units", "revenue"],
            ),
            media_type="text/csv; charset=utf-8",
            headers={
                "content-disposition": (
                    "attachment; filename="
                    f"top-products-{from_dt.date().isoformat()}_"
                    f"{to_dt.date().isoformat()}.csv"
                ),
            },
        )
    return TopProductsResponse(branch_id=branch_id, from_dt=from_dt, to_dt=to_dt, items=rows)
