"""E2E — refresh rotation + logout invalidates refresh."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import (
    extract_otp_from_messages,
    install_fresh_sms_queue,
)

pytestmark = pytest.mark.e2e


async def _login(client: AsyncClient, phone: str) -> tuple[str, str]:
    """Helper: full OTP flow → returns (access, refresh)."""
    sms = install_fresh_sms_queue()
    await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    code = extract_otp_from_messages(sms.sent)
    assert code is not None
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": code},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return (body["access_token"], body["refresh_token"])


async def test_refresh_rotates_and_old_token_rejected(
    client: AsyncClient, redis_clean: None
) -> None:
    _, refresh = await _login(client, "+996700121601")

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    new_pair = r.json()
    assert new_pair["refresh_token"] != refresh

    # Old refresh now revoked
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401
    assert r2.json()["code"] == "unauthorized"


async def test_logout_revokes_refresh_token(client: AsyncClient, redis_clean: None) -> None:
    _, refresh = await _login(client, "+996700121602")

    r = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert r.status_code == 204

    # After logout, refresh fails
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


async def test_logout_with_garbage_token_is_idempotent(
    client: AsyncClient, redis_clean: None
) -> None:
    """Logout never errors — even with a malformed refresh token."""
    r = await client.post("/api/v1/auth/logout", json={"refresh_token": "garbage"})
    assert r.status_code == 204
