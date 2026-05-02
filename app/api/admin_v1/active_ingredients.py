"""Admin active ingredients — ``/api/admin/v1/active-ingredients``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import (
    get_active_ingredient_repository,
    get_catalog_admin_service,
)
from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.domain.catalog.repositories import ActiveIngredientRepository
from app.domain.catalog.schemas import (
    ActiveIngredientCreate,
    ActiveIngredientRead,
    ActiveIngredientUpdate,
)
from app.domain.catalog.services import CatalogAdminService
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser

router = APIRouter(prefix="/active-ingredients", tags=["admin-catalog"])

_AdminGuard = Annotated[AdminUser, Depends(require_role("super_admin", "content_editor"))]


@router.get("", response_model=Page[ActiveIngredientRead])
async def list_ingredients(
    _admin: _AdminGuard,
    repo: Annotated[ActiveIngredientRepository, Depends(get_active_ingredient_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
    q: str | None = None,
) -> Page[ActiveIngredientRead]:
    items, total = await repo.list_paginated(offset=(page - 1) * page_size, limit=page_size, q=q)
    return Page[ActiveIngredientRead](
        items=[ActiveIngredientRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=ActiveIngredientRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ingredient(
    payload: ActiveIngredientCreate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
    repo: Annotated[ActiveIngredientRepository, Depends(get_active_ingredient_repository)],
) -> ActiveIngredientRead:
    ai = await service.create_ingredient(
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_translations(ai.id)
    assert full is not None
    return ActiveIngredientRead.model_validate(full)


@router.get("/{ingredient_id}", response_model=ActiveIngredientRead)
async def get_ingredient(
    ingredient_id: int,
    _admin: _AdminGuard,
    repo: Annotated[ActiveIngredientRepository, Depends(get_active_ingredient_repository)],
) -> ActiveIngredientRead:
    ai = await repo.get_by_id_with_translations(ingredient_id)
    if ai is None:
        raise NotFoundError(code="ingredient_not_found")
    return ActiveIngredientRead.model_validate(ai)


@router.patch("/{ingredient_id}", response_model=ActiveIngredientRead)
async def update_ingredient(
    ingredient_id: int,
    payload: ActiveIngredientUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
    repo: Annotated[ActiveIngredientRepository, Depends(get_active_ingredient_repository)],
) -> ActiveIngredientRead:
    await service.update_ingredient(
        ingredient_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_translations(ingredient_id)
    assert full is not None
    return ActiveIngredientRead.model_validate(full)
