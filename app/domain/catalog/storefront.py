"""Storefront catalog service — read-only customer-facing API.

* :meth:`get_categories_tree` — cached 1h per language.
* :meth:`get_category_with_products` — paginated category page.
* :meth:`get_symptom_with_products` — paginated symptom page.
* :meth:`get_product_detail` — cached 5m per (product, lang); invalidated
  by Phase 5 product mutations and by Phase 6 ``update_branch_product``.
* :meth:`list_substitutes` — same primary AI + dose, in stock.

Caching keys use the ``v1:`` prefix per BACKEND §18.2; invalidation is
done by the catalog/inventory services on every mutation.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.cache import cache_get_or_set
from app.core.errors import NotFoundError
from app.domain.catalog.models import Category, Product
from app.domain.catalog.repositories import (
    CategoryRepository,
    ProductRepository,
    StorefrontProductRow,
    SymptomRepository,
)
from app.domain.catalog.storefront_schemas import (
    BreadcrumbItem,
    CategoryDetail,
    CategoryNode,
    StorefrontImage,
    StorefrontIngredient,
    StorefrontProductCard,
    StorefrontProductDetail,
    StorefrontProductsPage,
    StorefrontSymptom,
    StorefrontSymptomTag,
)
from app.domain.inventory.models import Branch, BranchProduct
from app.domain.inventory.repositories import BranchRepository

CATEGORY_TREE_TTL = 3600
PRODUCT_DETAIL_TTL = 300
DEFAULT_PAGE_SIZE = 24


def category_tree_key(language_code: str) -> str:
    return f"v1:cat:tree:{language_code}"


def product_detail_key(slug: str, language_code: str) -> str:
    return f"v1:product:read:{slug}:{language_code}"


class StorefrontCatalogService:
    def __init__(
        self,
        *,
        categories: CategoryRepository,
        products: ProductRepository,
        symptoms: SymptomRepository,
        branches: BranchRepository,
    ) -> None:
        self.categories = categories
        self.products = products
        self.symptoms = symptoms
        self.branches = branches

    # ─── Categories ────────────────────────────────────────────────────────

    async def get_categories_tree(self, *, language_code: str) -> list[CategoryNode]:
        async def _loader() -> list[dict[str, Any]]:
            cats = await self.categories.list_active_tree()
            tree = _assemble_tree(cats, language_code)
            # ``orjson`` can't serialise Pydantic models directly; dump
            # to JSON-compatible primitives before caching.
            return [n.model_dump(mode="json") for n in tree]

        nodes = await cache_get_or_set(
            category_tree_key(language_code),
            CATEGORY_TREE_TTL,
            _loader,
        )
        return [CategoryNode.model_validate(n) for n in nodes]

    async def get_category_with_products(
        self,
        *,
        slug: str,
        language_code: str,
        branch_id: int,
        in_stock_only: bool = True,
        manufacturer_id: int | None = None,
        sort: str = "relevance",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[CategoryDetail, StorefrontProductsPage]:
        category = await self.categories.get_by_slug(slug)
        if category is None:
            raise NotFoundError(code="category_not_found", slug=slug)

        # Resolve breadcrumb by walking parents.
        breadcrumb = await self._build_breadcrumb(category, language_code)
        cat_translation = (
            _pick_translation(category.translations, language_code, "name")
            if hasattr(category, "translations")
            else None
        )
        # Reload with translations if necessary.
        if cat_translation is None:
            full = await self.categories.get_by_id_with_translations(category.id)
            assert full is not None
            cat_translation = _pick_translation(full.translations, language_code, "name")
        cat_description = _pick_translation(
            (await self.categories.get_by_id_with_translations(category.id)).translations,  # type: ignore[union-attr]
            language_code,
            "description",
        )

        items, total = await self.products.list_for_category(
            category_id=category.id,
            branch_id=branch_id,
            language_code=language_code,
            in_stock_only=in_stock_only,
            manufacturer_id=manufacturer_id,
            sort=sort,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return (
            CategoryDetail(
                id=category.id,
                slug=category.slug,
                name=cat_translation or category.slug,
                description=cat_description,
                icon_url=category.icon_url,
                breadcrumb=breadcrumb,
            ),
            StorefrontProductsPage(
                items=[_row_to_card(r) for r in items],
                total=total,
                page=page,
                page_size=page_size,
            ),
        )

    # ─── Symptoms ─────────────────────────────────────────────────────────

    async def get_symptom_with_products(
        self,
        *,
        slug: str,
        language_code: str,
        branch_id: int,
        in_stock_only: bool = True,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[StorefrontSymptom, StorefrontProductsPage]:
        symptom = await self.symptoms.get_by_slug(slug)
        if symptom is None:
            raise NotFoundError(code="symptom_not_found", slug=slug)

        full = await self.symptoms.get_by_id_with_translations(symptom.id)
        assert full is not None
        name = _pick_translation(full.translations, language_code, "name") or symptom.slug

        items, total = await self.products.list_for_symptom(
            symptom_id=symptom.id,
            branch_id=branch_id,
            language_code=language_code,
            in_stock_only=in_stock_only,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return (
            StorefrontSymptom(
                id=symptom.id,
                slug=symptom.slug,
                name=name,
                icon_url=symptom.icon_url,
                sort_order=symptom.sort_order,
            ),
            StorefrontProductsPage(
                items=[_row_to_card(r) for r in items],
                total=total,
                page=page,
                page_size=page_size,
            ),
        )

    async def list_active_symptoms(self, *, language_code: str) -> list[StorefrontSymptom]:
        symptoms = await self.symptoms.list_active_with_translations()
        out: list[StorefrontSymptom] = []
        for s in symptoms:
            name = _pick_translation(s.translations, language_code, "name") or s.slug
            out.append(
                StorefrontSymptom(
                    id=s.id,
                    slug=s.slug,
                    name=name,
                    icon_url=s.icon_url,
                    sort_order=s.sort_order,
                )
            )
        return out

    # ─── Product detail + substitutes ─────────────────────────────────────

    async def get_product_detail(
        self, *, slug: str, language_code: str, branch_id: int
    ) -> StorefrontProductDetail:
        async def _loader() -> dict[str, object]:
            result = await self.products.get_storefront_detail(slug=slug, branch_id=branch_id)
            if result is None:
                # Cache absences as None? No — raise so the cache layer
                # doesn't store negative entries.
                raise NotFoundError(code="product_not_found", slug=slug)
            product, bp = result
            detail = _build_product_detail(product, bp, language_code)
            return detail.model_dump(mode="json")

        try:
            cached = await cache_get_or_set(
                product_detail_key(slug, language_code),
                PRODUCT_DETAIL_TTL,
                _loader,
            )
        except NotFoundError:
            raise
        return StorefrontProductDetail.model_validate(cached)

    async def list_substitutes(
        self, *, product_id: UUID, branch_id: int, language_code: str
    ) -> list[StorefrontProductCard]:
        rows = await self.products.list_substitutes(
            product_id=product_id,
            branch_id=branch_id,
            language_code=language_code,
        )
        return [_row_to_card(r) for r in rows]

    # ─── Branches ─────────────────────────────────────────────────────────

    async def list_active_branches(self) -> Sequence[Branch]:
        return await self.branches.list_active()

    # ─── Internals ────────────────────────────────────────────────────────

    async def _build_breadcrumb(
        self, category: Category, language_code: str
    ) -> list[BreadcrumbItem]:
        chain: list[BreadcrumbItem] = []
        current = category
        # Walk up to the root, capping at 5 hops to avoid runaway loops.
        for _ in range(5):
            full = await self.categories.get_by_id_with_translations(current.id)
            if full is None:
                break
            name = _pick_translation(full.translations, language_code, "name") or current.slug
            chain.append(BreadcrumbItem(id=full.id, slug=full.slug, name=name))
            if full.parent_id is None:
                break
            parent = await self.categories.get_by_id(full.parent_id)
            if parent is None:
                break
            current = parent
        return list(reversed(chain))


# ─── Tree assembly + translation helpers ────────────────────────────────────


def _assemble_tree(cats: Sequence[Category], language_code: str) -> list[CategoryNode]:
    by_id: dict[int, CategoryNode] = {}
    for c in cats:
        name = _pick_translation(c.translations, language_code, "name") or c.slug
        by_id[c.id] = CategoryNode(
            id=c.id,
            slug=c.slug,
            name=name,
            icon_url=c.icon_url,
            sort_order=c.sort_order,
        )
    roots: list[CategoryNode] = []
    for c in cats:
        node = by_id[c.id]
        if c.parent_id is None:
            roots.append(node)
        else:
            parent = by_id.get(c.parent_id)
            if parent is not None:
                parent.children.append(node)
    return roots


def _pick_translation(translations: Sequence[Any], language_code: str, field: str) -> str | None:
    """RU mandatory fallback — PRODUCT §13.1: every product has at least
    one ``ru`` translation. Try the requested language, then ``ru``,
    then any first translation, then None.
    """
    by_lang: dict[str, Any] = {t.language_code: t for t in translations}
    for code in (language_code, "ru"):
        t = by_lang.get(code)
        if t is not None:
            value = getattr(t, field, None)
            if value:
                return str(value)
    if translations:
        first_value = getattr(translations[0], field, None)
        if first_value:
            return str(first_value)
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


def _build_product_detail(
    product: Product, bp: BranchProduct | None, language_code: str
) -> StorefrontProductDetail:
    name = _pick_translation(product.translations, language_code, "name") or product.sku
    short = _pick_translation(product.translations, language_code, "short_description")
    description = _pick_translation(product.translations, language_code, "description")
    usage = _pick_translation(product.translations, language_code, "usage_instructions")
    side_effects = _pick_translation(product.translations, language_code, "side_effects")
    contraindications = _pick_translation(product.translations, language_code, "contraindications")
    composition = _pick_translation(product.translations, language_code, "composition")

    cat_name = (
        _pick_translation(product.category.translations, language_code, "name")
        or product.category.slug
    )

    ingredients: list[StorefrontIngredient] = []
    for pai in product.active_ingredients:
        ai = pai.active_ingredient
        ai_name = (
            _pick_translation(ai.translations, language_code, "name")
            if hasattr(ai, "translations") and ai.translations
            else None
        )
        ingredients.append(
            StorefrontIngredient(
                id=ai.id,
                inn_name=ai.inn_name,
                name=ai_name,
                dosage_amount=pai.dosage_amount,
                dosage_unit=pai.dosage_unit,
            )
        )

    symptoms: list[StorefrontSymptomTag] = []
    for ps in product.symptoms:
        sym = ps.symptom
        sym_name = (
            _pick_translation(sym.translations, language_code, "name")
            if hasattr(sym, "translations") and sym.translations
            else sym.slug
        ) or sym.slug
        symptoms.append(StorefrontSymptomTag(id=sym.id, slug=sym.slug, name=sym_name))

    images = [
        StorefrontImage(
            id=img.id,
            url=img.url,
            thumbnail_url=img.thumbnail_url,
            medium_url=img.medium_url,
            large_url=img.large_url,
            alt_text=img.alt_text,
            is_primary=img.is_primary,
        )
        for img in sorted(product.images, key=lambda i: (not i.is_primary, i.sort_order))
    ]

    available = max(int(bp.total_quantity) - int(bp.reserved_quantity), 0) if bp is not None else 0
    is_in_stock = bp is not None and bp.is_available and available > 0

    return StorefrontProductDetail(
        id=product.id,
        sku=product.sku,
        slug=product.slug,
        form=product.form,
        pack_size_label=product.pack_size_label,
        name=name,
        short_description=short,
        description=description,
        usage_instructions=usage,
        side_effects=side_effects,
        contraindications=contraindications,
        composition=composition,
        manufacturer_id=product.manufacturer_id,
        manufacturer_name=product.manufacturer.name if product.manufacturer else None,
        manufacturer_country=(product.manufacturer.country_code if product.manufacturer else None),
        category_id=product.category_id,
        category_slug=product.category.slug,
        category_name=cat_name,
        requires_prescription=product.requires_prescription,
        requires_cold_chain=product.requires_cold_chain,
        price=bp.price if bp is not None else Decimal(0),
        compare_at_price=bp.compare_at_price if bp is not None else None,
        currency=bp.currency if bp is not None else "KGS",
        is_in_stock=is_in_stock,
        active_ingredients=ingredients,
        symptoms=symptoms,
        images=images,
    )
