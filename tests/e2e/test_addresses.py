"""E2E — addresses CRUD + default-toggle behaviour."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import (
    extract_otp_from_messages,
    install_fresh_sms_queue,
)

pytestmark = pytest.mark.e2e


async def _login(client: AsyncClient, phone: str) -> str:
    sms = install_fresh_sms_queue()
    await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    code = extract_otp_from_messages(sms.sent)
    assert code is not None
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": code},
    )
    assert r.status_code == 200
    return str(r.json()["access_token"])


async def test_full_address_lifecycle(client: AsyncClient, redis_clean: None) -> None:
    access = await _login(client, "+996700121701")
    auth = {"Authorization": f"Bearer {access}"}

    # Initially empty
    r = await client.get("/api/v1/me/addresses", headers=auth)
    assert r.status_code == 200
    assert r.json() == []

    # Create
    r = await client.post(
        "/api/v1/me/addresses",
        headers=auth,
        json={
            "label": "Home",
            "recipient_name": "Айжана",
            "recipient_phone": "+996700121701",
            "city": "Bishkek",
            "address_line": "мкр Асанбай, дом 12, кв 45",
            "landmark": "напротив школы №42",
            "is_default": True,
        },
    )
    assert r.status_code == 201, r.text
    addr = r.json()
    assert addr["is_default"] is True
    addr_id = addr["id"]

    # List
    r = await client.get("/api/v1/me/addresses", headers=auth)
    assert r.status_code == 200
    listing = r.json()
    assert len(listing) == 1
    assert listing[0]["id"] == addr_id

    # Update label
    r = await client.patch(
        f"/api/v1/me/addresses/{addr_id}",
        headers=auth,
        json={"label": "Дом"},
    )
    assert r.status_code == 200
    assert r.json()["label"] == "Дом"

    # Delete
    r = await client.delete(f"/api/v1/me/addresses/{addr_id}", headers=auth)
    assert r.status_code == 204

    r = await client.get("/api/v1/me/addresses", headers=auth)
    assert r.json() == []


async def test_default_toggle_clears_prior_default(client: AsyncClient, redis_clean: None) -> None:
    """Setting a new address as default un-defaults the old one."""
    access = await _login(client, "+996700121702")
    auth = {"Authorization": f"Bearer {access}"}

    # Create first address as default
    r1 = await client.post(
        "/api/v1/me/addresses",
        headers=auth,
        json={
            "address_line": "мкр Асанбай 12",
            "is_default": True,
        },
    )
    a1 = r1.json()
    assert a1["is_default"] is True

    # Create second address — also default → first should flip to non-default
    r2 = await client.post(
        "/api/v1/me/addresses",
        headers=auth,
        json={
            "address_line": "улица Чуй 5",
            "is_default": True,
        },
    )
    assert r2.status_code == 201, r2.text
    a2 = r2.json()
    assert a2["is_default"] is True

    # Verify: only one is default now (a2)
    r = await client.get("/api/v1/me/addresses", headers=auth)
    listing = r.json()
    defaults = [x for x in listing if x["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == a2["id"]


async def test_address_update_404_for_other_users_address(
    client: AsyncClient, redis_clean: None
) -> None:
    """A user cannot read or modify another user's address."""
    access1 = await _login(client, "+996700121703")
    access2 = await _login(client, "+996700121704")

    # User 1 creates an address
    r = await client.post(
        "/api/v1/me/addresses",
        headers={"Authorization": f"Bearer {access1}"},
        json={"address_line": "private addr"},
    )
    assert r.status_code == 201
    addr_id = r.json()["id"]

    # User 2 tries to update it — 404 (owner-scoped)
    r = await client.patch(
        f"/api/v1/me/addresses/{addr_id}",
        headers={"Authorization": f"Bearer {access2}"},
        json={"label": "stolen"},
    )
    assert r.status_code == 404


async def test_create_address_requires_auth(client: AsyncClient, redis_clean: None) -> None:
    r = await client.post(
        "/api/v1/me/addresses",
        json={"address_line": "test"},
    )
    assert r.status_code == 401
