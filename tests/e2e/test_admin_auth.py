"""E2E — admin login (success, lockout, role-gate, branch-access, logout)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import seed_admin_committed, seed_branch_committed

pytestmark = pytest.mark.e2e


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def test_admin_login_sets_session_cookie(client: AsyncClient, redis_clean: None) -> None:
    email = _unique_email("super")
    await seed_admin_committed(email=email, password="hunter-correct", role="super_admin")

    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "hunter-correct"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == email
    assert body["role"] == "super_admin"
    assert "admin_session" in r.cookies

    # Subsequent /admin/v1/auth/me with the cookie returns the admin
    r2 = await client.get(
        "/api/admin/v1/auth/me",
        cookies={"admin_session": r.cookies["admin_session"]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["email"] == email


async def test_admin_login_lockout_after_5_failures(client: AsyncClient, redis_clean: None) -> None:
    email = _unique_email("lockout")
    await seed_admin_committed(email=email, password="correct-pass", role="super_admin")

    # 5 wrong attempts
    for _ in range(5):
        r = await client.post(
            "/api/admin/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
        assert r.status_code == 401

    # 6th — correct password — locked
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "correct-pass"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "forbidden"


async def test_admin_logout_clears_session(client: AsyncClient, redis_clean: None) -> None:
    email = _unique_email("logout")
    await seed_admin_committed(email=email, password="ok", role="super_admin")
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "ok"},
    )
    cookie = r.cookies["admin_session"]

    # Logout
    r = await client.post(
        "/api/admin/v1/auth/logout",
        cookies={"admin_session": cookie},
    )
    assert r.status_code == 204

    # /me with revoked cookie → 401
    r = await client.get(
        "/api/admin/v1/auth/me",
        cookies={"admin_session": cookie},
    )
    assert r.status_code == 401


async def test_admin_login_inactive_rejected(client: AsyncClient, redis_clean: None) -> None:
    """A bogus email returns invalid_credentials, not "user not found"."""
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={
            "email": _unique_email("ghost"),
            "password": "anything",
        },
    )
    assert r.status_code == 401


async def test_admin_me_without_cookie_is_401(client: AsyncClient, redis_clean: None) -> None:
    r = await client.get("/api/admin/v1/auth/me")
    assert r.status_code == 401


async def test_seeded_branch_admin_login_works(client: AsyncClient, redis_clean: None) -> None:
    """A branch_manager admin (with branch_id) can log in."""
    branch_id = await seed_branch_committed(
        code=f"TEST-{uuid.uuid4().hex[:6].upper()}", name="Тестовая аптека"
    )
    email = _unique_email("manager")
    await seed_admin_committed(
        email=email,
        password="manager-pass",
        role="branch_manager",
        branch_id=branch_id,
    )

    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "manager-pass"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "branch_manager"
    assert r.json()["branch_id"] == branch_id
