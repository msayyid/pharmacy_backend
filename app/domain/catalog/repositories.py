"""Catalog domain — repositories.

Five repositories, one per aggregate root:

* :class:`ManufacturerRepository`
* :class:`ActiveIngredientRepository`
* :class:`CategoryRepository`
* :class:`SymptomRepository`
* :class:`ProductRepository`

Phase 7 adds storefront read methods (``list_for_category``,
``get_storefront_detail``, ``list_substitutes``, ``storefront_search``,
``suggest``) returning the :class:`StorefrontProductRow` dataclass —
joined-row shape that combines product + lang-translation +
``branch_products`` + primary image without the N+1 of separate ORM
queries.

Repositories are thin: queries shaped for intent, no business rules, no
commits, no Pydantic. Services own transactions.

Reference: BACKEND_BLUEPRINT.md §11; PHARMACY_BLUEPRINT_2.md §11.1, §11.2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.engine import RowMapping
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
from app.domain.inventory.models import BranchProduct


def _guid_bind(u: UUID) -> bytes:
    """Encode a ``UUID`` for raw ``text()`` MySQL parameters.

    SQLAlchemy's :class:`~app.core.types.GUID` ``TypeDecorator`` only
    runs its byte-swap on ORM/Core column-bound parameters. Raw
    ``text()`` queries bypass that, so we apply the same byte-swap
    here when the parameter compares against a ``BINARY(16)`` column
    (e.g. ``products.id`` in ``WHERE p.id = :exclude_id``).
    """
    b = u.bytes
    return b[6:8] + b[4:6] + b[0:4] + b[8:]


def _guid_load(value: bytes | UUID) -> UUID:
    """Decode bytes from a raw ``text()`` SELECT into the original UUID.

    Inverse of :func:`_guid_bind`; mirrors :meth:`app.core.types.GUID
    .process_result_value`. Idempotent on already-decoded ``UUID``
    instances (e.g. ORM-loaded values).
    """
    if isinstance(value, UUID):
        return value
    b = value
    original = b[4:8] + b[2:4] + b[0:2] + b[8:]
    return UUID(bytes=original)


# ─── Storefront row shapes ───────────────────────────────────────────────────


@dataclass(slots=True)
class StorefrontProductRow:
    """Row returned by storefront list / search / substitutes methods.

    Combines product + lang-translation + ``branch_products`` + primary
    image into a single flat structure. The service maps this to a
    Pydantic ``StorefrontProductCard`` for the response.
    """

    product_id: UUID
    sku: str
    slug: str
    form: str
    is_featured: bool
    manufacturer_id: int | None
    name: str
    short_description: str | None
    price: Decimal
    compare_at_price: Decimal | None
    currency: str
    available_quantity: int
    is_in_stock: bool
    thumbnail_url: str | None
    score: float | None = None  # populated by search


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

    async def list_active_tree(self) -> Sequence[Category]:
        """All non-deleted active categories with eager-loaded translations.

        Service assembles the parent-child tree in Python and caches the
        result (``v1:cat:tree:<lang>``).
        """
        stmt = (
            select(Category)
            .options(selectinload(Category.translations))
            .where(Category.deleted_at.is_(None), Category.is_active.is_(True))
            .order_by(Category.parent_id, Category.sort_order, Category.id)
        )
        return (await self.session.execute(stmt)).scalars().all()

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

    async def list_active_with_translations(self) -> Sequence[Symptom]:
        """All active symptoms with translations eager-loaded; storefront index."""
        stmt = (
            select(Symptom)
            .options(selectinload(Symptom.translations))
            .where(Symptom.is_active.is_(True))
            .order_by(Symptom.sort_order, Symptom.id)
        )
        return (await self.session.execute(stmt)).scalars().all()

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

    # ─── Storefront reads (Phase 7) ─────────────────────────────────────────

    async def list_for_category(
        self,
        *,
        category_id: int,
        branch_id: int,
        language_code: str,
        in_stock_only: bool = True,
        manufacturer_id: int | None = None,
        sort: str = "relevance",
        offset: int = 0,
        limit: int = 24,
    ) -> tuple[Sequence[StorefrontProductRow], int]:
        """Storefront category page query (PHARMACY §11.1).

        Joins product + translation + branch_products + primary image
        in one round-trip; returns flattened rows. ``sort`` ∈
        ``{relevance, price_asc, price_desc, name, newest}``.
        """
        return await self._storefront_list(
            language_code=language_code,
            branch_id=branch_id,
            category_id=category_id,
            symptom_id=None,
            manufacturer_id=manufacturer_id,
            q=None,
            in_stock_only=in_stock_only,
            sort=sort,
            offset=offset,
            limit=limit,
        )

    async def list_for_symptom(
        self,
        *,
        symptom_id: int,
        branch_id: int,
        language_code: str,
        in_stock_only: bool = True,
        offset: int = 0,
        limit: int = 24,
    ) -> tuple[Sequence[StorefrontProductRow], int]:
        return await self._storefront_list(
            language_code=language_code,
            branch_id=branch_id,
            category_id=None,
            symptom_id=symptom_id,
            manufacturer_id=None,
            q=None,
            in_stock_only=in_stock_only,
            sort="relevance",
            offset=offset,
            limit=limit,
        )

    async def get_storefront_detail(
        self, *, slug: str, branch_id: int
    ) -> tuple[Product, BranchProduct | None] | None:
        """Full product + the branch_products row for stock + price.

        Returns ``None`` if the product is missing / soft-deleted /
        inactive. ``BranchProduct`` may be ``None`` if the branch
        has never priced this product (storefront should treat as
        out-of-stock).
        """
        prod_stmt = (
            select(Product)
            .options(
                selectinload(Product.translations),
                selectinload(Product.images),
                selectinload(Product.active_ingredients)
                .joinedload(ProductActiveIngredient.active_ingredient)
                .selectinload(ActiveIngredient.translations),
                selectinload(Product.symptoms)
                .joinedload(ProductSymptom.symptom)
                .selectinload(Symptom.translations),
                joinedload(Product.manufacturer),
                joinedload(Product.category).selectinload(Category.translations),
            )
            .where(
                Product.slug == slug,
                Product.deleted_at.is_(None),
                Product.is_active.is_(True),
            )
        )
        product = (await self.session.execute(prod_stmt)).scalar_one_or_none()
        if product is None:
            return None
        bp_stmt = select(BranchProduct).where(
            BranchProduct.branch_id == branch_id,
            BranchProduct.product_id == product.id,
        )
        bp = (await self.session.execute(bp_stmt)).scalar_one_or_none()
        return (product, bp)

    async def list_substitutes(
        self,
        *,
        product_id: UUID,
        branch_id: int,
        language_code: str,
        limit: int = 4,
    ) -> Sequence[StorefrontProductRow]:
        """Up to ``limit`` substitutes — same primary active ingredient
        AND same dose, in stock, ordered by price ascending; excludes
        the source product (PRODUCT §F-CAT-007).

        "Primary" active ingredient = the one with the largest
        ``dosage_amount`` for the source product (tie-break by
        ``active_ingredient_id``). Falls back to "same ingredient,
        any dose" if nothing matches the dose exactly — service tags
        the response so the UI can render "different dosage".
        """
        # Pull source-product's primary AI + dose.
        primary_stmt = (
            select(
                ProductActiveIngredient.active_ingredient_id,
                ProductActiveIngredient.dosage_amount,
                ProductActiveIngredient.dosage_unit,
            )
            .where(ProductActiveIngredient.product_id == product_id)
            # MySQL has no ``NULLS LAST``; use the ``IS NULL`` trick so
            # rows with a NULL dose sort after the rest.
            .order_by(
                ProductActiveIngredient.dosage_amount.is_(None).asc(),
                ProductActiveIngredient.dosage_amount.desc(),
                ProductActiveIngredient.active_ingredient_id,
            )
            .limit(1)
        )
        primary = (await self.session.execute(primary_stmt)).first()
        if primary is None:
            return []

        ai_id, dose_amount, dose_unit = primary

        # Same AI + same dose first.
        rows = await self._fetch_substitutes(
            branch_id=branch_id,
            language_code=language_code,
            exclude_product_id=product_id,
            active_ingredient_id=ai_id,
            dose_amount=dose_amount,
            dose_unit=dose_unit,
            limit=limit,
        )
        if rows:
            return rows
        # Fall back to same AI, any dose.
        return await self._fetch_substitutes(
            branch_id=branch_id,
            language_code=language_code,
            exclude_product_id=product_id,
            active_ingredient_id=ai_id,
            dose_amount=None,
            dose_unit=None,
            limit=limit,
        )

    async def storefront_search(
        self,
        *,
        boolean_query: str,
        language_code: str,
        branch_id: int,
        in_stock_only: bool = True,
        offset: int = 0,
        limit: int = 24,
    ) -> tuple[Sequence[StorefrontProductRow], int]:
        """Composite-ranked storefront search (PRODUCT §12.2).

        Score = exact_name_match * 1000 + name_prefix * 500
              + FULLTEXT_score * 10
              + has_ingredient_match * 50
              + has_symptom_match * 30
              + has_manufacturer_match * 20

        ``boolean_query`` is the prepared MySQL-BOOLEAN-mode query
        (already synonym-expanded by the service); the same string is
        also LIKE-prefixed with ``%`` for the substring fallback.
        Returns rows in score order with ``score`` populated.
        """
        return await self._storefront_search(
            boolean_query=boolean_query,
            language_code=language_code,
            branch_id=branch_id,
            in_stock_only=in_stock_only,
            offset=offset,
            limit=limit,
        )

    async def suggest(
        self,
        *,
        prefix: str,
        language_code: str,
        branch_id: int,
        limit: int = 4,
    ) -> Sequence[StorefrontProductRow]:
        """Autocomplete: prefix-match on translated name + in-stock
        first; cheap query for the suggest endpoint.
        """
        like = f"{prefix.strip().lower()}%"
        sql = text(
            """
            SELECT
              p.id            AS product_id,
              p.sku           AS sku,
              p.slug          AS slug,
              p.form          AS form,
              p.is_featured   AS is_featured,
              p.manufacturer_id AS manufacturer_id,
              pt.name         AS name,
              pt.short_description AS short_description,
              COALESCE(bp.price, 0)              AS price,
              bp.compare_at_price                AS compare_at_price,
              COALESCE(bp.currency, 'KGS')       AS currency,
              GREATEST(COALESCE(bp.total_quantity, 0)
                       - COALESCE(bp.reserved_quantity, 0), 0) AS available_quantity,
              pi.thumbnail_url AS thumbnail_url
            FROM products p
            JOIN product_translations pt
              ON pt.product_id = p.id AND pt.language_code = :lang
            LEFT JOIN branch_products bp
              ON bp.product_id = p.id AND bp.branch_id = :branch_id
            LEFT JOIN product_images pi
              ON pi.primary_product_id = p.id
            WHERE p.is_active = 1
              AND p.deleted_at IS NULL
              AND LOWER(pt.name) LIKE :like
            ORDER BY
              CASE WHEN COALESCE(bp.total_quantity, 0)
                        - COALESCE(bp.reserved_quantity, 0) > 0 THEN 0 ELSE 1 END,
              p.is_featured DESC,
              pt.name
            LIMIT :limit
            """
        )
        result = await self.session.execute(
            sql,
            {
                "lang": language_code,
                "branch_id": branch_id,
                "like": like,
                "limit": limit,
            },
        )
        return [_row_to_storefront(r) for r in result.mappings().all()]

    # ─── Internal helpers ──────────────────────────────────────────────────

    async def _storefront_list(
        self,
        *,
        language_code: str,
        branch_id: int,
        category_id: int | None,
        symptom_id: int | None,
        manufacturer_id: int | None,
        q: str | None,
        in_stock_only: bool,
        sort: str,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[StorefrontProductRow], int]:
        order_clause = _SORT_CLAUSES.get(sort, _SORT_CLAUSES["relevance"])
        symptom_join = (
            "JOIN product_symptoms ps ON ps.product_id = p.id " "AND ps.symptom_id = :symptom_id"
            if symptom_id is not None
            else ""
        )
        where = ["p.is_active = 1", "p.deleted_at IS NULL"]
        if category_id is not None:
            where.append("p.category_id = :category_id")
        if manufacturer_id is not None:
            where.append("p.manufacturer_id = :manufacturer_id")
        if q:
            where.append("LOWER(pt.name) LIKE :q_like")
        if in_stock_only:
            where.append(
                "COALESCE(bp.total_quantity, 0) " "- COALESCE(bp.reserved_quantity, 0) > 0"
            )
        where_sql = " AND ".join(where)

        params: dict[str, object] = {
            "lang": language_code,
            "branch_id": branch_id,
            "limit": limit,
            "offset": offset,
        }
        if category_id is not None:
            params["category_id"] = category_id
        if symptom_id is not None:
            params["symptom_id"] = symptom_id
        if manufacturer_id is not None:
            params["manufacturer_id"] = manufacturer_id
        if q:
            params["q_like"] = f"%{q.lower()}%"

        items_sql = text(
            f"""
            SELECT
              p.id            AS product_id,
              p.sku           AS sku,
              p.slug          AS slug,
              p.form          AS form,
              p.is_featured   AS is_featured,
              p.manufacturer_id AS manufacturer_id,
              pt.name         AS name,
              pt.short_description AS short_description,
              COALESCE(bp.price, 0)              AS price,
              bp.compare_at_price                AS compare_at_price,
              COALESCE(bp.currency, 'KGS')       AS currency,
              GREATEST(COALESCE(bp.total_quantity, 0)
                       - COALESCE(bp.reserved_quantity, 0), 0) AS available_quantity,
              pi.thumbnail_url AS thumbnail_url
            FROM products p
            JOIN product_translations pt
              ON pt.product_id = p.id AND pt.language_code = :lang
            LEFT JOIN branch_products bp
              ON bp.product_id = p.id AND bp.branch_id = :branch_id
            LEFT JOIN product_images pi
              ON pi.primary_product_id = p.id
            {symptom_join}
            WHERE {where_sql}
            ORDER BY {order_clause}
            LIMIT :limit OFFSET :offset
            """
        )
        count_sql = text(
            f"""
            SELECT COUNT(*) AS n
            FROM products p
            JOIN product_translations pt
              ON pt.product_id = p.id AND pt.language_code = :lang
            LEFT JOIN branch_products bp
              ON bp.product_id = p.id AND bp.branch_id = :branch_id
            {symptom_join}
            WHERE {where_sql}
            """  # noqa: S608
        )

        items_result = await self.session.execute(items_sql, params)
        total_result = await self.session.execute(count_sql, params)
        items = [_row_to_storefront(r) for r in items_result.mappings().all()]
        total = int(total_result.scalar_one())
        return (items, total)

    async def _fetch_substitutes(
        self,
        *,
        branch_id: int,
        language_code: str,
        exclude_product_id: UUID,
        active_ingredient_id: int,
        dose_amount: Decimal | None,
        dose_unit: str | None,
        limit: int,
    ) -> Sequence[StorefrontProductRow]:
        params: dict[str, object] = {
            "lang": language_code,
            "branch_id": branch_id,
            "exclude_id": _guid_bind(exclude_product_id),
            "ai_id": active_ingredient_id,
            "limit": limit,
        }
        dose_filter = ""
        if dose_amount is not None and dose_unit is not None:
            dose_filter = "AND pai.dosage_amount = :dose_amount " "AND pai.dosage_unit = :dose_unit"
            params["dose_amount"] = dose_amount
            params["dose_unit"] = dose_unit
        sql = text(
            f"""
            SELECT
              p.id            AS product_id,
              p.sku           AS sku,
              p.slug          AS slug,
              p.form          AS form,
              p.is_featured   AS is_featured,
              p.manufacturer_id AS manufacturer_id,
              pt.name         AS name,
              pt.short_description AS short_description,
              COALESCE(bp.price, 0)              AS price,
              bp.compare_at_price                AS compare_at_price,
              COALESCE(bp.currency, 'KGS')       AS currency,
              GREATEST(COALESCE(bp.total_quantity, 0)
                       - COALESCE(bp.reserved_quantity, 0), 0) AS available_quantity,
              pi.thumbnail_url AS thumbnail_url
            FROM product_active_ingredients pai
            JOIN products p ON p.id = pai.product_id
            JOIN product_translations pt
              ON pt.product_id = p.id AND pt.language_code = :lang
            LEFT JOIN branch_products bp
              ON bp.product_id = p.id AND bp.branch_id = :branch_id
            LEFT JOIN product_images pi
              ON pi.primary_product_id = p.id
            WHERE pai.active_ingredient_id = :ai_id
              {dose_filter}
              AND p.id != :exclude_id
              AND p.is_active = 1
              AND p.deleted_at IS NULL
              AND COALESCE(bp.total_quantity, 0)
                  - COALESCE(bp.reserved_quantity, 0) > 0
            ORDER BY bp.price ASC
            LIMIT :limit
            """
        )
        result = await self.session.execute(sql, params)
        return [_row_to_storefront(r) for r in result.mappings().all()]

    async def _storefront_search(
        self,
        *,
        boolean_query: str,
        language_code: str,
        branch_id: int,
        in_stock_only: bool,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[StorefrontProductRow], int]:
        # Lower-cased query for the exact-match and prefix-match boosts.
        q_lower = boolean_query.lstrip("+ ").rstrip(" *").lower()
        prefix = f"{q_lower}%"
        like = f"%{q_lower}%"
        in_stock_clause = (
            "AND COALESCE(bp.total_quantity, 0) " "- COALESCE(bp.reserved_quantity, 0) > 0"
            if in_stock_only
            else ""
        )

        params: dict[str, object] = {
            "lang": language_code,
            "branch_id": branch_id,
            "boolean_query": boolean_query,
            "q_lower": q_lower,
            "prefix": prefix,
            "like": like,
            "limit": limit,
            "offset": offset,
        }

        # The composite-ranked SELECT is built around the FULLTEXT MATCH
        # AGAINST(... IN BOOLEAN MODE) score (BACKEND §6.4 ngram index).
        items_sql = text(
            f"""
            SELECT
              p.id            AS product_id,
              p.sku           AS sku,
              p.slug          AS slug,
              p.form          AS form,
              p.is_featured   AS is_featured,
              p.manufacturer_id AS manufacturer_id,
              pt.name         AS name,
              pt.short_description AS short_description,
              COALESCE(bp.price, 0)              AS price,
              bp.compare_at_price                AS compare_at_price,
              COALESCE(bp.currency, 'KGS')       AS currency,
              GREATEST(COALESCE(bp.total_quantity, 0)
                       - COALESCE(bp.reserved_quantity, 0), 0) AS available_quantity,
              pi.thumbnail_url AS thumbnail_url,
              (
                CASE WHEN LOWER(pt.name) = :q_lower THEN 1000 ELSE 0 END
                + CASE WHEN LOWER(pt.name) LIKE :prefix THEN 500 ELSE 0 END
                + (MATCH(pt.name, pt.short_description, pt.description)
                    AGAINST (:boolean_query IN BOOLEAN MODE)) * 10
                + CASE WHEN EXISTS (
                    SELECT 1 FROM product_active_ingredients pai
                    JOIN active_ingredients ai ON ai.id = pai.active_ingredient_id
                    LEFT JOIN active_ingredient_translations ait
                      ON ait.active_ingredient_id = ai.id
                      AND ait.language_code = :lang
                    WHERE pai.product_id = p.id
                      AND (LOWER(ai.inn_name) LIKE :like
                           OR LOWER(ait.name) LIKE :like)
                  ) THEN 50 ELSE 0 END
                + CASE WHEN EXISTS (
                    SELECT 1 FROM product_symptoms ps
                    JOIN symptoms s ON s.id = ps.symptom_id
                    LEFT JOIN symptom_translations st
                      ON st.symptom_id = s.id AND st.language_code = :lang
                    WHERE ps.product_id = p.id
                      AND (LOWER(s.slug) LIKE :like OR LOWER(st.name) LIKE :like)
                  ) THEN 30 ELSE 0 END
                + CASE WHEN EXISTS (
                    SELECT 1 FROM manufacturers m
                    WHERE m.id = p.manufacturer_id
                      AND LOWER(m.name) LIKE :like
                  ) THEN 20 ELSE 0 END
              ) AS score
            FROM products p
            JOIN product_translations pt
              ON pt.product_id = p.id AND pt.language_code = :lang
            LEFT JOIN branch_products bp
              ON bp.product_id = p.id AND bp.branch_id = :branch_id
            LEFT JOIN product_images pi
              ON pi.primary_product_id = p.id
            WHERE p.is_active = 1
              AND p.deleted_at IS NULL
              {in_stock_clause}
            HAVING score > 0
            ORDER BY score DESC, p.is_featured DESC, p.created_at DESC
            LIMIT :limit OFFSET :offset
            """  # noqa: S608
        )
        # Total uses the same scoring expression to count "matched"
        # rows correctly. Wrapped as a subquery so HAVING applies.
        count_sql = text(
            f"""
            SELECT COUNT(*) AS n FROM (
              SELECT p.id,
                (
                  CASE WHEN LOWER(pt.name) = :q_lower THEN 1000 ELSE 0 END
                  + CASE WHEN LOWER(pt.name) LIKE :prefix THEN 500 ELSE 0 END
                  + (MATCH(pt.name, pt.short_description, pt.description)
                      AGAINST (:boolean_query IN BOOLEAN MODE)) * 10
                  + CASE WHEN EXISTS (
                      SELECT 1 FROM product_active_ingredients pai
                      JOIN active_ingredients ai
                        ON ai.id = pai.active_ingredient_id
                      LEFT JOIN active_ingredient_translations ait
                        ON ait.active_ingredient_id = ai.id
                        AND ait.language_code = :lang
                      WHERE pai.product_id = p.id
                        AND (LOWER(ai.inn_name) LIKE :like
                             OR LOWER(ait.name) LIKE :like)
                    ) THEN 50 ELSE 0 END
                  + CASE WHEN EXISTS (
                      SELECT 1 FROM product_symptoms ps
                      JOIN symptoms s ON s.id = ps.symptom_id
                      LEFT JOIN symptom_translations st
                        ON st.symptom_id = s.id AND st.language_code = :lang
                      WHERE ps.product_id = p.id
                        AND (LOWER(s.slug) LIKE :like
                             OR LOWER(st.name) LIKE :like)
                    ) THEN 30 ELSE 0 END
                  + CASE WHEN EXISTS (
                      SELECT 1 FROM manufacturers m
                      WHERE m.id = p.manufacturer_id
                        AND LOWER(m.name) LIKE :like
                    ) THEN 20 ELSE 0 END
                ) AS score
              FROM products p
              JOIN product_translations pt
                ON pt.product_id = p.id AND pt.language_code = :lang
              LEFT JOIN branch_products bp
                ON bp.product_id = p.id AND bp.branch_id = :branch_id
              WHERE p.is_active = 1
                AND p.deleted_at IS NULL
                {in_stock_clause}
              HAVING score > 0
            ) sub
            """  # noqa: S608
        )
        items_result = await self.session.execute(items_sql, params)
        total_result = await self.session.execute(count_sql, params)
        rows: list[StorefrontProductRow] = []
        for m in items_result.mappings().all():
            row = _row_to_storefront(m)
            row.score = float(m["score"]) if m["score"] is not None else None
            rows.append(row)
        total = int(total_result.scalar_one())
        return (rows, total)

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


# ─── Storefront row helpers ──────────────────────────────────────────────────


_SORT_CLAUSES = {
    "relevance": "p.is_featured DESC, p.created_at DESC",
    "price_asc": "COALESCE(bp.price, 0) ASC, p.created_at DESC",
    "price_desc": "COALESCE(bp.price, 0) DESC, p.created_at DESC",
    "name": "pt.name ASC",
    "newest": "p.created_at DESC",
}


def _row_to_storefront(m: RowMapping) -> StorefrontProductRow:
    """Map a SQL row mapping → :class:`StorefrontProductRow`."""
    available = int(m["available_quantity"])
    return StorefrontProductRow(
        product_id=_guid_load(m["product_id"]),
        sku=m["sku"],
        slug=m["slug"],
        form=m["form"],
        is_featured=bool(m["is_featured"]),
        manufacturer_id=m["manufacturer_id"],
        name=m["name"],
        short_description=m["short_description"],
        price=Decimal(m["price"]) if m["price"] is not None else Decimal(0),
        compare_at_price=Decimal(m["compare_at_price"])
        if m["compare_at_price"] is not None
        else None,
        currency=m["currency"],
        available_quantity=available,
        is_in_stock=available > 0,
        thumbnail_url=m["thumbnail_url"],
    )
