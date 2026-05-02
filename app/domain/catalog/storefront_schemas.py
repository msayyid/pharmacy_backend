"""Storefront response schemas — the customer-facing read models.

These are deliberately separate from the admin schemas
(``app/domain/catalog/schemas.py``):

* Admin shapes carry full translations + audit-relevant fields and
  return Decimal at full precision.
* Storefront shapes carry one ``name`` (the resolved language) plus an
  ``is_in_stock`` flag the UI uses to disable the CTA.

Reference: PRODUCT_BLUEPRINT.md §8.2 (F-CAT-001..008); BACKEND_BLUEPRINT.md §10.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── Categories ──────────────────────────────────────────────────────────────


class CategoryNode(BaseModel):
    """A node in the storefront category tree."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    icon_url: str | None = None
    sort_order: int
    children: list[Self] = Field(default_factory=list)


class BreadcrumbItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str


class CategoryDetail(BaseModel):
    """Single category + breadcrumb for the category page header."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    description: str | None = None
    icon_url: str | None = None
    breadcrumb: list[BreadcrumbItem] = Field(default_factory=list)


# ─── Products ────────────────────────────────────────────────────────────────


class StorefrontProductCard(BaseModel):
    """Slim product shape for category / search / suggest lists.

    ``score`` is populated only by the search endpoint — informational.
    """

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str
    slug: str
    form: str
    is_featured: bool
    name: str
    short_description: str | None = None
    price: Decimal
    compare_at_price: Decimal | None = None
    currency: str
    is_in_stock: bool
    thumbnail_url: str | None = None
    score: float | None = None


class StorefrontIngredient(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inn_name: str
    name: str | None = None  # localised
    dosage_amount: Decimal | None = None
    dosage_unit: str | None = None


class StorefrontSymptomTag(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str


class StorefrontImage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    thumbnail_url: str | None = None
    medium_url: str | None = None
    large_url: str | None = None
    alt_text: str | None = None
    is_primary: bool


class StorefrontProductDetail(BaseModel):
    """Full product page shape (PRODUCT §F-CAT-003)."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str
    slug: str
    form: str
    pack_size_label: str | None = None

    name: str
    short_description: str | None = None
    description: str | None = None
    usage_instructions: str | None = None
    side_effects: str | None = None
    contraindications: str | None = None
    composition: str | None = None

    manufacturer_id: int | None = None
    manufacturer_name: str | None = None
    manufacturer_country: str | None = None

    category_id: int
    category_slug: str
    category_name: str

    requires_prescription: bool
    requires_cold_chain: bool

    price: Decimal
    compare_at_price: Decimal | None = None
    currency: str
    is_in_stock: bool

    active_ingredients: list[StorefrontIngredient]
    symptoms: list[StorefrontSymptomTag]
    images: list[StorefrontImage]


# ─── Symptoms ────────────────────────────────────────────────────────────────


class StorefrontSymptom(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    icon_url: str | None = None
    sort_order: int


class StorefrontSymptomDetail(StorefrontSymptom):
    description: str | None = None
    synonyms: list[str] = Field(default_factory=list)


# ─── Branches ────────────────────────────────────────────────────────────────


class StorefrontBranch(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    address: str
    city: str
    phone: str | None = None
    timezone: str
    opens_at: str | None = None
    closes_at: str | None = None


# ─── Search & Suggest ────────────────────────────────────────────────────────


class SuggestProductMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    name: str
    price: Decimal
    currency: str
    thumbnail_url: str | None = None


class SuggestCategoryMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str


class SuggestSymptomMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str


class SuggestResponse(BaseModel):
    products: list[SuggestProductMini] = Field(default_factory=list)
    categories: list[SuggestCategoryMini] = Field(default_factory=list)
    symptoms: list[SuggestSymptomMini] = Field(default_factory=list)


class SearchResultPage(BaseModel):
    """Search response. Mirrors :class:`Page` but adds search-only fields."""

    items: list[StorefrontProductCard]
    total: int
    page: int
    page_size: int
    synonyms_used: list[str] = Field(default_factory=list)
    popular_searches: list[str] = Field(default_factory=list)


# ─── Branches list query ─────────────────────────────────────────────────────


class StorefrontProductsPage(BaseModel):
    """Generic paginated product list (category / symptom / search-without-scoring)."""

    items: list[StorefrontProductCard]
    total: int
    page: int
    page_size: int


# ─── Sort enum (for /categories/{slug}/products) ─────────────────────────────


SortLiteral = Annotated[
    str,
    Field(pattern=r"^(relevance|price_asc|price_desc|name|newest)$"),
]


# ─── Re-export helpers (date type for symptom_translations.synonyms) ────────


__all__ = [
    "BreadcrumbItem",
    "CategoryDetail",
    "CategoryNode",
    "SearchResultPage",
    "SortLiteral",
    "StorefrontBranch",
    "StorefrontImage",
    "StorefrontIngredient",
    "StorefrontProductCard",
    "StorefrontProductDetail",
    "StorefrontProductsPage",
    "StorefrontSymptom",
    "StorefrontSymptomDetail",
    "StorefrontSymptomTag",
    "SuggestCategoryMini",
    "SuggestProductMini",
    "SuggestResponse",
    "SuggestSymptomMini",
    "_date",  # silence "imported but unused" — date type used by callers
]
