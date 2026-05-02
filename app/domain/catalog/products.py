"""Product admin service — atomic CRUD with translations + M:N.

The crown jewel of Phase 5: a single ``create_product`` call accepts
translations, ``active_ingredients`` (with dose), and ``symptom_ids`` and
persists everything in one transaction.

Update follows replace semantics: passing a non-None ``translations``,
``active_ingredients``, or ``symptom_ids`` field replaces that full set
(cascade ``all, delete-orphan`` cleans up).

Reference: BACKEND_BLUEPRINT.md §12; PRODUCT_BLUEPRINT.md §8.5; CLAUDE_CODE_PROMPTS Phase 5.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.time import utcnow
from app.core.types import uuid7
from app.domain.catalog.models import (
    Product,
    ProductActiveIngredient,
    ProductSymptom,
    ProductTranslation,
)
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    ProductRepository,
    SymptomRepository,
)
from app.domain.catalog.schemas import (
    ProductCreate,
    ProductTranslationIn,
    ProductUpdate,
)
from app.domain.catalog.slug import slugify_name, unique_slug
from app.domain.identity.models import AdminUser
from app.domain.ops.services import AdminAuditLogService


def _pick_product_slug_source(translations: list[ProductTranslationIn]) -> str:
    for lang in ("ru", "ky", "en"):
        for t in translations:
            if t.language_code == lang:
                return t.name
    if translations:
        return translations[0].name
    return ""


def _product_snapshot(p: Product) -> dict[str, Any]:
    return {
        "sku": p.sku,
        "slug": p.slug,
        "manufacturer_id": p.manufacturer_id,
        "category_id": p.category_id,
        "form": p.form,
        "is_active": p.is_active,
        "is_featured": p.is_featured,
        "requires_prescription": p.requires_prescription,
        "requires_cold_chain": p.requires_cold_chain,
    }


class ProductService:
    """Admin CRUD for products + translations + ingredients (with dose) + symptoms."""

    def __init__(
        self,
        *,
        products: ProductRepository,
        manufacturers: ManufacturerRepository,
        categories: CategoryRepository,
        ingredients: ActiveIngredientRepository,
        symptoms: SymptomRepository,
        audit: AdminAuditLogService,
    ) -> None:
        self.products = products
        self.manufacturers = manufacturers
        self.categories = categories
        self.ingredients = ingredients
        self.symptoms = symptoms
        self.audit = audit

    async def get_product(self, product_id: UUID) -> Product:
        p = await self.products.get_by_id_with_full(product_id)
        if p is None:
            raise NotFoundError(code="product_not_found")
        return p

    async def create_product(
        self,
        *,
        payload: ProductCreate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Product:
        # ─── Validation ─────────────────────────────────────────────────────
        if payload.manufacturer_id is not None:
            mfr = await self.manufacturers.get_by_id(payload.manufacturer_id)
            if mfr is None:
                raise ValidationError(
                    code="manufacturer_not_found",
                    manufacturer_id=payload.manufacturer_id,
                )
        cat = await self.categories.get_by_id(payload.category_id)
        if cat is None:
            raise ValidationError(code="category_not_found", category_id=payload.category_id)

        if await self.products.get_by_sku(payload.sku) is not None:
            raise ConflictError(code="sku_exists", sku=payload.sku)

        # Slug: explicit, else from translation name
        slug_base = payload.slug or slugify_name(_pick_product_slug_source(payload.translations))
        if not slug_base:
            raise ValidationError(code="slug_or_translation_required")
        slug = await unique_slug(slug_base, self.products.slug_exists)

        # Validate ingredient + symptom IDs exist
        for pi in payload.active_ingredients:
            if (await self.ingredients.get_by_id(pi.active_ingredient_id)) is None:
                raise ValidationError(
                    code="ingredient_not_found",
                    active_ingredient_id=pi.active_ingredient_id,
                )
        for sid in payload.symptom_ids:
            if (await self.symptoms.get_by_id(sid)) is None:
                raise ValidationError(code="symptom_not_found", symptom_id=sid)

        # ─── Build aggregate ────────────────────────────────────────────────
        product = Product(
            id=uuid7(),
            sku=payload.sku,
            barcode=payload.barcode,
            slug=slug,
            manufacturer_id=payload.manufacturer_id,
            category_id=payload.category_id,
            form=payload.form,
            pack_size_label=payload.pack_size_label,
            pack_quantity=payload.pack_quantity,
            pack_unit=payload.pack_unit,
            requires_prescription=payload.requires_prescription,
            min_age=payload.min_age,
            max_per_order=payload.max_per_order,
            storage_temp_min_c=payload.storage_temp_min_c,
            storage_temp_max_c=payload.storage_temp_max_c,
            requires_cold_chain=payload.requires_cold_chain,
            weight_grams=payload.weight_grams,
            attributes=payload.attributes,
            is_active=payload.is_active,
            is_featured=payload.is_featured,
        )
        for t in payload.translations:
            product.translations.append(
                ProductTranslation(
                    language_code=t.language_code,
                    name=t.name,
                    short_description=t.short_description,
                    description=t.description,
                    usage_instructions=t.usage_instructions,
                    side_effects=t.side_effects,
                    contraindications=t.contraindications,
                    composition=t.composition,
                )
            )
        for pi in payload.active_ingredients:
            product.active_ingredients.append(
                ProductActiveIngredient(
                    active_ingredient_id=pi.active_ingredient_id,
                    dosage_amount=pi.dosage_amount,
                    dosage_unit=pi.dosage_unit,
                )
            )
        for sid in payload.symptom_ids:
            product.symptoms.append(ProductSymptom(symptom_id=sid))

        await self.products.add(product)
        await self.audit.record(
            admin_user_id=actor.id,
            action="create",
            entity_type="product",
            entity_id=product.id,
            after=_product_snapshot(product),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return product

    async def update_product(  # noqa: PLR0912, PLR0915 — patch-shape with replace-M:N
        self,
        product_id: UUID,
        *,
        payload: ProductUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Product:
        product = await self.products.get_by_id_with_full(product_id)
        if product is None:
            raise NotFoundError(code="product_not_found")
        before = _product_snapshot(product)

        # Reference checks first
        if (
            payload.manufacturer_id is not None
            and payload.manufacturer_id != product.manufacturer_id
        ) and (await self.manufacturers.get_by_id(payload.manufacturer_id)) is None:
            raise ValidationError(
                code="manufacturer_not_found",
                manufacturer_id=payload.manufacturer_id,
            )
        if (payload.category_id is not None and payload.category_id != product.category_id) and (
            await self.categories.get_by_id(payload.category_id)
        ) is None:
            raise ValidationError(code="category_not_found", category_id=payload.category_id)

        # Scalar fields
        if payload.barcode is not None:
            product.barcode = payload.barcode
        if payload.slug is not None and payload.slug != product.slug:

            async def _exists(s: str) -> bool:
                other = await self.products.get_by_slug(s)
                return other is not None and other.id != product.id

            product.slug = await unique_slug(payload.slug, _exists)
        if payload.manufacturer_id is not None:
            product.manufacturer_id = payload.manufacturer_id
        if payload.category_id is not None:
            product.category_id = payload.category_id
        if payload.form is not None:
            product.form = payload.form
        if payload.pack_size_label is not None:
            product.pack_size_label = payload.pack_size_label
        if payload.pack_quantity is not None:
            product.pack_quantity = payload.pack_quantity
        if payload.pack_unit is not None:
            product.pack_unit = payload.pack_unit
        if payload.requires_prescription is not None:
            product.requires_prescription = payload.requires_prescription
        if payload.min_age is not None:
            product.min_age = payload.min_age
        if payload.max_per_order is not None:
            product.max_per_order = payload.max_per_order
        if payload.storage_temp_min_c is not None:
            product.storage_temp_min_c = payload.storage_temp_min_c
        if payload.storage_temp_max_c is not None:
            product.storage_temp_max_c = payload.storage_temp_max_c
        if payload.requires_cold_chain is not None:
            product.requires_cold_chain = payload.requires_cold_chain
        if payload.weight_grams is not None:
            product.weight_grams = payload.weight_grams
        if payload.attributes is not None:
            product.attributes = payload.attributes
        if payload.is_active is not None:
            product.is_active = payload.is_active
        if payload.is_featured is not None:
            product.is_featured = payload.is_featured

        # Replace collections if provided
        if payload.translations is not None:
            product.translations.clear()
            for t in payload.translations:
                product.translations.append(
                    ProductTranslation(
                        language_code=t.language_code,
                        name=t.name,
                        short_description=t.short_description,
                        description=t.description,
                        usage_instructions=t.usage_instructions,
                        side_effects=t.side_effects,
                        contraindications=t.contraindications,
                        composition=t.composition,
                    )
                )

        if payload.active_ingredients is not None:
            for pi in payload.active_ingredients:
                if (await self.ingredients.get_by_id(pi.active_ingredient_id)) is None:
                    raise ValidationError(
                        code="ingredient_not_found",
                        active_ingredient_id=pi.active_ingredient_id,
                    )
            product.active_ingredients.clear()
            for pi in payload.active_ingredients:
                product.active_ingredients.append(
                    ProductActiveIngredient(
                        active_ingredient_id=pi.active_ingredient_id,
                        dosage_amount=pi.dosage_amount,
                        dosage_unit=pi.dosage_unit,
                    )
                )

        if payload.symptom_ids is not None:
            for sid in payload.symptom_ids:
                if (await self.symptoms.get_by_id(sid)) is None:
                    raise ValidationError(code="symptom_not_found", symptom_id=sid)
            product.symptoms.clear()
            for sid in payload.symptom_ids:
                product.symptoms.append(ProductSymptom(symptom_id=sid))

        await self.products.session.flush()
        await self.audit.record(
            admin_user_id=actor.id,
            action="update",
            entity_type="product",
            entity_id=product.id,
            before=before,
            after=_product_snapshot(product),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return product

    async def soft_delete_product(
        self,
        product_id: UUID,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        product = await self.products.get_by_id(product_id)
        if product is None:
            raise NotFoundError(code="product_not_found")
        before = _product_snapshot(product)
        product.deleted_at = utcnow()
        await self.products.session.flush()
        await self.audit.record(
            admin_user_id=actor.id,
            action="delete",
            entity_type="product",
            entity_id=product.id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # ─── Helper for the import service ──────────────────────────────────────

    async def upsert_from_import(
        self,
        *,
        sku: str,
        payload: ProductCreate | ProductUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[Product, bool]:
        """Bulk-import upsert. Returns ``(product, created)``.

        If a product with this SKU exists (including soft-deleted), update
        it; otherwise create.
        """
        existing = await self.products.get_by_sku(sku)
        if existing is None:
            assert isinstance(payload, ProductCreate)
            product = await self.create_product(
                payload=payload,
                actor=actor,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return (product, True)
        # Update path — payload here is logically ProductUpdate-shaped
        update_payload = (
            payload
            if isinstance(payload, ProductUpdate)
            else ProductUpdate(**payload.model_dump(exclude={"sku"}))
        )
        product = await self.update_product(
            existing.id,
            payload=update_payload,
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return (product, False)
