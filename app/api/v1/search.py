"""Customer storefront — search + autocomplete suggest.

* ``GET /api/v1/search``           — full search with composite ranking
* ``GET /api/v1/search/suggest``   — autocomplete (cached 60s)

``q`` length ≥ 2 is enforced. ``in_stock_only`` defaults to ``true``
(PRODUCT §F-CAT-008).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    BranchIdDep,
    LangDep,
    get_search_service,
)
from app.domain.catalog.search import SearchService
from app.domain.catalog.storefront_schemas import (
    SearchResultPage,
    SuggestResponse,
)
from app.domain.identity.dependencies import OptionalCurrentUser

router = APIRouter(tags=["storefront"])


@router.get("/search", response_model=SearchResultPage)
async def search(
    lang: LangDep,
    branch_id: BranchIdDep,
    service: Annotated[SearchService, Depends(get_search_service)],
    user: OptionalCurrentUser,
    q: Annotated[str, Query(min_length=2)],
    in_stock_only: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> SearchResultPage:
    return await service.search(
        q=q,
        language_code=lang,
        branch_id=branch_id,
        in_stock_only=in_stock_only,
        page=page,
        page_size=page_size,
        user_id=user.id if user is not None else None,
    )


@router.get("/search/suggest", response_model=SuggestResponse)
async def search_suggest(
    lang: LangDep,
    branch_id: BranchIdDep,
    service: Annotated[SearchService, Depends(get_search_service)],
    q: Annotated[str, Query(min_length=2)],
) -> SuggestResponse:
    return await service.suggest(q=q, language_code=lang, branch_id=branch_id)
