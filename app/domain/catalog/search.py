"""Search service — synonym expansion + composite-ranked search + suggest.

Composite ranking weights (PRODUCT §12.2 — DECISION_LOG'd):

* exact name match           → 1000
* name prefix                → 500
* FULLTEXT MATCH score x 10  → fuzzy / typo / multi-word
* active ingredient match    → 50
* symptom-tag match          → 30
* manufacturer match         → 20

Within tier: ``is_featured DESC``, then ``created_at DESC``.

Synonym expansion is application-side (PRODUCT §12.4). The dictionary
lives at ``app/i18n/synonyms_ru.json`` and is loaded once per service
instance. Phase 9 will add an admin UI; for Phase 7 the file is the
source of truth.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.cache import cache_get_or_set
from app.core.errors import ValidationError
from app.domain.catalog.repositories import (
    CategoryRepository,
    ProductRepository,
    StorefrontProductRow,
    SymptomRepository,
)
from app.domain.catalog.storefront_schemas import (
    SearchResultPage,
    StorefrontProductCard,
    SuggestCategoryMini,
    SuggestProductMini,
    SuggestResponse,
    SuggestSymptomMini,
)
from app.domain.ops.repositories import SearchLogRepository

MIN_QUERY_LENGTH = 2
SUGGEST_TTL = 60
DEFAULT_PAGE_SIZE = 24


def suggest_cache_key(language_code: str, q: str) -> str:
    return f"v1:search:suggest:{language_code}:{q.lower()}"


_SYNONYMS_PATH = Path(__file__).resolve().parents[2] / "i18n" / "synonyms_ru.json"


def _load_synonyms() -> dict[str, list[str]]:
    raw = json.loads(_SYNONYMS_PATH.read_text())
    # Drop ``_doc`` / ``_xxx`` annotation keys.
    return {
        k.lower(): [s.lower() for s in v]
        for k, v in raw.items()
        if not k.startswith("_") and isinstance(v, list)
    }


# Pre-compiled at module import so every search avoids re-loading.
_SYNONYMS = _load_synonyms()


# Splits a query into "word"-ish tokens (Cyrillic + Latin + digits).
_WORD_RE = re.compile(r"[\w]+", flags=re.UNICODE)


class SearchService:
    def __init__(
        self,
        *,
        products: ProductRepository,
        categories: CategoryRepository,
        symptoms: SymptomRepository,
        search_log: SearchLogRepository,
    ) -> None:
        self.products = products
        self.categories = categories
        self.symptoms = symptoms
        self.search_log = search_log
        self._synonyms = _SYNONYMS  # exposed for tests

    # ─── Search ────────────────────────────────────────────────────────────

    async def search(
        self,
        *,
        q: str,
        language_code: str,
        branch_id: int,
        in_stock_only: bool = True,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        user_id: UUID | None = None,
    ) -> SearchResultPage:
        normalised = q.strip().lower()
        if len(normalised) < MIN_QUERY_LENGTH:
            raise ValidationError(code="query_too_short", min_length=MIN_QUERY_LENGTH)

        synonyms_used = self._expand_synonyms(normalised)
        boolean_query = self._build_boolean_query(normalised, synonyms_used)

        rows, total = await self.products.storefront_search(
            boolean_query=boolean_query,
            language_code=language_code,
            branch_id=branch_id,
            in_stock_only=in_stock_only,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

        # Persist for analytics (catalog-gap signal on zero results).
        await self.search_log.append(
            query=normalised,
            language_code=language_code,
            user_id=user_id,
            results_count=total,
        )

        popular: list[str] = []
        if total == 0:
            popular = list(
                await self.search_log.popular_queries(limit=5, language_code=language_code)
            )

        return SearchResultPage(
            items=[_row_to_card(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
            synonyms_used=sorted(synonyms_used),
            popular_searches=popular,
        )

    # ─── Suggest (autocomplete) ────────────────────────────────────────────

    async def suggest(
        self,
        *,
        q: str,
        language_code: str,
        branch_id: int,
    ) -> SuggestResponse:
        normalised = q.strip().lower()
        if len(normalised) < MIN_QUERY_LENGTH:
            return SuggestResponse()

        async def _loader() -> dict[str, Any]:
            products = await self.products.suggest(
                prefix=normalised,
                language_code=language_code,
                branch_id=branch_id,
                limit=4,
            )
            categories = await self._suggest_categories(normalised, language_code)
            symptoms = await self._suggest_symptoms(normalised, language_code)
            return SuggestResponse(
                products=[
                    SuggestProductMini(
                        id=r.product_id,
                        slug=r.slug,
                        name=r.name,
                        price=r.price,
                        currency=r.currency,
                        thumbnail_url=r.thumbnail_url,
                    )
                    for r in products
                ],
                categories=categories,
                symptoms=symptoms,
            ).model_dump(mode="json")

        cached = await cache_get_or_set(
            suggest_cache_key(language_code, normalised),
            SUGGEST_TTL,
            _loader,
        )
        return SuggestResponse.model_validate(cached)

    # ─── Internals ─────────────────────────────────────────────────────────

    def _expand_synonyms(self, normalised_query: str) -> set[str]:
        """Return the set of synonym values to OR into the boolean query.

        Matches in two ways:

        * Whole-query phrase match (``"от головы"`` → ``["головная боль", "обезболивающее"]``).
        * Per-token match (``"анальгин"`` in a longer query still expands).
        """
        out: set[str] = set()
        # Phrase-level lookup first.
        if normalised_query in self._synonyms:
            out.update(self._synonyms[normalised_query])
        # Token-level fallback.
        for token in _WORD_RE.findall(normalised_query):
            if token in self._synonyms:
                out.update(self._synonyms[token])
        return out

    def _build_boolean_query(self, normalised_query: str, synonyms: set[str]) -> str:
        """Compose a MySQL FULLTEXT BOOLEAN-mode query for the ngram parser.

        With the ngram parser, ``*`` is treated as a literal character —
        not a wildcard — so we omit it. Default operator (whitespace) =
        OR. Synonym terms are appended as OR-tokens, all lower-cased.

        Reference: BACKEND_BLUEPRINT.md §6.4; MySQL Reference Manual
        12.10.9 ("ngram Full-Text Parser").
        """
        tokens = _WORD_RE.findall(normalised_query)
        if not tokens:
            tokens = [normalised_query]
        primary = " ".join(t for t in tokens if t)
        synonym_terms = " ".join(w for syn in synonyms for w in _WORD_RE.findall(syn) if w)
        return f"{primary} {synonym_terms}".strip()

    async def _suggest_categories(
        self, normalised_query: str, language_code: str
    ) -> list[SuggestCategoryMini]:
        cats = await self.categories.list_active_tree()
        out: list[SuggestCategoryMini] = []
        for c in cats:
            name = _first_translation_match(c.translations, language_code, normalised_query)
            if name is not None:
                out.append(SuggestCategoryMini(id=c.id, slug=c.slug, name=name))
            if len(out) >= 2:  # noqa: PLR2004 — spec: 2 categories
                break
        return out

    async def _suggest_symptoms(
        self, normalised_query: str, language_code: str
    ) -> list[SuggestSymptomMini]:
        syms = await self.symptoms.list_active_with_translations()
        out: list[SuggestSymptomMini] = []
        for s in syms:
            name = _first_translation_match(s.translations, language_code, normalised_query)
            if name is not None:
                out.append(SuggestSymptomMini(id=s.id, slug=s.slug, name=name))
            if len(out) >= 2:  # noqa: PLR2004 — spec: 2 symptoms
                break
        return out


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _first_translation_match(
    translations: Sequence[Any],
    language_code: str,
    normalised_query: str,
) -> str | None:
    """If any translation in this row's translations starts with the
    query (or contains it), return the localised name; else ``None``.
    """
    candidates = [t for t in translations if t.language_code == language_code]
    if not candidates:
        candidates = [t for t in translations if t.language_code == "ru"]
    if not candidates:
        candidates = list(translations)
    for t in candidates:
        name_lower = (t.name or "").lower()
        if name_lower.startswith(normalised_query) or normalised_query in name_lower:
            return str(t.name)
    return None


def _row_to_card(r: StorefrontProductRow) -> StorefrontProductCard:
    return StorefrontProductCard(
        id=r.product_id,
        sku=r.sku,
        slug=r.slug,
        form=r.form,
        is_featured=r.is_featured,
        name=r.name,
        short_description=r.short_description,
        price=r.price,
        compare_at_price=r.compare_at_price,
        currency=r.currency,
        is_in_stock=r.is_in_stock,
        thumbnail_url=r.thumbnail_url,
        score=r.score,
    )
