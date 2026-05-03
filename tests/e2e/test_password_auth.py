"""E2E — local-dev password auth.

Walks the new ``POST /auth/register`` + ``POST /auth/login`` flow and
verifies the returned access token works against ``GET /me``.
"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


def _email() -> str:
    return f"pwd-{secrets.token_hex(6)}@example.com"


def _phone() -> str:
    return f"+99670{secrets.randbelow(10**6):07d}"


async def test_register_returns_user_id_and_token_pair(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    payload = {
        "email": _email(),
        "password": "hunter22-strong",
        "phone": _phone(),
        "first_name": "Тест",
        "last_name": "Пользователь",
    }
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user_id"]
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_register_then_login_then_me(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    email = _email()
    password = "another-strong-pwd"
    phone = _phone()

    r1 = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "phone": phone},
    )
    assert r1.status_code == 201, r1.text

    # Login with the same credentials.
    r2 = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert r2.status_code == 200, r2.text
    access = r2.json()["access_token"]

    # Hit the authenticated /me endpoint.
    r3 = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r3.status_code == 200, r3.text
    me = r3.json()
    assert me["email"] == email.lower()
    assert me["phone"] == phone


async def test_register_rejects_duplicate_email(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    email = _email()
    password = "first-pwd"
    r1 = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "phone": _phone()},
    )
    assert r1.status_code == 201

    # Same email, different phone.
    r2 = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "second-pwd", "phone": _phone()},
    )
    assert r2.status_code == 400
    # ValidationError surfaces with generic "validation_error" code; the
    # specific reason lives in the response detail.
    assert r2.json()["code"] == "validation_error"


async def test_login_wrong_password_returns_401_generic(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    email = _email()
    r1 = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "phone": _phone()},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-pwd"},
    )
    assert r2.status_code == 401
    # Generic code — same as unknown-email (no user enumeration).
    # AuthenticationError surfaces with generic "unauthorized" code; the
    # detail field carries the specific ``invalid_credentials`` reason.
    assert r2.json()["code"] == "unauthorized"


async def test_login_unknown_email_returns_401_generic(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": _email(), "password": "anything"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"
