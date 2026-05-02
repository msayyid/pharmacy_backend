"""Admin products — ``/api/admin/v1/products``.

Includes CRUD, ``/{id}/images`` upload + management, and bulk
``/import/dry-run`` and ``/import/apply`` endpoints. RBAC: ``super_admin``
and ``content_editor`` per PRODUCT §19.5.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Query,
    Request,
    UploadFile,
    status,
)

from app.api.deps import (
    get_product_image_service,
    get_product_import_service,
    get_product_repository,
    get_product_service,
)
from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.domain.catalog.images import ProductImageService
from app.domain.catalog.import_csv import ProductImportService
from app.domain.catalog.products import ProductService
from app.domain.catalog.repositories import ProductRepository
from app.domain.catalog.schemas import (
    BulkImportSummary,
    ProductCreate,
    ProductImageRead,
    ProductImageUpdate,
    ProductListItem,
    ProductRead,
    ProductUpdate,
)
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser

router = APIRouter(prefix="/products", tags=["admin-catalog"])

_AdminGuard = Annotated[AdminUser, Depends(require_role("super_admin", "content_editor"))]


# ─── CRUD ────────────────────────────────────────────────────────────────────


@router.get("", response_model=Page[ProductListItem])
async def list_products(
    _admin: _AdminGuard,
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
    category_id: int | None = None,
    manufacturer_id: int | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> Page[ProductListItem]:
    items, total = await repo.list_paginated(
        category_id=category_id,
        manufacturer_id=manufacturer_id,
        is_active=is_active,
        q=q,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[ProductListItem](
        items=[ProductListItem.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductService, Depends(get_product_service)],
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
) -> ProductRead:
    p = await service.create_product(
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    # Reload with eager-loaded children so ``ProductRead`` can serialise.
    full = await repo.get_by_id_with_full(p.id)
    assert full is not None
    return ProductRead.model_validate(full)


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: UUID,
    _admin: _AdminGuard,
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
) -> ProductRead:
    p = await repo.get_by_id_with_full(product_id)
    if p is None:
        raise NotFoundError(code="product_not_found")
    return ProductRead.model_validate(p)


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductService, Depends(get_product_service)],
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
) -> ProductRead:
    await service.update_product(
        product_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_full(product_id)
    assert full is not None
    return ProductRead.model_validate(full)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_product(
    product_id: UUID,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductService, Depends(get_product_service)],
) -> None:
    await service.soft_delete_product(
        product_id,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# ─── Images ──────────────────────────────────────────────────────────────────


@router.post(
    "/{product_id}/images",
    response_model=ProductImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    product_id: UUID,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImageService, Depends(get_product_image_service)],
    file: Annotated[UploadFile, File()],
) -> ProductImageRead:
    file_bytes = await file.read()
    image = await service.upload(
        product_id=product_id,
        file_bytes=file_bytes,
        content_type=file.content_type or "",
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return ProductImageRead.model_validate(image)


@router.patch(
    "/{product_id}/images/{image_id}",
    response_model=ProductImageRead,
)
async def update_image(
    product_id: UUID,
    image_id: int,
    payload: ProductImageUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImageService, Depends(get_product_image_service)],
) -> ProductImageRead:
    image = await service.update(
        product_id=product_id,
        image_id=image_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return ProductImageRead.model_validate(image)


@router.delete(
    "/{product_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_image(
    product_id: UUID,
    image_id: int,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImageService, Depends(get_product_image_service)],
) -> None:
    await service.delete(
        product_id=product_id,
        image_id=image_id,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# ─── Bulk import ─────────────────────────────────────────────────────────────


@router.post("/import/dry-run", response_model=BulkImportSummary)
async def import_dry_run(
    _admin: _AdminGuard,
    service: Annotated[ProductImportService, Depends(get_product_import_service)],
    file: Annotated[UploadFile, File()],
) -> BulkImportSummary:
    csv_bytes = await file.read()
    return await service.dry_run(csv_bytes)


@router.post("/import/apply", response_model=BulkImportSummary)
async def import_apply(
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImportService, Depends(get_product_import_service)],
    file: Annotated[UploadFile, File()],
) -> BulkImportSummary:
    csv_bytes = await file.read()
    return await service.apply(
        csv_bytes,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
