"""Storefront repository integration tests.

Covers:
* ``CategoryRepository.list_active_tree`` — soft-deleted + inactive
  categories excluded; translations eager-loaded.
* ``ProductRepository.list_for_category`` — joins on translation /
  branch_products / primary image; in-stock filter; sort options.
* ``ProductRepository.list_for_symptom`` — symptom-tag join.
* ``ProductRepository.list_substitutes`` — same primary AI + dose, in
  stock, excludes self, limit 4; falls back to same AI any-dose when
  nothing matches the dose.
* ``ProductRepository.suggest`` — prefix-match autocomplete.

The composite-ranked ``storefront_search`` is exercised by
``tests/unit/test_search_quality.py`` (which commits data so the
FULLTEXT index sees it).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog.models import (
    ProductActiveIngredient,
    ProductImage,
    ProductSymptom,
)
from app.domain.catalog.repositories import (
    CategoryRepository,
    ProductRepository,
    SymptomRepository,
)
from tests.factories.catalog import (
    seed_active_ingredient,
    seed_category,
    seed_manufacturer,
    seed_product,
    seed_symptom,
)
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)

pytestmark = pytest.mark.integration


async def test_list_active_tree_excludes_inactive(
    session: AsyncSession,
) -> None:
    repo = CategoryRepository(session)
    visible = await seed_category(session, slug="cat-tree-visible")
    hidden = await seed_category(session, slug="cat-tree-hidden")
    hidden.is_active = False
    await session.flush()

    rows = await repo.list_active_tree()
    slugs = {c.slug for c in rows}
    assert visible.slug in slugs
    assert hidden.slug not in slugs


async def test_symptom_list_active_with_translations(
    session: AsyncSession,
) -> None:
    repo = SymptomRepository(session)
    await seed_symptom(session, slug="head-active")
    inactive = await seed_symptom(session, slug="head-inactive")
    inactive.is_active = False
    await session.flush()

    rows = await repo.list_active_with_translations()
    slugs = {s.slug for s in rows}
    assert "head-active" in slugs
    assert "head-inactive" not in slugs


async def test_list_for_category_joins_and_in_stock_filter(
    session: AsyncSession,
) -> None:
    repo = ProductRepository(session)
    branch = await seed_branch(session, code="STORE-1")
    cat = await seed_category(session, slug="cat-store-1")

    p_in = await seed_product(session, sku="STORE-IN-1", slug="store-in-1", category_id=cat.id)
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=p_in.id,
        price=Decimal("100"),
        is_available=True,
        total_quantity=20,
        reserved_quantity=2,
    )
    p_out = await seed_product(session, sku="STORE-OUT-1", slug="store-out-1", category_id=cat.id)
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=p_out.id,
        price=Decimal("50"),
        is_available=True,
        total_quantity=0,
        reserved_quantity=0,
    )
    # Commit nothing — the joined SELECT runs in this same session.
    await session.flush()

    in_only, total = await repo.list_for_category(
        category_id=cat.id,
        branch_id=branch.id,
        language_code="ru",
        in_stock_only=True,
    )
    skus = {r.sku for r in in_only}
    assert p_in.sku in skus
    assert p_out.sku not in skus
    assert total == 1

    both, total_both = await repo.list_for_category(
        category_id=cat.id,
        branch_id=branch.id,
        language_code="ru",
        in_stock_only=False,
    )
    both_skus = {r.sku for r in both}
    assert p_in.sku in both_skus
    assert p_out.sku in both_skus
    assert total_both == 2


async def test_list_for_category_sort_price_asc(session: AsyncSession) -> None:
    repo = ProductRepository(session)
    branch = await seed_branch(session, code="STORE-SORT")
    cat = await seed_category(session, slug="cat-store-sort")

    p_cheap = await seed_product(session, sku="CHEAP-1", slug="cheap-1", category_id=cat.id)
    p_pricey = await seed_product(session, sku="PRICEY-1", slug="pricey-1", category_id=cat.id)
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=p_cheap.id,
        price=Decimal("10"),
        total_quantity=5,
    )
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=p_pricey.id,
        price=Decimal("500"),
        total_quantity=5,
    )

    rows, _ = await repo.list_for_category(
        category_id=cat.id,
        branch_id=branch.id,
        language_code="ru",
        sort="price_asc",
    )
    assert [r.sku for r in rows] == [p_cheap.sku, p_pricey.sku]

    rows_desc, _ = await repo.list_for_category(
        category_id=cat.id,
        branch_id=branch.id,
        language_code="ru",
        sort="price_desc",
    )
    assert [r.sku for r in rows_desc] == [p_pricey.sku, p_cheap.sku]


async def test_list_for_symptom_joins_through_product_symptoms(
    session: AsyncSession,
) -> None:
    repo = ProductRepository(session)
    branch = await seed_branch(session, code="SYMP-1")
    cat = await seed_category(session, slug="cat-symp-1")
    sym = await seed_symptom(session, slug="head-1")

    tagged = await seed_product(session, sku="HEAD-1", slug="head-prod-1", category_id=cat.id)
    untagged = await seed_product(session, sku="UNTAG-1", slug="untag-1", category_id=cat.id)
    session.add(ProductSymptom(product_id=tagged.id, symptom_id=sym.id))
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=tagged.id,
        total_quantity=5,
    )
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=untagged.id,
        total_quantity=5,
    )
    await session.flush()

    rows, total = await repo.list_for_symptom(
        symptom_id=sym.id, branch_id=branch.id, language_code="ru"
    )
    assert total == 1
    assert {r.sku for r in rows} == {tagged.sku}


async def test_list_substitutes_same_ai_same_dose(
    session: AsyncSession,
) -> None:
    repo = ProductRepository(session)
    branch = await seed_branch(session, code="SUB-1")
    cat = await seed_category(session, slug="cat-sub-1")
    ai = await seed_active_ingredient(session, inn_name="paracetamol-sub")

    src = await seed_product(session, sku="SUB-SRC", slug="sub-src", category_id=cat.id)
    twin = await seed_product(session, sku="SUB-TWIN", slug="sub-twin", category_id=cat.id)
    other_dose = await seed_product(session, sku="SUB-DOSE2", slug="sub-dose2", category_id=cat.id)
    other_ai = await seed_product(session, sku="SUB-OTHER", slug="sub-other", category_id=cat.id)

    # Source: 500mg.
    session.add(
        ProductActiveIngredient(
            product_id=src.id,
            active_ingredient_id=ai.id,
            dosage_amount=Decimal("500"),
            dosage_unit="mg",
        )
    )
    # Twin: same AI + same dose.
    session.add(
        ProductActiveIngredient(
            product_id=twin.id,
            active_ingredient_id=ai.id,
            dosage_amount=Decimal("500"),
            dosage_unit="mg",
        )
    )
    # Same AI, different dose.
    session.add(
        ProductActiveIngredient(
            product_id=other_dose.id,
            active_ingredient_id=ai.id,
            dosage_amount=Decimal("250"),
            dosage_unit="mg",
        )
    )
    # Different AI entirely (shouldn't appear).
    other_ai_id = (await seed_active_ingredient(session, inn_name="ibuprofen-sub")).id
    session.add(
        ProductActiveIngredient(
            product_id=other_ai.id,
            active_ingredient_id=other_ai_id,
            dosage_amount=Decimal("200"),
            dosage_unit="mg",
        )
    )
    for p in (src, twin, other_dose, other_ai):
        await seed_branch_product(
            session,
            branch_id=branch.id,
            product_id=p.id,
            price=Decimal("100"),
            total_quantity=10,
        )
    await session.flush()

    subs = await repo.list_substitutes(
        product_id=src.id,
        branch_id=branch.id,
        language_code="ru",
    )
    skus = {r.sku for r in subs}
    assert twin.sku in skus
    assert src.sku not in skus  # excludes self
    assert other_ai.sku not in skus  # different AI
    # Same-dose path was satisfied → other_dose excluded.
    assert other_dose.sku not in skus


async def test_list_substitutes_falls_back_to_any_dose(
    session: AsyncSession,
) -> None:
    repo = ProductRepository(session)
    branch = await seed_branch(session, code="SUB-FB")
    cat = await seed_category(session, slug="cat-sub-fb")
    ai = await seed_active_ingredient(session, inn_name="aspirin-sub-fb")

    src = await seed_product(session, sku="FB-SRC", slug="fb-src", category_id=cat.id)
    diff_dose = await seed_product(session, sku="FB-DIFF", slug="fb-diff", category_id=cat.id)
    session.add(
        ProductActiveIngredient(
            product_id=src.id,
            active_ingredient_id=ai.id,
            dosage_amount=Decimal("500"),
            dosage_unit="mg",
        )
    )
    session.add(
        ProductActiveIngredient(
            product_id=diff_dose.id,
            active_ingredient_id=ai.id,
            dosage_amount=Decimal("100"),
            dosage_unit="mg",
        )
    )
    for p in (src, diff_dose):
        await seed_branch_product(
            session,
            branch_id=branch.id,
            product_id=p.id,
            price=Decimal("75"),
            total_quantity=5,
        )
    await session.flush()

    subs = await repo.list_substitutes(
        product_id=src.id,
        branch_id=branch.id,
        language_code="ru",
    )
    assert {r.sku for r in subs} == {diff_dose.sku}


async def test_suggest_prefix_match(session: AsyncSession) -> None:
    repo = ProductRepository(session)
    branch = await seed_branch(session, code="SUGG-1")
    cat = await seed_category(session, slug="cat-sugg-1")
    p1 = await seed_product(
        session,
        sku="SUGG-1",
        slug="sugg-1",
        category_id=cat.id,
        name_ru="Парацетамол 500 мг",
    )
    p2 = await seed_product(
        session,
        sku="SUGG-2",
        slug="sugg-2",
        category_id=cat.id,
        name_ru="Ибупрофен 200 мг",
    )
    for p in (p1, p2):
        await seed_branch_product(
            session,
            branch_id=branch.id,
            product_id=p.id,
            total_quantity=10,
        )
    await session.flush()

    rows = await repo.suggest(prefix="пара", language_code="ru", branch_id=branch.id)
    assert any(r.sku == "SUGG-1" for r in rows)
    assert all(r.sku != "SUGG-2" for r in rows)


async def test_get_storefront_detail_returns_product_and_bp(
    session: AsyncSession,
) -> None:
    repo = ProductRepository(session)
    branch = await seed_branch(session, code="DET-1")
    cat = await seed_category(session, slug="cat-det-1")
    mfr = await seed_manufacturer(session, name="DetailMfr")
    prod = await seed_product(
        session,
        sku="DET-1",
        slug="det-1",
        category_id=cat.id,
        manufacturer_id=mfr.id,
    )
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=prod.id,
        price=Decimal("123.45"),
        total_quantity=20,
    )
    # Add a primary image to test the join.
    session.add(
        ProductImage(
            product_id=prod.id,
            url="/det/1.webp",
            thumbnail_url="/det/1-t.webp",
            sort_order=0,
            is_primary=True,
        )
    )
    await session.flush()
    # Ensure inventory batch lives so reconcile-style logic works.
    await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=prod.id,
        batch_number="DET-LOT-1",
        expiry_date=date.today() + timedelta(days=180),
    )
    await session.flush()

    result = await repo.get_storefront_detail(slug="det-1", branch_id=branch.id)
    assert result is not None
    product_back, bp_back = result
    assert product_back.id == prod.id
    assert bp_back is not None
    assert bp_back.price == Decimal("123.45")
    assert any(img.is_primary for img in product_back.images)
