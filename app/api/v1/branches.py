"""Customer storefront — branches list (footer / "About us")."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_storefront_catalog_service
from app.domain.catalog.storefront import StorefrontCatalogService
from app.domain.catalog.storefront_schemas import StorefrontBranch

router = APIRouter(prefix="/branches", tags=["storefront"])


@router.get("", response_model=list[StorefrontBranch])
async def list_branches(
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
) -> list[StorefrontBranch]:
    branches = await service.list_active_branches()
    return [
        StorefrontBranch(
            id=b.id,
            code=b.code,
            name=b.name,
            address=b.address,
            city=b.city,
            phone=b.phone,
            timezone=b.timezone,
            opens_at=b.opens_at.isoformat() if b.opens_at else None,
            closes_at=b.closes_at.isoformat() if b.closes_at else None,
        )
        for b in branches
    ]
