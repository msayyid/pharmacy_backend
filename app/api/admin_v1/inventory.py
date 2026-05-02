"""Admin inventory — ``/api/admin/v1`` (mounted as several path prefixes).

Endpoints (all RBAC-gated):

* ``POST /branches/{branch_id}/inventory/batches``                 — receive
* ``PATCH /inventory/batches/{batch_id}``                          — adjust
* ``PATCH /branches/{branch_id}/inventory/products/{product_id}``  — bp update
* ``GET /branches/{branch_id}/inventory``                          — list bp
* ``GET /inventory/movements``                                     — audit
* ``GET /branches/{branch_id}/reports/near-expiry?days=30|60|90``
* ``GET /branches/{branch_id}/reports/low-stock``

Roles permitted (PRODUCT §19.5 + Phase 6 prompt):
* ``super_admin``     — everything.
* ``branch_manager``  — own branch only (enforced via ``require_branch_access``).
* ``pharmacist``      — own branch only; can receive + adjust + read.
* ``content_editor``  — **forbidden from inventory entirely** (403).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    get_branch_product_repository,
    get_branch_repository,
    get_inventory_batch_repository,
    get_inventory_service,
    get_product_repository,
    get_stock_movement_repository,
)
from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.dependencies import (
    require_branch_access,
    require_role,
)
from app.domain.identity.models import AdminUser
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
)
from app.domain.inventory.schemas import (
    BatchAdjustRequest,
    BatchRead,
    BatchReceiveRequest,
    BatchReceiveResponse,
    BranchProductRead,
    BranchProductUpdate,
    LowStockRow,
    NearExpiryRow,
    StockMovementRead,
)
from app.domain.inventory.services import InventoryService

router = APIRouter(tags=["admin-inventory"])


_INVENTORY_ROLES = ("super_admin", "branch_manager", "pharmacist")
_PRICING_ROLES = ("super_admin", "branch_manager")


def _branch_admin(*roles: str) -> Any:
    """Compose ``require_role`` + ``require_branch_access('branch_id')``.

    ``Annotated[X, Depends(a), Depends(b)]`` does not work — FastAPI
    only resolves the last ``Depends``. Inside a closure we can't use
    ``Annotated[..., Depends(role_check)]`` either, because
    ``from __future__ import annotations`` defers annotations to
    strings and the closure-captured ``role_check`` isn't resolvable
    at module level by ``get_type_hints``. So use the legacy
    ``param: T = Depends(...)`` form, which FastAPI inspects at runtime
    via the default value.
    """
    role_check = require_role(*roles)
    branch_check = require_branch_access("branch_id")

    async def _dep(
        admin_by_role: AdminUser = Depends(role_check),  # noqa: B008 — FastAPI pattern
        _admin_branch_ok: AdminUser = Depends(branch_check),  # noqa: B008
    ) -> AdminUser:
        return admin_by_role

    return _dep


_BranchInventoryAdmin = Annotated[AdminUser, Depends(_branch_admin(*_INVENTORY_ROLES))]
_GlobalInventoryAdmin = Annotated[AdminUser, Depends(require_role(*_INVENTORY_ROLES))]
_PricingAdmin = Annotated[AdminUser, Depends(_branch_admin(*_PRICING_ROLES))]


# ─── Receive batch ───────────────────────────────────────────────────────────


@router.post(
    "/branches/{branch_id}/inventory/batches",
    response_model=BatchReceiveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_batch(
    branch_id: int,
    payload: BatchReceiveRequest,
    request: Request,
    admin: _BranchInventoryAdmin,
    service: Annotated[InventoryService, Depends(get_inventory_service)],
) -> BatchReceiveResponse:
    return await service.receive_batch(
        branch_id=branch_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# ─── Adjust batch ────────────────────────────────────────────────────────────


@router.patch(
    "/inventory/batches/{batch_id}",
    response_model=BatchRead,
)
async def adjust_batch(
    batch_id: int,
    payload: BatchAdjustRequest,
    request: Request,
    admin: _GlobalInventoryAdmin,
    service: Annotated[InventoryService, Depends(get_inventory_service)],
    batches_repo: Annotated[InventoryBatchRepository, Depends(get_inventory_batch_repository)],
) -> BatchRead:
    # Branch-scoping check before mutation: pharmacist/branch_manager can
    # only adjust batches in their own branch. Super admin bypasses.
    batch = await batches_repo.get_by_id(batch_id)
    if batch is None:
        raise NotFoundError(code="batch_not_found", batch_id=batch_id)
    _require_same_branch(admin, batch.branch_id)

    await service.adjust_batch(
        batch_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    # Reload to surface server-side ``updated_at`` and any other
    # auto-managed columns. Avoids ``MissingGreenlet`` from accessing
    # an expired attribute during Pydantic serialisation.
    fresh = await batches_repo.get_by_id(batch_id)
    assert fresh is not None
    return BatchRead.model_validate(fresh)


# ─── List branch products ────────────────────────────────────────────────────


@router.get(
    "/branches/{branch_id}/inventory",
    response_model=Page[BranchProductRead],
)
async def list_branch_inventory(
    branch_id: int,
    _admin: _BranchInventoryAdmin,
    repo: Annotated[BranchProductRepository, Depends(get_branch_product_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
    low_stock: bool = False,
    only_available: bool = False,
) -> Page[BranchProductRead]:
    items, total = await repo.list_paginated(
        branch_id=branch_id,
        offset=(page - 1) * page_size,
        limit=page_size,
        low_stock=low_stock,
        only_available=only_available,
    )
    return Page[BranchProductRead](
        items=[BranchProductRead.model_validate(bp) for bp in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ─── PATCH branch_product (price + threshold + availability) ─────────────────


@router.patch(
    "/branches/{branch_id}/inventory/products/{product_id}",
    response_model=BranchProductRead,
)
async def update_branch_product(
    branch_id: int,
    product_id: UUID,
    payload: BranchProductUpdate,
    request: Request,
    admin: _PricingAdmin,
    service: Annotated[InventoryService, Depends(get_inventory_service)],
) -> BranchProductRead:
    bp = await service.update_branch_product(
        branch_id=branch_id,
        product_id=product_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return BranchProductRead.model_validate(bp)


# ─── Stock movements (audit) ─────────────────────────────────────────────────


@router.get(
    "/inventory/movements",
    response_model=Page[StockMovementRead],
)
async def list_movements(
    _admin: _GlobalInventoryAdmin,
    repo: Annotated[StockMovementRepository, Depends(get_stock_movement_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    branch_id: int | None = None,
    product_id: UUID | None = None,
    movement_type: str | None = None,
    admin_user_id: int | None = None,
    order_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Page[StockMovementRead]:
    items, total = await repo.list_paginated(
        offset=(page - 1) * page_size,
        limit=page_size,
        branch_id=branch_id,
        product_id=product_id,
        movement_type=movement_type,
        admin_user_id=admin_user_id,
        order_id=order_id,
        date_from=date_from,
        date_to=date_to,
    )
    return Page[StockMovementRead](
        items=[StockMovementRead.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ─── Reports ─────────────────────────────────────────────────────────────────


@router.get(
    "/branches/{branch_id}/reports/near-expiry",
    response_model=list[NearExpiryRow],
)
async def report_near_expiry(
    branch_id: int,
    _admin: _BranchInventoryAdmin,
    service: Annotated[InventoryService, Depends(get_inventory_service)],
    branches_repo: Annotated[BranchRepository, Depends(get_branch_repository)],
    products_repo: Annotated[ProductRepository, Depends(get_product_repository)],
    days: Annotated[int, Query(ge=1, le=365)] = 60,
    fmt: Annotated[str, Query(alias="format", pattern="^(json|csv)$")] = "json",
) -> Any:
    if (await branches_repo.get_by_id(branch_id)) is None:
        raise NotFoundError(code="branch_not_found", branch_id=branch_id)

    batches = await service.list_near_expiry(branch_id=branch_id, days=days)
    rows = await _decorate_near_expiry(batches, products_repo, days)
    if fmt == "csv":
        return _csv_response(
            rows,
            filename=f"near-expiry-branch-{branch_id}.csv",
            columns=[
                "batch_id",
                "product_sku",
                "product_name",
                "batch_number",
                "expiry_date",
                "quantity_remaining",
                "days_left",
            ],
        )
    return rows


@router.get(
    "/branches/{branch_id}/reports/low-stock",
    response_model=list[LowStockRow],
)
async def report_low_stock(
    branch_id: int,
    _admin: _BranchInventoryAdmin,
    service: Annotated[InventoryService, Depends(get_inventory_service)],
    branches_repo: Annotated[BranchRepository, Depends(get_branch_repository)],
    products_repo: Annotated[ProductRepository, Depends(get_product_repository)],
    fmt: Annotated[str, Query(alias="format", pattern="^(json|csv)$")] = "json",
) -> Any:
    if (await branches_repo.get_by_id(branch_id)) is None:
        raise NotFoundError(code="branch_not_found", branch_id=branch_id)

    bps = await service.list_low_stock(branch_id=branch_id)
    rows = await _decorate_low_stock(bps, products_repo)
    if fmt == "csv":
        return _csv_response(
            rows,
            filename=f"low-stock-branch-{branch_id}.csv",
            columns=[
                "branch_id",
                "product_sku",
                "product_name",
                "total_quantity",
                "reserved_quantity",
                "low_stock_threshold",
            ],
        )
    return rows


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _require_same_branch(admin: AdminUser, branch_id: int) -> None:
    """Mirror of ``require_branch_access`` for paths that don't carry
    ``branch_id`` directly (e.g. ``/inventory/batches/{batch_id}``)."""
    from app.core.errors import PermissionDeniedError

    if admin.role == "super_admin":
        return
    if admin.branch_id != branch_id:
        raise PermissionDeniedError(
            code="forbidden_branch",
            admin_branch=admin.branch_id,
            target_branch=branch_id,
        )


async def _decorate_near_expiry(
    batches: Any, products_repo: ProductRepository, days: int
) -> list[NearExpiryRow]:
    from datetime import date as _date

    today = _date.today()
    rows: list[NearExpiryRow] = []
    for b in batches:
        product = await products_repo.get_by_id_with_full(b.product_id)
        if product is None:
            continue
        ru = next(
            (t for t in product.translations if t.language_code == "ru"),
            None,
        )
        rows.append(
            NearExpiryRow(
                batch_id=b.id,
                product_id=b.product_id,
                product_sku=product.sku,
                product_name=ru.name if ru else product.sku,
                batch_number=b.batch_number,
                expiry_date=b.expiry_date,
                quantity_remaining=b.quantity_remaining,
                days_left=(b.expiry_date - today).days,
            )
        )
    return rows


async def _decorate_low_stock(bps: Any, products_repo: ProductRepository) -> list[LowStockRow]:
    rows: list[LowStockRow] = []
    for bp in bps:
        product = await products_repo.get_by_id_with_full(bp.product_id)
        if product is None:
            continue
        ru = next(
            (t for t in product.translations if t.language_code == "ru"),
            None,
        )
        rows.append(
            LowStockRow(
                branch_id=bp.branch_id,
                product_id=bp.product_id,
                product_sku=product.sku,
                product_name=ru.name if ru else product.sku,
                total_quantity=bp.total_quantity,
                reserved_quantity=bp.reserved_quantity,
                low_stock_threshold=bp.low_stock_threshold,
            )
        )
    return rows


def _csv_response(rows: list[Any], *, filename: str, columns: list[str]) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        data = row.model_dump()
        writer.writerow([data.get(c, "") for c in columns])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"content-disposition": f"attachment; filename={filename}"},
    )
