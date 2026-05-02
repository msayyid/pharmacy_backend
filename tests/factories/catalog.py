"""Catalog factories — minimal in-session and committed seeders.

Mirror the pattern from :mod:`tests.e2e.conftest` for identity:

* ``make_*`` (sync) — build an unpersisted ORM instance.
* ``seed_*`` (async, in-session) — add to ``AsyncSession``, flush, return.
* ``seed_*_committed`` (async) — open a one-off NullPool engine, commit,
  return primary key. Used by E2E tests so the FastAPI app sees the row.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
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

# ─── In-session seeders (use the test ``session`` fixture) ───────────────────


async def seed_manufacturer(
    session: AsyncSession, *, name: str, country_code: str | None = "DE"
) -> Manufacturer:
    m = Manufacturer(name=name, country_code=country_code, is_active=True)
    session.add(m)
    await session.flush()
    return m


async def seed_active_ingredient(
    session: AsyncSession,
    *,
    inn_name: str,
    name_ru: str | None = None,
) -> ActiveIngredient:
    ai = ActiveIngredient(inn_name=inn_name)
    if name_ru is not None:
        ai.translations.append(ActiveIngredientTranslation(language_code="ru", name=name_ru))
    session.add(ai)
    await session.flush()
    return ai


async def seed_category(
    session: AsyncSession,
    *,
    slug: str,
    name_ru: str = "Категория",
    parent_id: int | None = None,
) -> Category:
    c = Category(slug=slug, parent_id=parent_id, is_active=True, sort_order=0)
    c.translations.append(CategoryTranslation(language_code="ru", name=name_ru))
    session.add(c)
    await session.flush()
    return c


async def seed_symptom(
    session: AsyncSession,
    *,
    slug: str,
    name_ru: str = "Симптом",
) -> Symptom:
    s = Symptom(slug=slug, is_active=True, sort_order=0)
    s.translations.append(SymptomTranslation(language_code="ru", name=name_ru))
    session.add(s)
    await session.flush()
    return s


async def seed_product(
    session: AsyncSession,
    *,
    sku: str,
    slug: str,
    category_id: int,
    manufacturer_id: int | None = None,
    name_ru: str = "Продукт",
    form: str = "tablet",
    is_active: bool = True,
) -> Product:
    p = Product(
        id=uuid7(),
        sku=sku,
        slug=slug,
        category_id=category_id,
        manufacturer_id=manufacturer_id,
        form=form,
        is_active=is_active,
        is_featured=False,
        requires_prescription=False,
        requires_cold_chain=False,
    )
    p.translations.append(ProductTranslation(language_code="ru", name=name_ru))
    session.add(p)
    await session.flush()
    return p


async def attach_ingredient(
    session: AsyncSession,
    *,
    product: Product,
    active_ingredient_id: int,
    dosage_amount: str | None = None,
    dosage_unit: str | None = None,
) -> None:
    session.add(
        ProductActiveIngredient(
            product_id=product.id,
            active_ingredient_id=active_ingredient_id,
            dosage_amount=dosage_amount,  # type: ignore[arg-type]
            dosage_unit=dosage_unit,
        )
    )
    await session.flush()


async def attach_symptom(session: AsyncSession, *, product: Product, symptom_id: int) -> None:
    session.add(ProductSymptom(product_id=product.id, symptom_id=symptom_id))
    await session.flush()


# ─── Committed seeders for E2E tests ──────────────────────────────────────────


async def _committed_session() -> AsyncIterator[tuple[AsyncSession, Any]]:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s, engine
    await engine.dispose()


async def seed_manufacturer_committed(*, name: str) -> int:
    """Commit one Manufacturer, return its id."""
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            m = Manufacturer(name=name, country_code="DE", is_active=True)
            s.add(m)
            await s.commit()
            assert m.id is not None
            return m.id
    finally:
        await engine.dispose()


async def seed_category_committed(*, slug: str, name_ru: str = "Категория") -> int:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            c = Category(slug=slug, is_active=True, sort_order=0)
            c.translations.append(CategoryTranslation(language_code="ru", name=name_ru))
            s.add(c)
            await s.commit()
            assert c.id is not None
            return c.id
    finally:
        await engine.dispose()


async def seed_active_ingredient_committed(*, inn_name: str, name_ru: str | None = None) -> int:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            ai = ActiveIngredient(inn_name=inn_name)
            if name_ru is not None:
                ai.translations.append(
                    ActiveIngredientTranslation(language_code="ru", name=name_ru)
                )
            s.add(ai)
            await s.commit()
            assert ai.id is not None
            return ai.id
    finally:
        await engine.dispose()


async def seed_symptom_committed(*, slug: str, name_ru: str = "Симптом") -> int:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            sym = Symptom(slug=slug, is_active=True, sort_order=0)
            sym.translations.append(SymptomTranslation(language_code="ru", name=name_ru))
            s.add(sym)
            await s.commit()
            assert sym.id is not None
            return sym.id
    finally:
        await engine.dispose()


async def seed_product_committed(
    *,
    sku: str,
    slug: str,
    category_id: int,
    manufacturer_id: int | None = None,
    name_ru: str = "Продукт",
    form: str = "tablet",
    is_active: bool = True,
) -> UUID:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            p = Product(
                id=uuid7(),
                sku=sku,
                slug=slug,
                category_id=category_id,
                manufacturer_id=manufacturer_id,
                form=form,
                is_active=is_active,
                is_featured=False,
                requires_prescription=False,
                requires_cold_chain=False,
            )
            p.translations.append(ProductTranslation(language_code="ru", name=name_ru))
            s.add(p)
            await s.commit()
            return p.id
    finally:
        await engine.dispose()
