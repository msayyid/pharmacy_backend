"""Customer storefront — categories (tree + browse).

* ``GET /api/v1/categories``                   — full active tree (cached)
* ``GET /api/v1/categories/{slug}``            — detail + breadcrumb
* ``GET /api/v1/categories/{slug}/products``   — paginated products list
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
    CategoryDetail,
    CategoryNode,
    StorefrontProductsPage,
)

router = APIRouter(prefix="/categories", tags=["storefront"])


@router.get("", response_model=list[CategoryNode])
async def categories_tree(
    lang: LangDep,
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
) -> list[CategoryNode]:
    return await service.get_categories_tree(language_code=lang)


@router.get("/{slug}", response_model=CategoryDetail)
async def category_detail(
    slug: str,
    lang: LangDep,
    branch_id: BranchIdDep,
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
) -> CategoryDetail:
    detail, _products = await service.get_category_with_products(
        slug=slug,
        language_code=lang,
        branch_id=branch_id,
        page=1,
        page_size=1,
    )
    return detail


@router.get("/{slug}/products", response_model=StorefrontProductsPage)
async def category_products(
    slug: str,
    lang: LangDep,
    branch_id: BranchIdDep,
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
    in_stock_only: bool = True,
    manufacturer_id: int | None = None,
    sort: Annotated[
        str,
        Query(pattern=r"^(relevance|price_asc|price_desc|name|newest)$"),
    ] = "relevance",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> StorefrontProductsPage:
    _detail, products = await service.get_category_with_products(
        slug=slug,
        language_code=lang,
        branch_id=branch_id,
        in_stock_only=in_stock_only,
        manufacturer_id=manufacturer_id,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return products
