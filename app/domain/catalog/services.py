"""Catalog admin service — CRUD for the four simpler aggregates.

* Manufacturers (no translations)
* Active ingredients (with translations)
* Categories (with translations + tree + slug auto-gen)
* Symptoms (with translations + slug auto-gen)

Each mutation writes an ``admin_audit_log`` row. Translation lists are
"replace" semantics — passing a non-None ``translations`` field on update
replaces the full set (cascade ``all, delete-orphan`` cleans up).

ProductService + ProductImageService + ProductImportService land in 5.5.

Reference: BACKEND_BLUEPRINT.md §12; PRODUCT_BLUEPRINT.md §8.5; CLAUDE_CODE_PROMPTS Phase 5.
"""

from __future__ import annotations

from typing import Any

from app.core.cache import invalidate as cache_invalidate
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.domain.catalog.models import (
    ActiveIngredient,
    ActiveIngredientTranslation,
    Category,
    CategoryTranslation,
    Manufacturer,
    Symptom,
    SymptomTranslation,
)
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    SymptomRepository,
)
from app.domain.catalog.schemas import (
    ActiveIngredientCreate,
    ActiveIngredientTranslationIn,
    ActiveIngredientUpdate,
    CategoryCreate,
    CategoryTranslationIn,
    CategoryUpdate,
    ManufacturerCreate,
    ManufacturerUpdate,
    SymptomCreate,
    SymptomTranslationIn,
    SymptomUpdate,
)
from app.domain.catalog.slug import slugify_name, unique_slug
from app.domain.identity.models import AdminUser
from app.domain.ops.services import AdminAuditLogService

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _pick_slug_source(
    translations: list[CategoryTranslationIn]
    | list[SymptomTranslationIn]
    | list[ActiveIngredientTranslationIn],
) -> str:
    """Prefer RU, fall back to KY, then EN, then first available."""
    for lang in ("ru", "ky", "en"):
        for t in translations:
            if t.language_code == lang:
                return t.name
    if translations:
        return translations[0].name
    return ""


def _manufacturer_snapshot(m: Manufacturer) -> dict[str, Any]:
    return {
        "name": m.name,
        "country_code": m.country_code,
        "website": m.website,
        "is_active": m.is_active,
    }


def _category_snapshot(c: Category) -> dict[str, Any]:
    return {
        "parent_id": c.parent_id,
        "slug": c.slug,
        "icon_url": c.icon_url,
        "sort_order": c.sort_order,
        "is_active": c.is_active,
    }


def _ingredient_snapshot(ai: ActiveIngredient) -> dict[str, Any]:
    return {"inn_name": ai.inn_name}


def _symptom_snapshot(s: Symptom) -> dict[str, Any]:
    return {
        "slug": s.slug,
        "icon_url": s.icon_url,
        "sort_order": s.sort_order,
        "is_active": s.is_active,
    }


