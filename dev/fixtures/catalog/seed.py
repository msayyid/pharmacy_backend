"""Seed the catalog from the JSON fixtures next to this file.

Idempotent: skips rows whose unique key already exists. Safe to re-run.

Usage:
    uv run python -m dev.fixtures.catalog.seed

Reads ``MYSQL_DSN`` from the environment (so ``.env`` overrides apply).
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

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
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    ProductRepository,
    SymptomRepository,
)

_HERE = Path(__file__).parent


def _load(name: str) -> list[dict[str, Any]]:
    return json.loads((_HERE / name).read_text())


async def _seed_manufacturers(session: Any) -> dict[str, int]:
    repo = ManufacturerRepository(session)
    out: dict[str, int] = {}
    for row in _load("manufacturers.json"):
        existing = await repo.get_by_name(row["name"])
        if existing is not None:
            out[row["name"]] = existing.id
            continue
        m = Manufacturer(
            name=row["name"],
            country_code=row.get("country_code"),
            website=row.get("website"),
            is_active=True,
        )
        session.add(m)
        await session.flush()
        out[row["name"]] = m.id
    return out


async def _seed_categories(session: Any) -> dict[str, int]:
    repo = CategoryRepository(session)
    rows = _load("categories.json")
    out: dict[str, int] = {}
    # Two-pass so children resolve their parents.
    for row in rows:
        if (existing := await repo.get_by_slug(row["slug"])) is not None:
            out[row["slug"]] = existing.id
            continue
        if row["parent_slug"] is not None:
            continue
        c = Category(
            slug=row["slug"],
            sort_order=row.get("sort_order", 0),
            is_active=True,
        )
        for t in row["translations"]:
            c.translations.append(CategoryTranslation(**t))
        session.add(c)
        await session.flush()
        out[row["slug"]] = c.id
    for row in rows:
        if row["parent_slug"] is None:
            continue
        if (existing := await repo.get_by_slug(row["slug"])) is not None:
            out[row["slug"]] = existing.id
            continue
        c = Category(
            slug=row["slug"],
            parent_id=out[row["parent_slug"]],
            sort_order=row.get("sort_order", 0),
            is_active=True,
        )
        for t in row["translations"]:
            c.translations.append(CategoryTranslation(**t))
        session.add(c)
        await session.flush()
        out[row["slug"]] = c.id
    return out


async def _seed_ingredients(session: Any) -> dict[str, int]:
    repo = ActiveIngredientRepository(session)
    out: dict[str, int] = {}
    for row in _load("ingredients.json"):
        if (existing := await repo.get_by_inn(row["inn_name"])) is not None:
            out[row["inn_name"]] = existing.id
            continue
        ai = ActiveIngredient(inn_name=row["inn_name"])
        for t in row["translations"]:
            ai.translations.append(ActiveIngredientTranslation(**t))
        session.add(ai)
        await session.flush()
        out[row["inn_name"]] = ai.id
    return out


async def _seed_symptoms(session: Any) -> dict[str, int]:
    repo = SymptomRepository(session)
    out: dict[str, int] = {}
    for row in _load("symptoms.json"):
        if (existing := await repo.get_by_slug(row["slug"])) is not None:
            out[row["slug"]] = existing.id
            continue
        s = Symptom(
            slug=row["slug"],
            sort_order=row.get("sort_order", 0),
            is_active=True,
        )
        for t in row["translations"]:
            s.translations.append(SymptomTranslation(**t))
        session.add(s)
        await session.flush()
        out[row["slug"]] = s.id
    return out


async def _seed_products(
    session: Any,
    *,
    manufacturers: dict[str, int],
    categories: dict[str, int],
    ingredients: dict[str, int],
    symptoms: dict[str, int],
) -> int:
    repo = ProductRepository(session)
    n = 0
    for row in _load("products.json"):
        if (await repo.get_by_sku(row["sku"])) is not None:
            continue
        p = Product(
            id=uuid7(),
            sku=row["sku"],
            slug=row["sku"].lower().replace("-", "-"),
            manufacturer_id=manufacturers[row["manufacturer_name"]],
            category_id=categories[row["category_slug"]],
            form=row["form"],
            pack_size_label=row.get("pack_size_label"),
            pack_quantity=Decimal(row["pack_quantity"]) if row.get("pack_quantity") else None,
            pack_unit=row.get("pack_unit"),
            requires_prescription=row.get("requires_prescription", False),
            requires_cold_chain=row.get("requires_cold_chain", False),
            is_active=row.get("is_active", True),
            is_featured=row.get("is_featured", False),
        )
        for t in row["translations"]:
            p.translations.append(ProductTranslation(**t))
        for ai in row.get("active_ingredients", []):
            p.active_ingredients.append(
                ProductActiveIngredient(
                    active_ingredient_id=ingredients[ai["inn_name"]],
                    dosage_amount=Decimal(ai["dosage_amount"]) if ai.get("dosage_amount") else None,
                    dosage_unit=ai.get("dosage_unit"),
                )
            )
        for sym_slug in row.get("symptom_slugs", []):
            p.symptoms.append(ProductSymptom(symptom_id=symptoms[sym_slug]))
        session.add(p)
        await session.flush()
        n += 1
    return n


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            mfrs = await _seed_manufacturers(session)
            cats = await _seed_categories(session)
            ings = await _seed_ingredients(session)
            syms = await _seed_symptoms(session)
            n_products = await _seed_products(
                session,
                manufacturers=mfrs,
                categories=cats,
                ingredients=ings,
                symptoms=syms,
            )
            await session.commit()
            print(
                f"Seeded {len(mfrs)} manufacturers, {len(cats)} categories, "
                f"{len(ings)} ingredients, {len(syms)} symptoms, "
                f"{n_products} products."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
