"""E2E — guest storefront flow over HTTP.

Walks through ``GET /api/v1/categories``, ``GET
/api/v1/categories/{slug}/products``, ``GET /api/v1/products/{slug}``,
``GET /api/v1/symptoms``, ``GET /api/v1/branches``, ``GET /api/v1/search``,
and ``GET /api/v1/search/suggest`` — all without auth.

Uses committed seeders so the FastAPI app sees the rows.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.types import uuid7
from app.domain.catalog.models import (
    ActiveIngredient,
    ActiveIngredientTranslation,
    Category,
    CategoryTranslation,
    Manufacturer,
    Product,
    ProductActiveIngredient,
    ProductSymptom,
    ProductTranslation,
    Symptom,
    SymptomTranslation,
)
from app.domain.inventory.models import Branch, BranchProduct, InventoryBatch

pytestmark = pytest.mark.e2e


async def _seed_full_storefront(*, with_substitutes: bool = True) -> dict:  # noqa: PLR0915
    """Commit a small storefront snapshot.

    Returns ``{"branch_id": int, "product_id": str, "slug": str,
    "category_slug": str, "symptom_slug": str}``.
    """
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    out: dict = {}
    try:
        async with factory() as s:
            # Storefront ``BranchIdDep`` always resolves to ``branch_id=1``.
            # First test creates id=1 implicitly; subsequent tests look it
            # up by id so all tests share the same branch.
            from sqlalchemy import select as _select

            existing = (await s.execute(_select(Branch).where(Branch.id == 1))).scalar_one_or_none()
            if existing is not None:
                branch_id = existing.id
            else:
                branch = Branch(
                    code=f"SF-BR-{uuid.uuid4().hex[:6].upper()}",
                    name="Storefront Test",
                    address="мкр Асанбай 12",
                    is_active=True,
                )
                s.add(branch)
                await s.flush()
                branch_id = branch.id
            out["branch_id"] = branch_id

            cat = Category(
                slug=f"sf-cat-{uuid.uuid4().hex[:6]}",
                is_active=True,
                sort_order=10,
            )
            cat.translations.append(CategoryTranslation(language_code="ru", name="Витамины (тест)"))
            s.add(cat)
            await s.flush()
            out["category_slug"] = cat.slug

            sym = Symptom(
                slug=f"sf-sym-{uuid.uuid4().hex[:6]}",
                is_active=True,
                sort_order=10,
            )
            sym.translations.append(
                SymptomTranslation(language_code="ru", name="Головная боль (тест)")
            )
            s.add(sym)
            await s.flush()
            out["symptom_slug"] = sym.slug

            ai = ActiveIngredient(inn_name=f"sf-ai-{uuid.uuid4().hex[:6]}")
            ai.translations.append(
                ActiveIngredientTranslation(language_code="ru", name="ТестВещество")
            )
            s.add(ai)
            await s.flush()

            mfr = Manufacturer(name=f"SFMfr-{uuid.uuid4().hex[:6]}", is_active=True)
            s.add(mfr)
            await s.flush()

            uniq = uuid.uuid4().hex[:6]
            slug = f"sf-prod-{uniq}"
            prod = Product(
                id=uuid7(),
                sku=f"SF-PROD-{uniq}",
                slug=slug,
                category_id=cat.id,
                manufacturer_id=mfr.id,
                form="tablet",
                pack_size_label="20 таблеток",
                is_active=True,
                is_featured=False,
                requires_prescription=False,
                requires_cold_chain=False,
            )
            prod.translations.append(
                ProductTranslation(
                    language_code="ru",
                    # Per-test-unique name so the suggest endpoint can
                    # find this exact seed across an accumulating test
                    # session (data persists until session-end downgrade).
                    name=f"Тестовый-{uniq} продукт 500 мг",
                    short_description="Описание",
                    description="Полное описание продукта.",
                )
            )
            prod.active_ingredients.append(
                ProductActiveIngredient(
                    active_ingredient_id=ai.id,
                    dosage_amount=Decimal("500"),
                    dosage_unit="mg",
                )
            )
            prod.symptoms.append(ProductSymptom(symptom_id=sym.id))
            s.add(prod)
            await s.flush()
            out["product_id"] = str(prod.id)
            out["slug"] = prod.slug

            bp = BranchProduct(
                branch_id=branch_id,
                product_id=prod.id,
                price=Decimal("100"),
                currency="KGS",
                is_available=True,
                total_quantity=20,
                reserved_quantity=0,
                low_stock_threshold=5,
            )
            s.add(bp)
            s.add(
                InventoryBatch(
                    branch_id=branch_id,
                    product_id=prod.id,
                    batch_number=f"SF-LOT-{uuid.uuid4().hex[:6]}",
                    expiry_date=date.today() + timedelta(days=365),
                    quantity_received=20,
                    quantity_remaining=20,
                    quantity_reserved=0,
                    cost_price=Decimal("50"),
                    currency="KGS",
                )
            )

            if with_substitutes:
                # Substitute: same AI + dose, different product, in stock.
                sub = Product(
                    id=uuid7(),
                    sku=f"SF-SUB-{uuid.uuid4().hex[:6]}",
                    slug=f"sf-sub-{uuid.uuid4().hex[:6]}",
                    category_id=cat.id,
                    manufacturer_id=mfr.id,
                    form="tablet",
                    is_active=True,
                    is_featured=False,
                    requires_prescription=False,
                    requires_cold_chain=False,
                )
                sub.translations.append(
                    ProductTranslation(language_code="ru", name="Тестовый продукт-Б 500 мг")
                )
                sub.active_ingredients.append(
                    ProductActiveIngredient(
                        active_ingredient_id=ai.id,
                        dosage_amount=Decimal("500"),
                        dosage_unit="mg",
                    )
                )
                s.add(sub)
                await s.flush()
                s.add(
                    BranchProduct(
                        branch_id=branch_id,
                        product_id=sub.id,
                        price=Decimal("80"),
                        currency="KGS",
                        is_available=True,
                        total_quantity=10,
                        reserved_quantity=0,
                        low_stock_threshold=5,
                    )
                )
                s.add(
                    InventoryBatch(
                        branch_id=branch_id,
                        product_id=sub.id,
                        batch_number=f"SF-SUB-LOT-{uuid.uuid4().hex[:6]}",
                        expiry_date=date.today() + timedelta(days=365),
                        quantity_received=10,
                        quantity_remaining=10,
                        quantity_reserved=0,
                        cost_price=Decimal("40"),
                        currency="KGS",
                    )
                )

            await s.commit()
        return out
    finally:
        await engine.dispose()


# ─── Categories ──────────────────────────────────────────────────────────────


async def test_categories_tree_returns_active_categories(
    client: AsyncClient, redis_clean: None
) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    r = await client.get("/api/v1/categories", headers={"Accept-Language": "ru"})
    assert r.status_code == 200
    nodes = r.json()
    slugs = {n["slug"] for n in nodes}
    assert seed["category_slug"] in slugs


async def test_category_products_filters_in_stock(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    r = await client.get(
        f"/api/v1/categories/{seed['category_slug']}/products",
        headers={"Accept-Language": "ru"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert any(p["slug"] == seed["slug"] for p in body["items"])
    # All in-stock by default.
    assert all(p["is_in_stock"] for p in body["items"])


# ─── Symptoms ────────────────────────────────────────────────────────────────


async def test_symptoms_list(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    r = await client.get("/api/v1/symptoms", headers={"Accept-Language": "ru"})
    assert r.status_code == 200
    slugs = {s["slug"] for s in r.json()}
    assert seed["symptom_slug"] in slugs


async def test_symptom_products(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    r = await client.get(
        f"/api/v1/symptoms/{seed['symptom_slug']}/products",
        headers={"Accept-Language": "ru"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1


# ─── Product detail + related ────────────────────────────────────────────────


async def test_product_detail(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    r = await client.get(f"/api/v1/products/{seed['slug']}", headers={"Accept-Language": "ru"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == seed["slug"]
    assert body["is_in_stock"] is True
    assert body["price"] == "100.00" or float(body["price"]) == 100.0


async def test_product_related_returns_substitute(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=True)
    r = await client.get(
        f"/api/v1/products/{seed['slug']}/related",
        headers={"Accept-Language": "ru"},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 1
    assert all(item["id"] != seed["product_id"] for item in items)


# ─── Branches ────────────────────────────────────────────────────────────────


async def test_branches_list(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    r = await client.get("/api/v1/branches")
    assert r.status_code == 200
    rows = r.json()
    assert any(b["id"] == seed["branch_id"] for b in rows)


# ─── Search + suggest ────────────────────────────────────────────────────────


async def test_search_returns_results(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    # The per-seed unique-suffix name makes the query stable across the
    # accumulating session.
    uniq = seed["slug"].split("-")[-1]
    r = await client.get(
        "/api/v1/search",
        params={"q": uniq},
        headers={"Accept-Language": "ru"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert any(item["slug"] == seed["slug"] for item in body["items"])


async def test_search_q_too_short_400(client: AsyncClient, redis_clean: None) -> None:
    r = await client.get("/api/v1/search", params={"q": "a"}, headers={"Accept-Language": "ru"})
    # FastAPI Query(min_length=2) → 422.
    assert r.status_code == 422


async def test_search_suggest(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_full_storefront(with_substitutes=False)
    uniq = seed["slug"].split("-")[-1]
    # Use the unique suffix as the query so the seeded product is the
    # unambiguous match.
    r = await client.get(
        "/api/v1/search/suggest",
        params={"q": f"тестовый-{uniq}"},
        headers={"Accept-Language": "ru"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "products" in body
    slugs = {p["slug"] for p in body["products"]}
    assert seed["slug"] in slugs