class CatalogAdminService:
    """Admin CRUD for manufacturers / ingredients / categories / symptoms."""

    def __init__(
        self,
        *,
        manufacturers: ManufacturerRepository,
        ingredients: ActiveIngredientRepository,
        categories: CategoryRepository,
        symptoms: SymptomRepository,
        audit: AdminAuditLogService,
    ) -> None:
        self.manufacturers = manufacturers
        self.ingredients = ingredients
        self.categories = categories
        self.symptoms = symptoms
        self.audit = audit

    # ─── Manufacturers ──────────────────────────────────────────────────────

    async def create_manufacturer(
        self,
        *,
        payload: ManufacturerCreate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Manufacturer:
        if await self.manufacturers.get_by_name(payload.name) is not None:
            raise ConflictError(code="manufacturer_name_exists", name=payload.name)
        m = Manufacturer(
            name=payload.name,
            country_code=payload.country_code,
            website=payload.website,
            is_active=payload.is_active,
        )
        await self.manufacturers.add(m)
        await self.audit.record(
            admin_user_id=actor.id,
            action="create",
            entity_type="manufacturer",
            entity_id=m.id,
            after=_manufacturer_snapshot(m),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return m

    async def update_manufacturer(
        self,
        manufacturer_id: int,
        *,
        payload: ManufacturerUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Manufacturer:
        m = await self.manufacturers.get_by_id(manufacturer_id)
        if m is None:
            raise NotFoundError(code="manufacturer_not_found")
        before = _manufacturer_snapshot(m)
        if payload.name is not None and payload.name != m.name:
            other = await self.manufacturers.get_by_name(payload.name)
            if other is not None and other.id != m.id:
                raise ConflictError(code="manufacturer_name_exists", name=payload.name)
            m.name = payload.name
        if payload.country_code is not None:
            m.country_code = payload.country_code
        if payload.website is not None:
            m.website = payload.website
        if payload.is_active is not None:
            m.is_active = payload.is_active
        await self.manufacturers.session.flush()
        await self.audit.record(
            admin_user_id=actor.id,
            action="update",
            entity_type="manufacturer",
            entity_id=m.id,
            before=before,
            after=_manufacturer_snapshot(m),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return m

    async def delete_manufacturer(
        self,
        manufacturer_id: int,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        m = await self.manufacturers.get_by_id(manufacturer_id)
        if m is None:
            raise NotFoundError(code="manufacturer_not_found")
        if await self.manufacturers.has_active_products(manufacturer_id):
            raise ConflictError(
                code="manufacturer_has_products",
                manufacturer_id=manufacturer_id,
            )
        before = _manufacturer_snapshot(m)
        await self.manufacturers.delete(m)
        await self.audit.record(
            admin_user_id=actor.id,
            action="delete",
            entity_type="manufacturer",
            entity_id=manufacturer_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # ─── Active ingredients ─────────────────────────────────────────────────

    async def create_ingredient(
        self,
        *,
        payload: ActiveIngredientCreate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActiveIngredient:
        if await self.ingredients.get_by_inn(payload.inn_name) is not None:
            raise ConflictError(code="ingredient_inn_exists", inn_name=payload.inn_name)
        ai = ActiveIngredient(inn_name=payload.inn_name)
        for t in payload.translations:
            ai.translations.append(
                ActiveIngredientTranslation(
                    language_code=t.language_code,
                    name=t.name,
                    synonyms=list(t.synonyms),
                )
            )
        await self.ingredients.add(ai)
        await self.audit.record(
            admin_user_id=actor.id,
            action="create",
            entity_type="active_ingredient",
            entity_id=ai.id,
            after=_ingredient_snapshot(ai),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return ai

    async def update_ingredient(
        self,
        ingredient_id: int,
        *,
        payload: ActiveIngredientUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActiveIngredient:
        ai = await self.ingredients.get_by_id_with_translations(ingredient_id)
        if ai is None:
            raise NotFoundError(code="ingredient_not_found")
        before = _ingredient_snapshot(ai)
        if payload.inn_name is not None and payload.inn_name != ai.inn_name:
            other = await self.ingredients.get_by_inn(payload.inn_name)
            if other is not None and other.id != ai.id:
                raise ConflictError(code="ingredient_inn_exists", inn_name=payload.inn_name)
            ai.inn_name = payload.inn_name
        if payload.translations is not None:
            ai.translations.clear()
            for t in payload.translations:
                ai.translations.append(
                    ActiveIngredientTranslation(
                        language_code=t.language_code,
                        name=t.name,
                        synonyms=list(t.synonyms),
                    )
                )
        await self.ingredients.session.flush()
        await self.audit.record(
            admin_user_id=actor.id,
            action="update",
            entity_type="active_ingredient",
            entity_id=ai.id,
            before=before,
            after=_ingredient_snapshot(ai),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return ai

    # ─── Categories ─────────────────────────────────────────────────────────

    async def create_category(
        self,
        *,
        payload: CategoryCreate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Category:
        if payload.parent_id is not None:
            parent = await self.categories.get_by_id(payload.parent_id)
            if parent is None:
                raise ValidationError(
                    code="parent_category_not_found",
                    parent_id=payload.parent_id,
                )

        # Slug: explicit, else auto-generate from translation name
        slug = payload.slug or slugify_name(_pick_slug_source(payload.translations))
        if not slug:
            raise ValidationError(code="slug_required_or_translation_required")

        async def _exists(s: str) -> bool:
            return await self.categories.get_by_slug(s) is not None

        slug = await unique_slug(slug, _exists)

        c = Category(
            parent_id=payload.parent_id,
            slug=slug,
            icon_url=payload.icon_url,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
        for t in payload.translations:
            c.translations.append(
                CategoryTranslation(
                    language_code=t.language_code,
                    name=t.name,
                    description=t.description,
                    meta_title=t.meta_title,
                    meta_description=t.meta_description,
                )
            )
        await self.categories.add(c)
        await self.audit.record(
            admin_user_id=actor.id,
            action="create",
            entity_type="category",
            entity_id=c.id,
            after=_category_snapshot(c),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        # Invalidate the storefront category-tree cache (BACKEND §18.4).
        await cache_invalidate("v1:cat:tree:")
        return c

    async def update_category(
        self,
        category_id: int,
        *,
        payload: CategoryUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Category:
        c = await self.categories.get_by_id_with_translations(category_id)
        if c is None:
            raise NotFoundError(code="category_not_found")
        before = _category_snapshot(c)

        if payload.parent_id is not None:
            if payload.parent_id == c.id:
                raise ValidationError(code="category_self_parent")
            parent = await self.categories.get_by_id(payload.parent_id)
            if parent is None:
                raise ValidationError(
                    code="parent_category_not_found",
                    parent_id=payload.parent_id,
                )
            c.parent_id = payload.parent_id

        if payload.slug is not None and payload.slug != c.slug:

            async def _exists(s: str) -> bool:
                other = await self.categories.get_by_slug(s)
                return other is not None and other.id != c.id

            c.slug = await unique_slug(payload.slug, _exists)

        if payload.icon_url is not None:
            c.icon_url = payload.icon_url
        if payload.sort_order is not None:
            c.sort_order = payload.sort_order
        if payload.is_active is not None:
            c.is_active = payload.is_active

        if payload.translations is not None:
            c.translations.clear()
            for t in payload.translations:
                c.translations.append(
                    CategoryTranslation(
                        language_code=t.language_code,
                        name=t.name,
                        description=t.description,
                        meta_title=t.meta_title,
                        meta_description=t.meta_description,
                    )
                )

        await self.categories.session.flush()
        await cache_invalidate("v1:cat:tree:")
        await self.audit.record(
            admin_user_id=actor.id,
            action="update",
            entity_type="category",
            entity_id=c.id,
            before=before,
            after=_category_snapshot(c),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return c

    async def delete_category(
        self,
        category_id: int,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        c = await self.categories.get_by_id(category_id)
        if c is None:
            raise NotFoundError(code="category_not_found")
        if await self.categories.has_children(category_id):
            raise ConflictError(code="category_has_children", category_id=category_id)
        if await self.categories.has_active_products(category_id):
            raise ConflictError(code="category_has_products", category_id=category_id)
        before = _category_snapshot(c)
        # Soft delete via deleted_at (catalog entities use SoftDeleteMixin).
        from app.core.time import utcnow

        c.deleted_at = utcnow()
        await self.categories.session.flush()
        await cache_invalidate("v1:cat:tree:")
        await self.audit.record(
            admin_user_id=actor.id,
            action="delete",
            entity_type="category",
            entity_id=category_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # ─── Symptoms ───────────────────────────────────────────────────────────

    async def create_symptom(
        self,
        *,
        payload: SymptomCreate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Symptom:
        slug = payload.slug or slugify_name(_pick_slug_source(payload.translations))
        if not slug:
            raise ValidationError(code="slug_required_or_translation_required")

        async def _exists(s: str) -> bool:
            return await self.symptoms.get_by_slug(s) is not None

        slug = await unique_slug(slug, _exists)

        s = Symptom(
            slug=slug,
            icon_url=payload.icon_url,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
        for t in payload.translations:
            s.translations.append(
                SymptomTranslation(
                    language_code=t.language_code,
                    name=t.name,
                    synonyms=list(t.synonyms),
                )
            )
        await self.symptoms.add(s)
        await self.audit.record(
            admin_user_id=actor.id,
            action="create",
            entity_type="symptom",
            entity_id=s.id,
            after=_symptom_snapshot(s),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return s

    async def update_symptom(
        self,
        symptom_id: int,
        *,
        payload: SymptomUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Symptom:
        s = await self.symptoms.get_by_id_with_translations(symptom_id)
        if s is None:
            raise NotFoundError(code="symptom_not_found")
        before = _symptom_snapshot(s)

        if payload.slug is not None and payload.slug != s.slug:

            async def _exists(candidate: str) -> bool:
                other = await self.symptoms.get_by_slug(candidate)
                return other is not None and other.id != s.id

            s.slug = await unique_slug(payload.slug, _exists)

        if payload.icon_url is not None:
            s.icon_url = payload.icon_url
        if payload.sort_order is not None:
            s.sort_order = payload.sort_order
        if payload.is_active is not None:
            s.is_active = payload.is_active

        if payload.translations is not None:
            s.translations.clear()
            for t in payload.translations:
                s.translations.append(
                    SymptomTranslation(
                        language_code=t.language_code,
                        name=t.name,
                        synonyms=list(t.synonyms),
                    )
                )

        await self.symptoms.session.flush()
        await self.audit.record(
            admin_user_id=actor.id,
            action="update",
            entity_type="symptom",
            entity_id=s.id,
            before=before,
            after=_symptom_snapshot(s),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return s
