"""Catalog repository integration tests — real DB constraints exercised.

Covers:
* Manufacturer / Symptom / Category list_paginated + filters
* Product slug + sku uniqueness, soft-delete semantics
* Generated-column UNIQUE on ``product_images.primary_product_id``
* M:N relationship loading via ``get_by_id_with_full``
"""

from __future__ import annotations

from datetime import UTC

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import uuid7
from app.domain.catalog.models import Product, ProductImage, ProductTranslation
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    ProductRepository,
    SymptomRepository,
)
from tests.factories.catalog import (
    attach_ingredient,
    attach_symptom,
    seed_active_ingredient,
    seed_category,
    seed_manufacturer,
    seed_product,
    seed_symptom,
)

pytestmark = pytest.mark.integration


# ─── Manufacturers ────────────────────────────────────────────────────────────


async def test_manufacturer_list_paginated_filters_by_q(
    session: AsyncSession,
) -> None:
    repo = ManufacturerRepository(session)
    await seed_manufacturer(session, name="Bayer AG")
    await seed_manufacturer(session, name="Pfizer")
    await seed_manufacturer(session, name="Bayer Pharma")

    items, total = await repo.list_paginated(offset=0, limit=10, q="Bayer")
    assert total == 2
    assert {m.name for m in items} == {"Bayer AG", "Bayer Pharma"}


async def test_manufacturer_has_active_products(
    session: AsyncSession,
) -> None:
    repo = ManufacturerRepository(session)
    mfr = await seed_manufacturer(session, name="HasProducts Inc")
    cat = await seed_category(session, slug="cat-mfr-test")
    await seed_product(
        session,
        sku="MFR-PROD-1",
        slug="mfr-prod-1",
        manufacturer_id=mfr.id,
        category_id=cat.id,
    )
    assert await repo.has_active_products(mfr.id) is True

    empty = await seed_manufacturer(session, name="NoProducts Inc")
    assert await repo.has_active_products(empty.id) is False


# ─── Active ingredients ───────────────────────────────────────────────────────


async def test_active_ingredient_get_by_id_with_translations(
    session: AsyncSession,
) -> None:
    repo = ActiveIngredientRepository(session)
    seeded = await seed_active_ingredient(session, inn_name="paracetamol", name_ru="Парацетамол")
    found = await repo.get_by_id_with_translations(seeded.id)
    assert found is not None
    assert {t.language_code for t in found.translations} == {"ru"}
    assert found.translations[0].name == "Парацетамол"


# ─── Categories ───────────────────────────────────────────────────────────────


async def test_category_list_paginated_by_parent(session: AsyncSession) -> None:
    repo = CategoryRepository(session)
    parent = await seed_category(session, slug="cat-parent", name_ru="Родительская")
    await seed_category(session, slug="cat-child-1", parent_id=parent.id)
    await seed_category(session, slug="cat-child-2", parent_id=parent.id)
    await seed_category(session, slug="cat-other")

    items, total = await repo.list_paginated(parent_id=parent.id, offset=0, limit=10)
    assert total == 2
    assert {c.slug for c in items} == {"cat-child-1", "cat-child-2"}


# ─── Symptoms ─────────────────────────────────────────────────────────────────


async def test_symptom_list_paginated_active_only(session: AsyncSession) -> None:
    repo = SymptomRepository(session)
    s_active = await seed_symptom(session, slug="sym-active")
    s_inactive = await seed_symptom(session, slug="sym-inactive")
    s_inactive.is_active = False
    await session.flush()

    items, total = await repo.list_paginated(offset=0, limit=10, active_only=True)
    slugs = {s.slug for s in items}
    assert s_active.slug in slugs
    assert s_inactive.slug not in slugs
    assert total == 1


# ─── Products ─────────────────────────────────────────────────────────────────


