"""Admin symptoms — ``/api/admin/v1/symptoms``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import get_catalog_admin_service, get_symptom_repository
from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.domain.catalog.repositories import SymptomRepository
from app.domain.catalog.schemas import (
    SymptomCreate,
    SymptomRead,
    SymptomUpdate,
)
from app.domain.catalog.services import CatalogAdminService
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser

router = APIRouter(prefix="/symptoms", tags=["admin-catalog"])

_AdminGuard = Annotated[AdminUser, Depends(require_role("super_admin", "content_editor"))]


@router.get("", response_model=Page[SymptomRead])
async def list_symptoms(
    _admin: _AdminGuard,
    repo: Annotated[SymptomRepository, Depends(get_symptom_repository)],
    active_only: bool = Query(default=False),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
) -> Page[SymptomRead]:
    items, total = await repo.list_paginated(
        offset=(page - 1) * page_size,
        limit=page_size,
        active_only=active_only,
    )
    return Page[SymptomRead](
        items=[SymptomRead.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=SymptomRead, status_code=status.HTTP_201_CREATED)
async def create_symptom(
    payload: SymptomCreate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
    repo: Annotated[SymptomRepository, Depends(get_symptom_repository)],
) -> SymptomRead:
    s = await service.create_symptom(
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_translations(s.id)
    assert full is not None
    return SymptomRead.model_validate(full)


@router.get("/{symptom_id}", response_model=SymptomRead)
async def get_symptom(
    symptom_id: int,
    _admin: _AdminGuard,
    repo: Annotated[SymptomRepository, Depends(get_symptom_repository)],
) -> SymptomRead:
    s = await repo.get_by_id_with_translations(symptom_id)
    if s is None:
        raise NotFoundError(code="symptom_not_found")
    return SymptomRead.model_validate(s)


@router.patch("/{symptom_id}", response_model=SymptomRead)
async def update_symptom(
    symptom_id: int,
    payload: SymptomUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
    repo: Annotated[SymptomRepository, Depends(get_symptom_repository)],
) -> SymptomRead:
    await service.update_symptom(
        symptom_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_translations(symptom_id)
    assert full is not None
    return SymptomRead.model_validate(full)
