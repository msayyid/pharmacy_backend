"""E2E — full OTP request → verify → /me happy path."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import (
    extract_otp_from_messages,
    install_fresh_sms_queue,
)

pytestmark = pytest.mark.e2e


async def test_otp_full_flow_creates_user_and_returns_tokens(
    client: AsyncClient, redis_clean: None
) -> None:
    sms = install_fresh_sms_queue()
    phone = "+996700121401"

    # Request
    r = await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert r.status_code == 202
    body = r.json()
    assert body["sent"] is True
    assert body["expires_in_seconds"] == 300

    # Extract OTP from the fake-queue log
    code = extract_otp_from_messages(sms.sent)
    assert code is not None and code.isdigit()

    # Verify
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": code},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == 900
    access = payload["access_token"]
    refresh = payload["refresh_token"]
    assert access and refresh

    # /me with the access token
    r = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["phone"] == phone
    assert me["preferred_language"] == "ru"  # default; no Accept-Language sent
    assert me["is_phone_verified"] is True


async def test_otp_verify_captures_accept_language(client: AsyncClient, redis_clean: None) -> None:
    sms = install_fresh_sms_queue()
    phone = "+996700121402"

    await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    code = extract_otp_from_messages(sms.sent)
    assert code is not None

    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": code},
        headers={"Accept-Language": "ky-KG,ky;q=0.9,ru;q=0.8"},
    )
    assert r.status_code == 200
    access = r.json()["access_token"]

    r = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.json()["preferred_language"] == "ky"


async def test_me_without_token_is_401(client: AsyncClient, redis_clean: None) -> None:
    r = await client.get("/api/v1/me")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"


async def test_me_with_garbage_token_is_401(client: AsyncClient, redis_clean: None) -> None:
    r = await client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer garbage.token.here"},
    )
    assert r.status_code == 401
