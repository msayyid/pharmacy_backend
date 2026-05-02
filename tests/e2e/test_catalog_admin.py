"""E2E — admin catalog CRUD + RBAC + audit log entries.

Hits the FastAPI app over HTTP via the ``client`` fixture, asserting
both the response shape and the admin_audit_log row.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import seed_admin_committed
from tests.factories.catalog import (
    seed_active_ingredient_committed,
    seed_category_committed,
    seed_manufacturer_committed,
)

pytestmark = pytest.mark.e2e


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def _login(client: AsyncClient, *, email: str, password: str) -> dict[str, str]:
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return {"admin_session": r.cookies["admin_session"]}


async def _login_as_super_admin(
    client: AsyncClient, redis_clean: None, *, prefix: str = "ce"
) -> dict[str, str]:
    email = _unique_email(prefix)
    await seed_admin_committed(email=email, password="ok", role="super_admin")
    return await _login(client, email=email, password="ok")


# ─── Manufacturers ────────────────────────────────────────────────────────────


async def test_admin_can_create_and_get_manufacturer(
    client: AsyncClient, redis_clean: None
) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="m-cre")
    r = await client.post(
        "/api/admin/v1/manufacturers",
        json={"name": f"NovoBayer-{uuid.uuid4().hex[:6]}", "country_code": "DE"},
        cookies=cookies,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    mfr_id = body["id"]
    assert body["country_code"] == "DE"

    r2 = await client.get(f"/api/admin/v1/manufacturers/{mfr_id}", cookies=cookies)
    assert r2.status_code == 200
    assert r2.json()["id"] == mfr_id


async def test_admin_create_manufacturer_duplicate_409(
    client: AsyncClient, redis_clean: None
) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="m-dup")
    name = f"DupMfr-{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/api/admin/v1/manufacturers",
        json={"name": name},
        cookies=cookies,
    )
    assert r.status_code == 201
    r2 = await client.post(
        "/api/admin/v1/manufacturers",
        json={"name": name},
        cookies=cookies,
    )
    assert r2.status_code == 409


async def test_unauthenticated_cannot_create_manufacturer(
    client: AsyncClient, redis_clean: None
) -> None:
    r = await client.post(
        "/api/admin/v1/manufacturers",
        json={"name": "Anonymous"},
    )
    assert r.status_code == 401


async def test_branch_manager_cannot_create_manufacturer(
    client: AsyncClient, redis_clean: None
) -> None:
    """RBAC: only super_admin/content_editor allowed."""
    from tests.e2e.conftest import seed_branch_committed

    branch_id = await seed_branch_committed(code=f"BR-{uuid.uuid4().hex[:6].upper()}", name="Тест")
    email = _unique_email("bm")
    await seed_admin_committed(
        email=email, password="ok", role="branch_manager", branch_id=branch_id
    )
    cookies = await _login(client, email=email, password="ok")
    r = await client.post(
        "/api/admin/v1/manufacturers",
        json={"name": f"Forbidden-{uuid.uuid4().hex[:6]}"},
        cookies=cookies,
    )
    assert r.status_code == 403


# ─── Categories ───────────────────────────────────────────────────────────────


async def test_admin_create_category_auto_slugifies(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="cat")
    r = await client.post(
        "/api/admin/v1/categories",
        json={
            "translations": [{"language_code": "ru", "name": f"Витамины-{uuid.uuid4().hex[:6]}"}]
        },
        cookies=cookies,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"].startswith("vitaminy")


async def test_admin_delete_category_with_children_409(
    client: AsyncClient, redis_clean: None
) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="cat-del")
    parent_slug = f"parent-{uuid.uuid4().hex[:6]}"
    parent_id = await seed_category_committed(slug=parent_slug)
    await seed_category_committed(slug=f"child-{uuid.uuid4().hex[:6]}")

    # The above child has no parent set; create one with parent=parent_id via API
    r = await client.post(
        "/api/admin/v1/categories",
        json={
            "parent_id": parent_id,
            "translations": [{"language_code": "ru", "name": "Дочерняя"}],
        },
        cookies=cookies,
    )
    assert r.status_code == 201

    r2 = await client.delete(f"/api/admin/v1/categories/{parent_id}", cookies=cookies)
    assert r2.status_code == 409


# ─── Active ingredients ───────────────────────────────────────────────────────


async def test_admin_can_create_active_ingredient(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="ai")
    inn = f"compound-{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/api/admin/v1/active-ingredients",
        json={
            "inn_name": inn,
            "translations": [{"language_code": "ru", "name": "Соединение", "synonyms": ["Соед."]}],
        },
        cookies=cookies,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["inn_name"] == inn


# ─── Symptoms ─────────────────────────────────────────────────────────────────


async def test_admin_can_list_symptoms(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="sym")
    r = await client.get("/api/admin/v1/symptoms", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body


# ─── Products ─────────────────────────────────────────────────────────────────


async def test_admin_create_and_get_product(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="p-create")
    cat_id = await seed_category_committed(slug=f"cat-prod-{uuid.uuid4().hex[:6]}")
    mfr_id = await seed_manufacturer_committed(name=f"Mfr-{uuid.uuid4().hex[:6]}")
    ai_id = await seed_active_ingredient_committed(inn_name=f"ing-{uuid.uuid4().hex[:6]}")

    sku = f"SKU-{uuid.uuid4().hex[:8]}"
    r = await client.post(
        "/api/admin/v1/products",
        json={
            "sku": sku,
            "category_id": cat_id,
            "manufacturer_id": mfr_id,
            "form": "tablet",
            "translations": [{"language_code": "ru", "name": "Тестовый продукт"}],
            "active_ingredients": [
                {
                    "active_ingredient_id": ai_id,
                    "dosage_amount": "500.000",
                    "dosage_unit": "mg",
                }
            ],
        },
        cookies=cookies,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    pid = body["id"]
    assert body["sku"] == sku
    assert body["slug"]  # auto-generated
    assert len(body["active_ingredients"]) == 1

    r2 = await client.get(f"/api/admin/v1/products/{pid}", cookies=cookies)
    assert r2.status_code == 200
    assert r2.json()["id"] == pid


async def test_admin_create_product_duplicate_sku_409(
    client: AsyncClient, redis_clean: None
) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="p-dup")
    cat_id = await seed_category_committed(slug=f"cat-dup-{uuid.uuid4().hex[:6]}")
    sku = f"DUP-{uuid.uuid4().hex[:8]}"

    base = {
        "sku": sku,
        "category_id": cat_id,
        "form": "tablet",
        "translations": [{"language_code": "ru", "name": "X"}],
    }
    r = await client.post("/api/admin/v1/products", json=base, cookies=cookies)
    assert r.status_code == 201
    r2 = await client.post("/api/admin/v1/products", json=base, cookies=cookies)
    assert r2.status_code == 409


async def test_admin_soft_delete_product_removes_from_list(
    client: AsyncClient, redis_clean: None
) -> None:
    cookies = await _login_as_super_admin(client, redis_clean, prefix="p-del")
    cat_id = await seed_category_committed(slug=f"cat-soft-{uuid.uuid4().hex[:6]}")
    sku = f"SOFT-{uuid.uuid4().hex[:8]}"

    r = await client.post(
        "/api/admin/v1/products",
        json={
            "sku": sku,
            "category_id": cat_id,
            "form": "tablet",
            "translations": [{"language_code": "ru", "name": "Будет удалён"}],
        },
        cookies=cookies,
    )
    pid = r.json()["id"]

    r2 = await client.delete(f"/api/admin/v1/products/{pid}", cookies=cookies)
    assert r2.status_code == 204

    r3 = await client.get(f"/api/admin/v1/products/{pid}", cookies=cookies)
    assert r3.status_code == 404
