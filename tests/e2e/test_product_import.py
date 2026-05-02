"""E2E — bulk product import dry-run + apply via multipart upload."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import seed_admin_committed
from tests.factories.catalog import seed_category_committed

pytestmark = pytest.mark.e2e


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def _login_as_admin(client: AsyncClient, *, prefix: str) -> dict[str, str]:
    email = _unique_email(prefix)
    await seed_admin_committed(email=email, password="ok", role="super_admin")
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "ok"},
    )
    assert r.status_code == 200, r.text
    return {"admin_session": r.cookies["admin_session"]}


_HEADER = (
    "sku,barcode,slug,manufacturer,category_path,form,pack_size_label,"
    "pack_quantity,pack_unit,requires_prescription,min_age,max_per_order,"
    "weight_grams,requires_cold_chain,storage_temp_min_c,storage_temp_max_c,"
    "is_active,is_featured,name_ru,name_ky,name_en,short_description_ru,"
    "short_description_ky,short_description_en,description_ru,description_ky,"
    "description_en,active_ingredients,symptoms\n"
)


def _row(sku: str, category_path: str, name_ru: str = "Продукт") -> str:
    return f"{sku},,,,{category_path},tablet,,,,,,,,,,,,," f"{name_ru},,,,,,,,,,\n"


async def test_import_dry_run_returns_summary(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_admin(client, prefix="imp-dry")
    cat_slug = f"cat-imp-{uuid.uuid4().hex[:6]}"
    await seed_category_committed(slug=cat_slug)

    csv_text = _HEADER + _row(f"DRY-1-{uuid.uuid4().hex[:6]}", cat_slug)

    r = await client.post(
        "/api/admin/v1/products/import/dry-run",
        cookies=cookies,
        files={"file": ("upload.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_create"] == 1
    assert body["n_update"] == 0
    assert body["errors"] == []


async def test_import_apply_creates_product(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_admin(client, prefix="imp-apply")
    cat_slug = f"cat-apply-{uuid.uuid4().hex[:6]}"
    await seed_category_committed(slug=cat_slug)

    sku = f"APPLY-{uuid.uuid4().hex[:8]}"
    csv_text = _HEADER + _row(sku, cat_slug)

    r = await client.post(
        "/api/admin/v1/products/import/apply",
        cookies=cookies,
        files={"file": ("upload.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["n_create"] == 1

    # Verify it's now visible via /products list
    r2 = await client.get("/api/admin/v1/products", cookies=cookies, params={"q": sku})
    assert r2.status_code == 200
    assert any(p["sku"] == sku for p in r2.json()["items"])


async def test_import_dry_run_reports_row_errors(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_admin(client, prefix="imp-err")
    cat_slug = f"cat-err-{uuid.uuid4().hex[:6]}"
    await seed_category_committed(slug=cat_slug)

    csv_text = (
        _HEADER
        + _row(f"OK-{uuid.uuid4().hex[:6]}", cat_slug)
        + _row(f"BAD-{uuid.uuid4().hex[:6]}", "nonexistent-category")
    )
    r = await client.post(
        "/api/admin/v1/products/import/dry-run",
        cookies=cookies,
        files={"file": ("upload.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["n_create"] == 1
    assert body["n_skip"] == 1
    assert any("category not found" in e["message"] for e in body["errors"])
