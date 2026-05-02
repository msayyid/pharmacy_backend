"""Unit-ish tests for the product CSV importer.

Exercises the service against a real DB session so the parser, the
category-path resolver, and ``upsert_from_import`` round-trip together.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog.import_csv import ProductImportService, TooManyRowsError
from app.domain.catalog.products import ProductService
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    ProductRepository,
    SymptomRepository,
)
from app.domain.identity.models import AdminUser
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from tests.factories.catalog import (
    seed_active_ingredient,
    seed_category,
    seed_manufacturer,
    seed_symptom,
)

pytestmark = pytest.mark.unit


def _make_import_service(session: AsyncSession) -> ProductImportService:
    audit = AdminAuditLogService(AdminAuditLogRepository(session))
    products = ProductRepository(session)
    manufacturers = ManufacturerRepository(session)
    categories = CategoryRepository(session)
    ingredients = ActiveIngredientRepository(session)
    symptoms = SymptomRepository(session)
    product_service = ProductService(
        products=products,
        manufacturers=manufacturers,
        categories=categories,
        ingredients=ingredients,
        symptoms=symptoms,
        audit=audit,
    )
    return ProductImportService(
        products=products,
        manufacturers=manufacturers,
        categories=categories,
        ingredients=ingredients,
        symptoms=symptoms,
        product_service=product_service,
    )


async def _make_actor(session: AsyncSession, *, suffix: str) -> AdminUser:
    admin = AdminUser(
        email=f"importer-{suffix}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="Imp",
        last_name="Actor",
        role="super_admin",
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin


_HEADER = (
    "sku,barcode,slug,manufacturer,category_path,form,pack_size_label,"
    "pack_quantity,pack_unit,requires_prescription,min_age,max_per_order,"
    "weight_grams,requires_cold_chain,storage_temp_min_c,storage_temp_max_c,"
    "is_active,is_featured,name_ru,name_ky,name_en,short_description_ru,"
    "short_description_ky,short_description_en,description_ru,description_ky,"
    "description_en,active_ingredients,symptoms\n"
)


def _row(**overrides: str) -> str:
    fields: dict[str, str] = {
        "sku": "",
        "barcode": "",
        "slug": "",
        "manufacturer": "",
        "category_path": "",
        "form": "tablet",
        "pack_size_label": "",
        "pack_quantity": "",
        "pack_unit": "",
        "requires_prescription": "",
        "min_age": "",
        "max_per_order": "",
        "weight_grams": "",
        "requires_cold_chain": "",
        "storage_temp_min_c": "",
        "storage_temp_max_c": "",
        "is_active": "",
        "is_featured": "",
        "name_ru": "Продукт",
        "name_ky": "",
        "name_en": "",
        "short_description_ru": "",
        "short_description_ky": "",
        "short_description_en": "",
        "description_ru": "",
        "description_ky": "",
        "description_en": "",
        "active_ingredients": "",
        "symptoms": "",
    }
    fields.update(overrides)
    return ",".join(fields[k] for k in fields) + "\n"


async def test_dry_run_counts_create_vs_update(session: AsyncSession) -> None:
    svc = _make_import_service(session)
    cat = await seed_category(session, slug="cat-imp-1")
    # Pre-existing product to test "update" branch
    from tests.factories.catalog import seed_product

    await seed_product(session, sku="EXIST-1", slug="exist-1", category_id=cat.id)

    csv_text = (
        _HEADER
        + _row(sku="NEW-1", category_path=cat.slug)
        + _row(sku="EXIST-1", category_path=cat.slug)
    )
    summary = await svc.dry_run(csv_text.encode("utf-8"))
    assert summary.n_create == 1
    assert summary.n_update == 1
    assert summary.n_skip == 0
    assert summary.errors == []


async def test_dry_run_collects_row_errors(session: AsyncSession) -> None:
    svc = _make_import_service(session)
    cat = await seed_category(session, slug="cat-imp-2")
    csv_text = (
        _HEADER
        + _row(sku="OK-1", category_path=cat.slug)
        + _row(sku="BAD-1", category_path="nonexistent")
        + _row(sku="", category_path=cat.slug)
    )
    summary = await svc.dry_run(csv_text.encode("utf-8"))
    assert summary.n_create == 1
    assert summary.n_skip == 2
    assert {e.message for e in summary.errors} >= {
        "missing sku",
        "category not found: nonexistent",
    }


async def test_apply_creates_products(session: AsyncSession) -> None:
    svc = _make_import_service(session)
    actor = await _make_actor(session, suffix="apply-create")
    cat = await seed_category(session, slug="cat-imp-3")

    csv_text = _HEADER + _row(sku="APPL-1", category_path=cat.slug)
    summary = await svc.apply(csv_text.encode("utf-8"), actor=actor)
    assert summary.n_create == 1
    assert summary.errors == []

    repo = ProductRepository(session)
    p = await repo.get_by_sku("APPL-1")
    assert p is not None
    assert p.category_id == cat.id


async def test_apply_aborts_when_dry_run_has_errors(
    session: AsyncSession,
) -> None:
    svc = _make_import_service(session)
    actor = await _make_actor(session, suffix="apply-abort")
    cat = await seed_category(session, slug="cat-imp-4")

    csv_text = (
        _HEADER + _row(sku="OK-A", category_path=cat.slug) + _row(sku="BAD-A", category_path="nope")
    )
    summary = await svc.apply(csv_text.encode("utf-8"), actor=actor)
    assert summary.n_create == 0
    assert summary.n_update == 0
    assert summary.n_skip > 0
    repo = ProductRepository(session)
    assert await repo.get_by_sku("OK-A") is None


async def test_too_many_rows_raises(session: AsyncSession) -> None:
    svc = _make_import_service(session)
    svc.max_rows = 2
    cat = await seed_category(session, slug="cat-imp-5")
    csv_text = (
        _HEADER
        + _row(sku="A1", category_path=cat.slug)
        + _row(sku="A2", category_path=cat.slug)
        + _row(sku="A3", category_path=cat.slug)
    )
    with pytest.raises(TooManyRowsError):
        await svc.dry_run(csv_text.encode("utf-8"))


async def test_resolves_nested_category_path(session: AsyncSession) -> None:
    svc = _make_import_service(session)
    parent = await seed_category(session, slug="cat-imp-parent")
    child = await seed_category(session, slug="cat-imp-child", parent_id=parent.id)

    csv_text = _HEADER + _row(sku="NEST-1", category_path=f"{parent.slug}/{child.slug}")
    summary = await svc.dry_run(csv_text.encode("utf-8"))
    assert summary.n_create == 1
    assert summary.errors == []


async def test_unknown_manufacturer_is_row_error(
    session: AsyncSession,
) -> None:
    svc = _make_import_service(session)
    cat = await seed_category(session, slug="cat-imp-6")
    await seed_manufacturer(session, name="KnownPharma")
    csv_text = _HEADER + _row(sku="MFR-A", category_path=cat.slug, manufacturer="UnknownPharma")
    summary = await svc.dry_run(csv_text.encode("utf-8"))
    assert summary.n_skip == 1
    assert summary.errors[0].field == "manufacturer"


async def test_active_ingredients_and_symptoms_resolved(
    session: AsyncSession,
) -> None:
    svc = _make_import_service(session)
    actor = await _make_actor(session, suffix="ai-syms")
    cat = await seed_category(session, slug="cat-imp-7")
    ai = await seed_active_ingredient(session, inn_name="paracetamol")
    sym = await seed_symptom(session, slug="cold")

    csv_text = _HEADER + _row(
        sku="ING-1",
        category_path=cat.slug,
        active_ingredients=f"{ai.inn_name}:500:mg",
        symptoms=sym.slug,
    )
    summary = await svc.apply(csv_text.encode("utf-8"), actor=actor)
    assert summary.n_create == 1
    assert summary.errors == []
