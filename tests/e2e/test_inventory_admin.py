"""E2E — admin inventory: receive, adjust, RBAC, reports."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import seed_admin_committed, seed_branch_committed
from tests.factories.catalog import (
    seed_category_committed,
    seed_product_committed,
)
from tests.factories.inventory import (
    seed_branch_product_committed,
    seed_inventory_batch_committed,
)

pytestmark = pytest.mark.e2e


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def _login(client: AsyncClient, *, email: str, password: str) -> dict[str, str]:
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return {"admin_session": r.cookies["admin_session"]}


async def _login_super_admin(client: AsyncClient, *, prefix: str = "sa") -> dict[str, str]:
    email = _email(prefix)
    await seed_admin_committed(email=email, password="ok", role="super_admin")
    return await _login(client, email=email, password="ok")


async def _seed_branch_and_product() -> tuple[int, str]:
    """Returns (branch_id, product_id_str)."""
    branch_id = await seed_branch_committed(code=f"BR-{uuid.uuid4().hex[:6].upper()}")
    cat_id = await seed_category_committed(slug=f"cat-{uuid.uuid4().hex[:6]}")
    pid = await seed_product_committed(
        sku=f"INV-E2E-{uuid.uuid4().hex[:8]}",
        slug=f"inv-e2e-{uuid.uuid4().hex[:6]}",
        category_id=cat_id,
    )
    return (branch_id, str(pid))


# ─── Receive ─────────────────────────────────────────────────────────────────


async def test_pharmacist_can_receive_batch(client: AsyncClient, redis_clean: None) -> None:
    branch_id, product_id = await _seed_branch_and_product()
    email = _email("pharm")
    await seed_admin_committed(email=email, password="ok", role="pharmacist", branch_id=branch_id)
    cookies = await _login(client, email=email, password="ok")

    body = {
        "product_id": product_id,
        "batch_number": "LOT-001",
        "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
        "quantity_received": 100,
        "cost_price": "50.00",
    }
    r = await client.post(
        f"/api/admin/v1/branches/{branch_id}/inventory/batches",
        json=body,
        cookies=cookies,
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["batch"]["quantity_remaining"] == 100
    assert payload["branch_product_pending_pricing"] is True

    # Stock visible via GET inventory list
    r2 = await client.get(f"/api/admin/v1/branches/{branch_id}/inventory", cookies=cookies)
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert any(item["total_quantity"] == 100 for item in items)


async def test_receive_within_hard_block_400(client: AsyncClient, redis_clean: None) -> None:
    branch_id, product_id = await _seed_branch_and_product()
    cookies = await _login_super_admin(client, prefix="hb")

    body = {
        "product_id": product_id,
        "batch_number": "LOT-HB",
        "expiry_date": (date.today() + timedelta(days=3)).isoformat(),
        "quantity_received": 50,
        "cost_price": "10.00",
    }
    r = await client.post(
        f"/api/admin/v1/branches/{branch_id}/inventory/batches",
        json=body,
        cookies=cookies,
    )
    assert r.status_code == 400


# ─── Adjust ──────────────────────────────────────────────────────────────────


async def test_pharmacist_can_adjust_own_batch(client: AsyncClient, redis_clean: None) -> None:
    from uuid import UUID

    branch_id, product_id = await _seed_branch_and_product()
    await seed_branch_product_committed(
        branch_id=branch_id, product_id=UUID(product_id), total_quantity=50
    )
    batch_id = await seed_inventory_batch_committed(
        branch_id=branch_id,
        product_id=UUID(product_id),
        batch_number="LOT-ADJ",
        quantity_received=50,
    )

    email = _email("pharm-adj")
    await seed_admin_committed(email=email, password="ok", role="pharmacist", branch_id=branch_id)
    cookies = await _login(client, email=email, password="ok")

    r = await client.patch(
        f"/api/admin/v1/inventory/batches/{batch_id}",
        json={
            "quantity_change": -3,
            "movement_type": "damaged",
            "reason": "knocked over",
        },
        cookies=cookies,
    )
    assert r.status_code == 200, r.text
    assert r.json()["quantity_remaining"] == 47


# ─── RBAC ────────────────────────────────────────────────────────────────────


async def test_content_editor_forbidden(client: AsyncClient, redis_clean: None) -> None:
    branch_id, product_id = await _seed_branch_and_product()
    email = _email("ce")
    await seed_admin_committed(
        email=email, password="ok", role="content_editor", branch_id=branch_id
    )
    cookies = await _login(client, email=email, password="ok")

    r = await client.post(
        f"/api/admin/v1/branches/{branch_id}/inventory/batches",
        json={
            "product_id": product_id,
            "batch_number": "LOT-CE",
            "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
            "quantity_received": 10,
            "cost_price": "10",
        },
        cookies=cookies,
    )
    assert r.status_code == 403


async def test_branch_manager_other_branch_forbidden(
    client: AsyncClient, redis_clean: None
) -> None:
    branch_a = await seed_branch_committed(code=f"BA-{uuid.uuid4().hex[:6].upper()}")
    branch_b = await seed_branch_committed(code=f"BB-{uuid.uuid4().hex[:6].upper()}")
    cat_id = await seed_category_committed(slug=f"cat-{uuid.uuid4().hex[:6]}")
    pid = await seed_product_committed(
        sku=f"X-{uuid.uuid4().hex[:6]}",
        slug=f"x-{uuid.uuid4().hex[:6]}",
        category_id=cat_id,
    )

    email = _email("bm-a")
    await seed_admin_committed(
        email=email, password="ok", role="branch_manager", branch_id=branch_a
    )
    cookies = await _login(client, email=email, password="ok")

    # Try to receive into branch_b — forbidden.
    r = await client.post(
        f"/api/admin/v1/branches/{branch_b}/inventory/batches",
        json={
            "product_id": str(pid),
            "batch_number": "LOT-X",
            "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
            "quantity_received": 5,
            "cost_price": "5",
        },
        cookies=cookies,
    )
    assert r.status_code == 403


# ─── Reports ─────────────────────────────────────────────────────────────────


async def test_low_stock_report_returns_rows(client: AsyncClient, redis_clean: None) -> None:
    from uuid import UUID

    branch_id, product_id = await _seed_branch_and_product()
    await seed_branch_product_committed(
        branch_id=branch_id,
        product_id=UUID(product_id),
        total_quantity=2,
        low_stock_threshold=10,
    )
    cookies = await _login_super_admin(client, prefix="rpt-low")

    r = await client.get(
        f"/api/admin/v1/branches/{branch_id}/reports/low-stock",
        cookies=cookies,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(row["product_id"] == product_id for row in rows)


async def test_near_expiry_report_csv_format(client: AsyncClient, redis_clean: None) -> None:
    from uuid import UUID

    branch_id, product_id = await _seed_branch_and_product()
    await seed_branch_product_committed(
        branch_id=branch_id, product_id=UUID(product_id), total_quantity=10
    )
    await seed_inventory_batch_committed(
        branch_id=branch_id,
        product_id=UUID(product_id),
        batch_number="LOT-NEAR",
        expiry_date=date.today() + timedelta(days=20),
        quantity_received=10,
    )
    cookies = await _login_super_admin(client, prefix="rpt-near")

    r = await client.get(
        f"/api/admin/v1/branches/{branch_id}/reports/near-expiry?days=30&format=csv",
        cookies=cookies,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.text
    assert "batch_id" in body  # header row
    assert "LOT-NEAR" in body
