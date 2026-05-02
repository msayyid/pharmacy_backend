"""Admin categories — ``/api/admin/v1/categories``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import get_catalog_admin_service, get_category_repository
from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.domain.catalog.repositories import CategoryRepository
from app.domain.catalog.schemas import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
)
from app.domain.catalog.services import CatalogAdminService
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser

router = APIRouter(prefix="/categories", tags=["admin-catalog"])

_AdminGuard = Annotated[AdminUser, Depends(require_role("super_admin", "content_editor"))]


@router.get("", response_model=Page[CategoryRead])
async def list_categories(
    _admin: _AdminGuard,
    repo: Annotated[CategoryRepository, Depends(get_category_repository)],
    parent_id: int | None = Query(default=None),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Page[CategoryRead]:
    items, total = await repo.list_paginated(
        parent_id=parent_id,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[CategoryRead](
        items=[CategoryRead.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
    repo: Annotated[CategoryRepository, Depends(get_category_repository)],
) -> CategoryRead:
    c = await service.create_category(
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_translations(c.id)
    assert full is not None
    return CategoryRead.model_validate(full)


@router.get("/{category_id}", response_model=CategoryRead)
async def get_category(
    category_id: int,
    _admin: _AdminGuard,
    repo: Annotated[CategoryRepository, Depends(get_category_repository)],
) -> CategoryRead:
    c = await repo.get_by_id_with_translations(category_id)
    if c is None:
        raise NotFoundError(code="category_not_found")
    return CategoryRead.model_validate(c)


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
    repo: Annotated[CategoryRepository, Depends(get_category_repository)],
) -> CategoryRead:
    await service.update_category(
        category_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_translations(category_id)
    assert full is not None
    return CategoryRead.model_validate(full)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_category(
    category_id: int,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
) -> None:
    await service.delete_category(
        category_id,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
