"""Customer storefront — symptoms (list + browse).

* ``GET /api/v1/symptoms``                  — active symptoms list
* ``GET /api/v1/symptoms/{slug}/products``  — paginated products tagged
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    BranchIdDep,
    LangDep,
    get_storefront_catalog_service,
)
from app.domain.catalog.storefront import StorefrontCatalogService
from app.domain.catalog.storefront_schemas import (
    StorefrontProductsPage,
    StorefrontSymptom,
)

router = APIRouter(prefix="/symptoms", tags=["storefront"])


@router.get("", response_model=list[StorefrontSymptom])
async def list_symptoms(
    lang: LangDep,
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
) -> list[StorefrontSymptom]:
    return await service.list_active_symptoms(language_code=lang)


@router.get("/{slug}/products", response_model=StorefrontProductsPage)
async def symptom_products(
    slug: str,
    lang: LangDep,
    branch_id: BranchIdDep,
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
    in_stock_only: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> StorefrontProductsPage:
    _symptom, products = await service.get_symptom_with_products(
        slug=slug,
        language_code=lang,
        branch_id=branch_id,
        in_stock_only=in_stock_only,
        page=page,
        page_size=page_size,
    )
    return products
