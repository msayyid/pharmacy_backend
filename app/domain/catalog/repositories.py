"""Catalog domain — repositories.

Five repositories, one per aggregate root:

* :class:`ManufacturerRepository`
* :class:`ActiveIngredientRepository`
* :class:`CategoryRepository`
* :class:`SymptomRepository`
* :class:`ProductRepository`

Repositories are thin: queries shaped for intent, no business rules, no
commits, no Pydantic. Services own transactions.

Reference: BACKEND_BLUEPRINT.md §11.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.domain.catalog.models import (
    ActiveIngredient,
    Category,
    Manufacturer,
    Product,
    ProductActiveIngredient,
    ProductImage,
    ProductSymptom,
    ProductTranslation,
    Symptom,
)

# ─── Manufacturers ───────────────────────────────────────────────────────────


class ManufacturerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, manufacturer_id: int) -> Manufacturer | None:
        stmt = select(Manufacturer).where(Manufacturer.id == manufacturer_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, name: str) -> Manufacturer | None:
        stmt = select(Manufacturer).where(Manufacturer.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self, *, offset: int, limit: int, q: str | None = None
    ) -> tuple[Sequence[Manufacturer], int]:
        base = select(Manufacturer)
        if q:
            base = base.where(Manufacturer.name.ilike(f"%{q}%"))
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = base.order_by(Manufacturer.name).offset(offset).limit(limit)
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def has_active_products(self, manufacturer_id: int) -> bool:
        """Used by the service to enforce 'cannot delete manufacturer with products'."""
        stmt = select(func.count(Product.id)).where(
            Product.manufacturer_id == manufacturer_id,
            Product.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def add(self, manufacturer: Manufacturer) -> None:
        self.session.add(manufacturer)
        await self.session.flush()
        await self.session.refresh(manufacturer)

    async def delete(self, manufacturer: Manufacturer) -> None:
        await self.session.delete(manufacturer)
        await self.session.flush()


# ─── Active ingredients ──────────────────────────────────────────────────────


class ActiveIngredientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, ingredient_id: int) -> ActiveIngredient | None:
        stmt = select(ActiveIngredient).where(ActiveIngredient.id == ingredient_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_translations(self, ingredient_id: int) -> ActiveIngredient | None:
        stmt = (
            select(ActiveIngredient)
            .options(selectinload(ActiveIngredient.translations))
            .where(ActiveIngredient.id == ingredient_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_inn(self, inn_name: str) -> ActiveIngredient | None:
        stmt = select(ActiveIngredient).where(ActiveIngredient.inn_name == inn_name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self, *, offset: int, limit: int, q: str | None = None
    ) -> tuple[Sequence[ActiveIngredient], int]:
        filtered = select(ActiveIngredient)
        if q:
            filtered = filtered.where(ActiveIngredient.inn_name.ilike(f"%{q}%"))
        total_stmt = select(func.count()).select_from(filtered.subquery())
        items_stmt = (
            filtered.options(selectinload(ActiveIngredient.translations))
            .order_by(ActiveIngredient.inn_name)
            .offset(offset)
            .limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def add(self, ingredient: ActiveIngredient) -> None:
        self.session.add(ingredient)
        await self.session.flush()
        await self.session.refresh(ingredient)


# ─── Categories ──────────────────────────────────────────────────────────────


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, category_id: int) -> Category | None:
        stmt = select(Category).where(Category.id == category_id, Category.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_translations(self, category_id: int) -> Category | None:
        stmt = (
            select(Category)
            .options(selectinload(Category.translations))
            .where(Category.id == category_id, Category.deleted_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Category | None:
        stmt = select(Category).where(Category.slug == slug, Category.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        parent_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[Category], int]:
        base = select(Category).where(Category.deleted_at.is_(None))
        if parent_id is None:
            base = base.where(Category.parent_id.is_(None))
        else:
            base = base.where(Category.parent_id == parent_id)
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = (
            base.options(selectinload(Category.translations))
            .order_by(Category.sort_order, Category.id)
            .offset(offset)
            .limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def has_children(self, category_id: int) -> bool:
        stmt = select(func.count(Category.id)).where(
            Category.parent_id == category_id, Category.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def has_active_products(self, category_id: int) -> bool:
        stmt = select(func.count(Product.id)).where(
            Product.category_id == category_id, Product.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def add(self, category: Category) -> None:
        self.session.add(category)
        await self.session.flush()
        await self.session.refresh(category)


# ─── Symptoms ────────────────────────────────────────────────────────────────


class SymptomRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, symptom_id: int) -> Symptom | None:
        stmt = select(Symptom).where(Symptom.id == symptom_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_translations(self, symptom_id: int) -> Symptom | None:
        stmt = (
            select(Symptom)
            .options(selectinload(Symptom.translations))
            .where(Symptom.id == symptom_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Symptom | None:
        stmt = select(Symptom).where(Symptom.slug == slug)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self, *, offset: int = 0, limit: int = 100, active_only: bool = False
    ) -> tuple[Sequence[Symptom], int]:
        base = select(Symptom)
        if active_only:
            base = base.where(Symptom.is_active.is_(True))
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = (
            base.options(selectinload(Symptom.translations))
            .order_by(Symptom.sort_order, Symptom.id)
            .offset(offset)
            .limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def add(self, symptom: Symptom) -> None:
        self.session.add(symptom)
        await self.session.flush()
        await self.session.refresh(symptom)


# ─── Products ────────────────────────────────────────────────────────────────


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, product_id: UUID) -> Product | None:
        stmt = select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_full(self, product_id: UUID) -> Product | None:
        """Eager-load translations, images, M:N ingredients/symptoms, manufacturer."""
        stmt = (
            select(Product)
            .options(
                selectinload(Product.translations),
                selectinload(Product.images),
                selectinload(Product.active_ingredients).joinedload(
                    ProductActiveIngredient.active_ingredient
                ),
                selectinload(Product.symptoms).joinedload(ProductSymptom.symptom),
                joinedload(Product.manufacturer),
                joinedload(Product.category),
            )
            .where(Product.id == product_id, Product.deleted_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Product | None:
        stmt = select(Product).where(Product.slug == slug, Product.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_sku(self, sku: str) -> Product | None:
        """SKU lookup includes soft-deleted rows so re-import behaves idempotently."""
        stmt = select(Product).where(Product.sku == sku)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(func.count()).select_from(
            select(Product.id).where(Product.slug == slug).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list_paginated(
        self,
        *,
        category_id: int | None = None,
        manufacturer_id: int | None = None,
        is_active: bool | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 24,
    ) -> tuple[Sequence[Product], int]:
        base = select(Product).where(Product.deleted_at.is_(None))
        if category_id is not None:
            base = base.where(Product.category_id == category_id)
        if manufacturer_id is not None:
            base = base.where(Product.manufacturer_id == manufacturer_id)
        if is_active is not None:
            base = base.where(Product.is_active.is_(is_active))
        if q:
            base = base.where(Product.sku.ilike(f"%{q}%"))

        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = (
            base.options(
                selectinload(Product.translations),
                selectinload(Product.images),
            )
            .order_by(Product.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

    async def add(self, product: Product) -> None:
        self.session.add(product)
        await self.session.flush()
        await self.session.refresh(product)

    async def soft_delete(self, product: Product) -> None:
        product.deleted_at = func.utc_timestamp(6)
        await self.session.flush()

    async def fulltext_search(
        self, *, query: str, language_code: str, limit: int = 50
    ) -> Sequence[ProductTranslation]:
        """Wrapper for the FULLTEXT ngram index on product_translations.

        Phase 7 will build the production search service on top; Phase 5 ships
        this for repository tests and ad-hoc admin search.
        """
        # MATCH ... AGAINST (... IN BOOLEAN MODE) — text() escapes ``%``.
        stmt = (
            select(ProductTranslation)
            .where(
                ProductTranslation.language_code == language_code,
                func.match(
                    ProductTranslation.name,
                    ProductTranslation.short_description,
                    ProductTranslation.description,
                ).against(query, postfix_modifiers="IN BOOLEAN MODE"),
            )
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()


# ─── Helpers (composite operations service uses) ─────────────────────────────


async def add_product_image(session: AsyncSession, image: ProductImage) -> None:
    """Add a product image and refresh to load the generated ``primary_product_id``
    plus the server-default ``created_at``.
    """
    session.add(image)
    await session.flush()
    await session.refresh(image)


async def add_product_active_ingredient(
    session: AsyncSession, link: ProductActiveIngredient
) -> None:
    session.add(link)
    await session.flush()


async def add_product_symptom(session: AsyncSession, link: ProductSymptom) -> None:
    session.add(link)
    await session.flush()