async def test_product_sku_uniqueness(session: AsyncSession) -> None:
    cat = await seed_category(session, slug="cat-sku")
    await seed_product(session, sku="DUP-SKU", slug="p1", category_id=cat.id)

    p2 = Product(
        id=uuid7(),
        sku="DUP-SKU",
        slug="p2",
        category_id=cat.id,
        form="tablet",
        is_active=True,
        is_featured=False,
        requires_prescription=False,
        requires_cold_chain=False,
    )
    p2.translations.append(ProductTranslation(language_code="ru", name="X"))
    session.add(p2)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_product_slug_exists(session: AsyncSession) -> None:
    repo = ProductRepository(session)
    cat = await seed_category(session, slug="cat-slug-exists")
    await seed_product(session, sku="SLG-1", slug="my-product", category_id=cat.id)

    assert await repo.slug_exists("my-product") is True
    assert await repo.slug_exists("missing-slug") is False


async def test_product_get_by_id_with_full_loads_relationships(
    session: AsyncSession,
) -> None:
    repo = ProductRepository(session)
    cat = await seed_category(session, slug="cat-full")
    mfr = await seed_manufacturer(session, name="FullMfr")
    ai = await seed_active_ingredient(session, inn_name="ibuprofen")
    sym = await seed_symptom(session, slug="sym-pain")
    prod = await seed_product(
        session,
        sku="FULL-1",
        slug="full-1",
        category_id=cat.id,
        manufacturer_id=mfr.id,
    )
    await attach_ingredient(
        session,
        product=prod,
        active_ingredient_id=ai.id,
        dosage_amount="200.000",
        dosage_unit="mg",
    )
    await attach_symptom(session, product=prod, symptom_id=sym.id)

    found = await repo.get_by_id_with_full(prod.id)
    assert found is not None
    assert len(found.translations) == 1
    assert found.manufacturer is not None and found.manufacturer.name == "FullMfr"
    assert found.category is not None and found.category.slug == "cat-full"
    assert len(found.active_ingredients) == 1
    assert found.active_ingredients[0].active_ingredient.inn_name == "ibuprofen"
    assert len(found.symptoms) == 1
    assert found.symptoms[0].symptom.slug == "sym-pain"


async def test_product_soft_delete_excluded_from_list(
    session: AsyncSession,
) -> None:
    """``list_paginated`` filters out ``deleted_at IS NOT NULL``."""
    from datetime import datetime

    repo = ProductRepository(session)
    cat = await seed_category(session, slug="cat-soft")
    p_alive = await seed_product(session, sku="ALIVE-1", slug="alive-1", category_id=cat.id)
    p_dead = await seed_product(session, sku="DEAD-1", slug="dead-1", category_id=cat.id)
    p_dead.deleted_at = datetime.now(tz=UTC).replace(tzinfo=None)
    await session.flush()

    items, total = await repo.list_paginated(category_id=cat.id, offset=0, limit=10)
    skus = {p.sku for p in items}
    assert p_alive.sku in skus
    assert p_dead.sku not in skus


async def test_product_image_only_one_primary_per_product(
    session: AsyncSession,
) -> None:
    """Generated-column UNIQUE on ``primary_product_id`` blocks two primaries."""
    cat = await seed_category(session, slug="cat-img")
    prod = await seed_product(session, sku="IMG-1", slug="img-1", category_id=cat.id)
    img1 = ProductImage(
        product_id=prod.id,
        url="/x/1.webp",
        thumbnail_url="/x/1-t.webp",
        medium_url="/x/1-m.webp",
        large_url="/x/1-l.webp",
        sort_order=0,
        is_primary=True,
    )
    session.add(img1)
    await session.flush()

    img2 = ProductImage(
        product_id=prod.id,
        url="/x/2.webp",
        thumbnail_url="/x/2-t.webp",
        medium_url="/x/2-m.webp",
        large_url="/x/2-l.webp",
        sort_order=1,
        is_primary=True,
    )
    session.add(img2)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
