"""Customer storefront — product detail + substitutes ("related").

* ``GET /api/v1/products/{slug}``           — full detail (cached 5m)
* ``GET /api/v1/products/{slug}/related``   — same primary AI + dose, ≤ 4
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    BranchIdDep,
    LangDep,
    get_storefront_catalog_service,
)
from app.core.errors import NotFoundError
from app.domain.catalog.storefront import StorefrontCatalogService
from app.domain.catalog.storefront_schemas import (
    StorefrontProductCard,
    StorefrontProductDetail,
)

router = APIRouter(prefix="/products", tags=["storefront"])


@router.get("/{slug}", response_model=StorefrontProductDetail)
async def product_detail(
    slug: str,
    lang: LangDep,
    branch_id: BranchIdDep,
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
) -> StorefrontProductDetail:
    return await service.get_product_detail(slug=slug, language_code=lang, branch_id=branch_id)


@router.get("/{slug}/related", response_model=list[StorefrontProductCard])
async def related_products(
    slug: str,
    lang: LangDep,
    branch_id: BranchIdDep,
    service: Annotated[StorefrontCatalogService, Depends(get_storefront_catalog_service)],
) -> list[StorefrontProductCard]:
    """Up to 4 substitutes (same primary AI + dose, in stock).

    The endpoint takes the product *slug*, but the substitute query
    needs the product id — fetch the detail (cache hit on a hot
    product) and pass id through.
    """
    detail = await service.get_product_detail(slug=slug, language_code=lang, branch_id=branch_id)
    if detail is None:  # pragma: no cover — get_product_detail raises NotFound
        raise NotFoundError(code="product_not_found", slug=slug)
    return await service.list_substitutes(
        product_id=detail.id, branch_id=branch_id, language_code=lang
    )
