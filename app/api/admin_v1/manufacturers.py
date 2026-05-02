"""Admin manufacturers — ``/api/admin/v1/manufacturers``.

RBAC: ``super_admin`` and ``content_editor`` per PRODUCT §19.5.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import get_catalog_admin_service, get_manufacturer_repository
from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.domain.catalog.repositories import ManufacturerRepository
from app.domain.catalog.schemas import (
    ManufacturerCreate,
    ManufacturerRead,
    ManufacturerUpdate,
)
from app.domain.catalog.services import CatalogAdminService
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser

router = APIRouter(prefix="/manufacturers", tags=["admin-catalog"])

_AdminGuard = Annotated[AdminUser, Depends(require_role("super_admin", "content_editor"))]


@router.get("", response_model=Page[ManufacturerRead])
async def list_manufacturers(
    _admin: _AdminGuard,
    repo: Annotated[ManufacturerRepository, Depends(get_manufacturer_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
    q: str | None = None,
) -> Page[ManufacturerRead]:
    items, total = await repo.list_paginated(offset=(page - 1) * page_size, limit=page_size, q=q)
    return Page[ManufacturerRead](
        items=[ManufacturerRead.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ManufacturerRead, status_code=status.HTTP_201_CREATED)
async def create_manufacturer(
    payload: ManufacturerCreate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
) -> ManufacturerRead:
    m = await service.create_manufacturer(
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return ManufacturerRead.model_validate(m)


@router.get("/{manufacturer_id}", response_model=ManufacturerRead)
async def get_manufacturer(
    manufacturer_id: int,
    _admin: _AdminGuard,
    repo: Annotated[ManufacturerRepository, Depends(get_manufacturer_repository)],
) -> ManufacturerRead:
    m = await repo.get_by_id(manufacturer_id)
    if m is None:
        raise NotFoundError(code="manufacturer_not_found")
    return ManufacturerRead.model_validate(m)


@router.patch("/{manufacturer_id}", response_model=ManufacturerRead)
async def update_manufacturer(
    manufacturer_id: int,
    payload: ManufacturerUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
) -> ManufacturerRead:
    m = await service.update_manufacturer(
        manufacturer_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return ManufacturerRead.model_validate(m)


@router.delete(
    "/{manufacturer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_manufacturer(
    manufacturer_id: int,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
) -> None:
    await service.delete_manufacturer(
        manufacturer_id,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
