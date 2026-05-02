"""Catalog domain — manufacturers, ingredients, categories, symptoms, products.

11 models map onto the PHARMACY §5 schema (Postgres-flavoured) with the
MySQL adaptations from BACKEND §6:

* :class:`Manufacturer`
* :class:`ActiveIngredient` + :class:`ActiveIngredientTranslation`
* :class:`Category` + :class:`CategoryTranslation`
* :class:`Symptom` + :class:`SymptomTranslation`
* :class:`Product` + :class:`ProductTranslation` + :class:`ProductImage`
* :class:`ProductActiveIngredient` (M:N with dosage)
* :class:`ProductSymptom` (M:N)

Notable adaptations:

* ``synonyms`` is ``JSON`` (default ``[]``) — MySQL has no array type;
  application reads it as a Python ``list``. Phase 0 OPEN_QUESTIONS Q8.
* ``product_translations`` carries a FULLTEXT index ``ftx_pt_search`` over
  ``(name, short_description, description)`` ``WITH PARSER ngram`` — the
  parser clause is added via ``op.execute`` in the migration (BACKEND §9.4).
* ``product_images.is_primary`` uniqueness uses the BACKEND §6.5 generated-
  column trick (``primary_product_id`` UNIQUE).
* ``product_images.product_id`` FK uses ``ON DELETE RESTRICT`` (not CASCADE)
  because MySQL forbids STORED generated columns on FK-CASCADE columns
  (same Phase 4 finding as ``user_addresses``). ORM cascade handles cleanup.

Reference: PHARMACY_BLUEPRINT_2.md §5; BACKEND_BLUEPRINT.md §6, §8.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BINARY, DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, SoftDeleteMixin, TimestampMixin
from app.core.types import GUID

# ─── Enums (mapped to String(32) + CHECK) ────────────────────────────────────


class ProductForm(StrEnum):
    TABLET = "tablet"
    CAPSULE = "capsule"
    SYRUP = "syrup"
    DROPS = "drops"
    CREAM = "cream"
    OINTMENT = "ointment"
    GEL = "gel"
    SPRAY = "spray"
    INHALER = "inhaler"
    INJECTION = "injection"
    SUPPOSITORY = "suppository"
    PATCH = "patch"
    POWDER = "powder"
    SOLUTION = "solution"
    SUSPENSION = "suspension"
    LOZENGE = "lozenge"
    OTHER = "other"


_PRODUCT_FORMS_SQL = (
    "form IN ('tablet','capsule','syrup','drops','cream','ointment','gel',"
    "'spray','inhaler','injection','suppository','patch','powder',"
    "'solution','suspension','lozenge','other')"
)


class DosageUnit(StrEnum):
    MG = "mg"
    G = "g"
    MCG = "mcg"
    ML = "ml"
    IU = "IU"
    PERCENT = "%"


_DOSAGE_UNITS_SQL = "dosage_unit IN ('mg','g','mcg','ml','IU','%')"


_LANG_CHECK_SQL = "language_code IN ('ru','ky','en')"

_MYSQL_TABLE_KW = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


# ─── Manufacturers ───────────────────────────────────────────────────────────


class Manufacturer(Base, TimestampMixin):
    __tablename__ = "manufacturers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    website: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("name", name="uq_manufacturers_name"),
        Index("idx_manufacturers_active", "is_active"),
        _MYSQL_TABLE_KW,
    )


# ─── Active ingredients ──────────────────────────────────────────────────────


class ActiveIngredient(Base, TimestampMixin):
    __tablename__ = "active_ingredients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inn_name: Mapped[str] = mapped_column(String(160), nullable=False)

    translations: Mapped[list[ActiveIngredientTranslation]] = relationship(
        back_populates="active_ingredient",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("inn_name", name="uq_active_ingredients_inn"),
        _MYSQL_TABLE_KW,
    )


class ActiveIngredientTranslation(Base):
    __tablename__ = "active_ingredient_translations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    active_ingredient_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "active_ingredients.id",
            name="fk_ai_trans_ingredient",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # MySQL has no array type — store as JSON list; default empty list.
    synonyms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    active_ingredient: Mapped[ActiveIngredient] = relationship(
        back_populates="translations", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint("active_ingredient_id", "language_code", name="uq_ai_trans_lang"),
        CheckConstraint(_LANG_CHECK_SQL, name="chk_ai_trans_lang"),
        _MYSQL_TABLE_KW,
    )


# ─── Categories ──────────────────────────────────────────────────────────────


class Category(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("categories.id", name="fk_categories_parent", ondelete="RESTRICT"),
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    icon_url: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    translations: Mapped[list[CategoryTranslation]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_categories_slug"),
        Index("idx_categories_parent", "parent_id"),
        Index("idx_categories_active_sort", "is_active", "sort_order"),
        # NOTE: PHARMACY §5.1 had ``CHECK (parent_id IS NULL OR parent_id <> id)``
        # but MySQL 8.0+ forbids CHECK constraints that reference AUTO_INCREMENT
        # columns (error 3818). Self-parent prevention is enforced in the
        # service layer instead. See DECISION_LOG.
        _MYSQL_TABLE_KW,
    )


class CategoryTranslation(Base):
    __tablename__ = "category_translations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("categories.id", name="fk_cat_trans_category", ondelete="CASCADE"),
        nullable=False,
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    meta_title: Mapped[str | None] = mapped_column(String(160))
    meta_description: Mapped[str | None] = mapped_column(String(320))

    category: Mapped[Category] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("category_id", "language_code", name="uq_cat_trans_lang"),
        CheckConstraint(_LANG_CHECK_SQL, name="chk_cat_trans_lang"),
        _MYSQL_TABLE_KW,
    )


# ─── Symptoms ────────────────────────────────────────────────────────────────


class Symptom(Base, TimestampMixin):
    __tablename__ = "symptoms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    icon_url: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    translations: Mapped[list[SymptomTranslation]] = relationship(
        back_populates="symptom",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_symptoms_slug"),
        Index("idx_symptoms_active_sort", "is_active", "sort_order"),
        _MYSQL_TABLE_KW,
    )


class SymptomTranslation(Base):
    __tablename__ = "symptom_translations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symptom_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("symptoms.id", name="fk_sym_trans_symptom", ondelete="CASCADE"),
        nullable=False,
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    symptom: Mapped[Symptom] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("symptom_id", "language_code", name="uq_sym_trans_lang"),
        CheckConstraint(_LANG_CHECK_SQL, name="chk_sym_trans_lang"),
        _MYSQL_TABLE_KW,
    )


# ─── Products ────────────────────────────────────────────────────────────────


class Product(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(40))
    slug: Mapped[str] = mapped_column(String(160), nullable=False)

    manufacturer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "manufacturers.id",
            name="fk_products_manufacturer",
            ondelete="RESTRICT",
        ),
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("categories.id", name="fk_products_category", ondelete="RESTRICT"),
        nullable=False,
    )

    form: Mapped[str] = mapped_column(String(32), nullable=False, default=ProductForm.OTHER.value)
    pack_size_label: Mapped[str | None] = mapped_column(String(60))
    pack_quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    pack_unit: Mapped[str | None] = mapped_column(String(16))

    requires_prescription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_age: Mapped[int | None] = mapped_column(SmallInteger)
    max_per_order: Mapped[int | None] = mapped_column(SmallInteger)

    storage_temp_min_c: Mapped[int | None] = mapped_column(SmallInteger)
    storage_temp_max_c: Mapped[int | None] = mapped_column(SmallInteger)
    requires_cold_chain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight_grams: Mapped[int | None] = mapped_column(Integer)

    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships — all lazy="raise"; explicit loading required.
    translations: Mapped[list[ProductTranslation]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="raise"
    )
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="raise"
    )
    active_ingredients: Mapped[list[ProductActiveIngredient]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="raise"
    )
    symptoms: Mapped[list[ProductSymptom]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="raise"
    )
    manufacturer: Mapped[Manufacturer | None] = relationship(lazy="raise")
    category: Mapped[Category] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        UniqueConstraint("slug", name="uq_products_slug"),
        Index("idx_products_barcode", "barcode"),
        Index("idx_products_category_active", "category_id", "is_active"),
        Index("idx_products_manufacturer", "manufacturer_id"),
        Index("idx_products_featured", "is_featured", "created_at"),
        Index("idx_products_created_at", "created_at"),
        CheckConstraint(_PRODUCT_FORMS_SQL, name="chk_products_form"),
        CheckConstraint(
            "storage_temp_min_c IS NULL OR storage_temp_max_c IS NULL "
            "OR storage_temp_min_c <= storage_temp_max_c",
            name="chk_products_temp_range",
        ),
        _MYSQL_TABLE_KW,
    )


class ProductTranslation(Base):
    __tablename__ = "product_translations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_pt_product", ondelete="CASCADE"),
        nullable=False,
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    usage_instructions: Mapped[str | None] = mapped_column(Text)
    side_effects: Mapped[str | None] = mapped_column(Text)
    contraindications: Mapped[str | None] = mapped_column(Text)
    composition: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("product_id", "language_code", name="uq_pt_product_lang"),
        Index("idx_pt_lang_name", "language_code", "name"),
        # FULLTEXT index — `WITH PARSER ngram` clause added in the migration
        # via op.execute() since SQLAlchemy can't render it.
        Index(
            "ftx_pt_search",
            "name",
            "short_description",
            "description",
            mysql_prefix="FULLTEXT",
        ),
        CheckConstraint(_LANG_CHECK_SQL, name="chk_pt_lang"),
        _MYSQL_TABLE_KW,
    )


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # NOTE: ON DELETE RESTRICT (not CASCADE per PHARMACY §5.8) — MySQL forbids
    # STORED generated columns from referencing FK columns with CASCADE.
    # ORM cascade="all, delete-orphan" handles cleanup before a hard delete.
    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_product_images_product", ondelete="RESTRICT"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    medium_url: Mapped[str | None] = mapped_column(Text)
    large_url: Mapped[str | None] = mapped_column(Text)
    alt_text: Mapped[str | None] = mapped_column(String(255))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    # Generated column: equals product_id when is_primary, else NULL.
    # UNIQUE on this column = "at most one primary image per product".
    primary_product_id: Mapped[bytes | None] = mapped_column(
        BINARY(16),
        Computed("IF(is_primary, product_id, NULL)", persisted=True),
    )

    product: Mapped[Product] = relationship(back_populates="images", lazy="raise")

    __table_args__ = (
        UniqueConstraint("primary_product_id", name="uq_product_images_primary"),
        Index("idx_product_images_product_sort", "product_id", "sort_order"),
        _MYSQL_TABLE_KW,
    )


# ─── Many-to-many: products + ingredients (with dose) ───────────────────────


class ProductActiveIngredient(Base):
    __tablename__ = "product_active_ingredients"

    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_pai_product", ondelete="CASCADE"),
        primary_key=True,
    )
    active_ingredient_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "active_ingredients.id",
            name="fk_pai_ingredient",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    dosage_amount: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    dosage_unit: Mapped[str] = mapped_column(String(8), nullable=False)

    product: Mapped[Product] = relationship(back_populates="active_ingredients", lazy="raise")
    active_ingredient: Mapped[ActiveIngredient] = relationship(lazy="raise")

    __table_args__ = (
        Index("idx_pai_ingredient", "active_ingredient_id"),
        CheckConstraint(_DOSAGE_UNITS_SQL, name="chk_pai_dosage_unit"),
        _MYSQL_TABLE_KW,
    )


# ─── Many-to-many: products + symptoms ──────────────────────────────────────


class ProductSymptom(Base):
    __tablename__ = "product_symptoms"

    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_psym_product", ondelete="CASCADE"),
        primary_key=True,
    )
    symptom_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("symptoms.id", name="fk_psym_symptom", ondelete="CASCADE"),
        primary_key=True,
    )

    product: Mapped[Product] = relationship(back_populates="symptoms", lazy="raise")
    symptom: Mapped[Symptom] = relationship(lazy="raise")

    __table_args__ = (
        Index("idx_psym_symptom", "symptom_id", "product_id"),
        _MYSQL_TABLE_KW,
    )
