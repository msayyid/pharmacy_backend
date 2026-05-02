"""Catalog domain — Pydantic schemas.

Per BACKEND §10:

* ``XxxCreate`` — request body for POST.
* ``XxxUpdate`` — PATCH-shape, all fields optional, ``extra="forbid"``.
* ``XxxRead`` — response body, ``from_attributes=True``.

Storefront-specific schemas (``ProductDetail`` with computed price + stock,
search-result shape) land in Phase 7.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── Manufacturers ───────────────────────────────────────────────────────────


class ManufacturerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=160)]
    country_code: Annotated[str | None, Field(max_length=2)] = None
    website: Annotated[str | None, Field(max_length=255)] = None
    is_active: bool = True


class ManufacturerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str | None, Field(max_length=160)] = None
    country_code: Annotated[str | None, Field(max_length=2)] = None
    website: Annotated[str | None, Field(max_length=255)] = None
    is_active: bool | None = None


class ManufacturerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    country_code: str | None = None
    website: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ─── Active ingredients ──────────────────────────────────────────────────────


class ActiveIngredientTranslationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: Literal["ru", "ky", "en"]
    name: Annotated[str, Field(min_length=1, max_length=160)]
    synonyms: list[str] = Field(default_factory=list)


class ActiveIngredientTranslationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language_code: str
    name: str
    synonyms: list[str]


class ActiveIngredientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inn_name: Annotated[str, Field(min_length=1, max_length=160)]
    translations: list[ActiveIngredientTranslationIn] = Field(default_factory=list)


class ActiveIngredientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inn_name: Annotated[str | None, Field(max_length=160)] = None
    # Translations replace policy: if provided, replaces the full set.
    translations: list[ActiveIngredientTranslationIn] | None = None


class ActiveIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inn_name: str
    translations: list[ActiveIngredientTranslationRead]
    created_at: datetime


# ─── Categories ──────────────────────────────────────────────────────────────


class CategoryTranslationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: Literal["ru", "ky", "en"]
    name: Annotated[str, Field(min_length=1, max_length=160)]
    description: str | None = None
    meta_title: Annotated[str | None, Field(max_length=160)] = None
    meta_description: Annotated[str | None, Field(max_length=320)] = None


class CategoryTranslationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language_code: str
    name: str
    description: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: int | None = None
    slug: Annotated[str | None, Field(max_length=120, pattern=r"^[a-z0-9-]+$")] = None
    icon_url: str | None = None
    sort_order: int = 0
    is_active: bool = True
    translations: list[CategoryTranslationIn] = Field(default_factory=list)


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: int | None = None
    slug: Annotated[str | None, Field(max_length=120, pattern=r"^[a-z0-9-]+$")] = None
    icon_url: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    translations: list[CategoryTranslationIn] | None = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: int | None = None
    slug: str
    icon_url: str | None = None
    sort_order: int
    is_active: bool
    translations: list[CategoryTranslationRead]
    created_at: datetime
    updated_at: datetime


# ─── Symptoms ────────────────────────────────────────────────────────────────


class SymptomTranslationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: Literal["ru", "ky", "en"]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    synonyms: list[str] = Field(default_factory=list)


class SymptomTranslationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language_code: str
    name: str
    synonyms: list[str]


class SymptomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: Annotated[str | None, Field(max_length=120, pattern=r"^[a-z0-9-]+$")] = None
    icon_url: str | None = None
    sort_order: int = 0
    is_active: bool = True
    translations: list[SymptomTranslationIn] = Field(default_factory=list)


class SymptomUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: Annotated[str | None, Field(max_length=120, pattern=r"^[a-z0-9-]+$")] = None
    icon_url: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    translations: list[SymptomTranslationIn] | None = None


class SymptomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    icon_url: str | None = None
    sort_order: int
    is_active: bool
    translations: list[SymptomTranslationRead]


# ─── Products ────────────────────────────────────────────────────────────────


_PRODUCT_FORMS = Literal[
    "tablet",
    "capsule",
    "syrup",
    "drops",
    "cream",
    "ointment",
    "gel",
    "spray",
    "inhaler",
    "injection",
    "suppository",
    "patch",
    "powder",
    "solution",
    "suspension",
    "lozenge",
    "other",
]
_DOSAGE_UNITS = Literal["mg", "g", "mcg", "ml", "IU", "%"]


class ProductTranslationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: Literal["ru", "ky", "en"]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    short_description: Annotated[str | None, Field(max_length=500)] = None
    description: str | None = None
    usage_instructions: str | None = None
    side_effects: str | None = None
    contraindications: str | None = None
    composition: str | None = None


class ProductTranslationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language_code: str
    name: str
    short_description: str | None = None
    description: str | None = None
    usage_instructions: str | None = None
    side_effects: str | None = None
    contraindications: str | None = None
    composition: str | None = None


class ProductImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    thumbnail_url: str | None = None
    medium_url: str | None = None
    large_url: str | None = None
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None
    sort_order: int
    is_primary: bool
    created_at: datetime


class ProductImageUpdate(BaseModel):
    """PATCH /admin/products/:id/images/:image_id"""

    model_config = ConfigDict(extra="forbid")
    is_primary: bool | None = None
    sort_order: int | None = None
    alt_text: Annotated[str | None, Field(max_length=255)] = None


class ProductActiveIngredientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_ingredient_id: int
    dosage_amount: Decimal
    dosage_unit: _DOSAGE_UNITS


class ProductActiveIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    active_ingredient_id: int
    dosage_amount: Decimal
    dosage_unit: str


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: Annotated[str, Field(min_length=1, max_length=40)]
    barcode: Annotated[str | None, Field(max_length=40)] = None
    slug: Annotated[str | None, Field(max_length=160, pattern=r"^[a-z0-9-]+$")] = (
        None  # auto-generated from RU translation if absent
    )
    manufacturer_id: int | None = None
    category_id: int

    form: _PRODUCT_FORMS = "other"
    pack_size_label: Annotated[str | None, Field(max_length=60)] = None
    pack_quantity: Decimal | None = None
    pack_unit: Annotated[str | None, Field(max_length=16)] = None

    requires_prescription: bool = False
    min_age: Annotated[int | None, Field(ge=0, le=120)] = None
    max_per_order: Annotated[int | None, Field(gt=0)] = None

    storage_temp_min_c: int | None = None
    storage_temp_max_c: int | None = None
    requires_cold_chain: bool = False
    weight_grams: Annotated[int | None, Field(ge=0)] = None

    attributes: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    is_featured: bool = False

    translations: list[ProductTranslationIn] = Field(default_factory=list)
    active_ingredients: list[ProductActiveIngredientIn] = Field(default_factory=list)
    symptom_ids: list[int] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barcode: str | None = None
    slug: Annotated[str | None, Field(max_length=160, pattern=r"^[a-z0-9-]+$")] = None
    manufacturer_id: int | None = None
    category_id: int | None = None

    form: _PRODUCT_FORMS | None = None
    pack_size_label: str | None = None
    pack_quantity: Decimal | None = None
    pack_unit: str | None = None

    requires_prescription: bool | None = None
    min_age: int | None = None
    max_per_order: int | None = None

    storage_temp_min_c: int | None = None
    storage_temp_max_c: int | None = None
    requires_cold_chain: bool | None = None
    weight_grams: int | None = None

    attributes: dict[str, Any] | None = None
    is_active: bool | None = None
    is_featured: bool | None = None

    # Replace policy: if provided, replaces full set.
    translations: list[ProductTranslationIn] | None = None
    active_ingredients: list[ProductActiveIngredientIn] | None = None
    symptom_ids: list[int] | None = None


class ProductRead(BaseModel):
    """Full product view for admin endpoints."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str
    barcode: str | None = None
    slug: str
    manufacturer_id: int | None = None
    category_id: int

    form: str
    pack_size_label: str | None = None
    pack_quantity: Decimal | None = None
    pack_unit: str | None = None

    requires_prescription: bool
    min_age: int | None = None
    max_per_order: int | None = None
    storage_temp_min_c: int | None = None
    storage_temp_max_c: int | None = None
    requires_cold_chain: bool
    weight_grams: int | None = None

    attributes: dict[str, Any]
    is_active: bool
    is_featured: bool

    translations: list[ProductTranslationRead]
    images: list[ProductImageRead]
    active_ingredients: list[ProductActiveIngredientRead]
    symptom_ids: list[int]

    created_at: datetime
    updated_at: datetime


class ProductListItem(BaseModel):
    """Slim shape for list endpoints."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str
    slug: str
    form: str
    is_active: bool
    is_featured: bool
    manufacturer_id: int | None = None
    category_id: int
    created_at: datetime


# ─── Bulk import ──────────────────────────────────────────────────────────────


class BulkImportRowError(BaseModel):
    """One row-level error from CSV/XLSX import dry-run."""

    row: int  # 1-indexed line number (excluding header)
    sku: str | None = None
    field: str | None = None
    message: str


class BulkImportSummary(BaseModel):
    """Result of dry-run or apply."""

    n_rows: int
    n_create: int
    n_update: int
    n_skip: int
    errors: list[BulkImportRowError] = Field(default_factory=list)


# ─── Admin audit log read (for Phase 9 viewer; expose now for tests) ─────────


class AdminAuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    admin_user_id: int | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    changes: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
