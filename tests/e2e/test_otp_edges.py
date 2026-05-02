"""E2E — OTP edge cases: rate limit, wrong code."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import (
    install_fresh_sms_queue,
)

pytestmark = pytest.mark.e2e


async def test_second_otp_request_within_60s_is_429(client: AsyncClient, redis_clean: None) -> None:
    install_fresh_sms_queue()
    phone = "+996700121501"
    r1 = await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert r1.status_code == 202

    r2 = await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert r2.status_code == 429
    body = r2.json()
    assert body["code"] == "rate_limited"


async def test_wrong_code_returns_401_invalid_otp(client: AsyncClient, redis_clean: None) -> None:
    install_fresh_sms_queue()
    phone = "+996700121502"
    await client.post("/api/v1/auth/otp/request", json={"phone": phone})

    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": phone, "code": "999999"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "invalid_otp"


async def test_invalid_phone_format_is_422(client: AsyncClient, redis_clean: None) -> None:
    r = await client.post("/api/v1/auth/otp/request", json={"phone": "not-a-phone"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"


async def test_verify_without_request_returns_invalid_otp(
    client: AsyncClient, redis_clean: None
) -> None:
    """Verify with no prior request → 401 not_found_or_expired."""
    install_fresh_sms_queue()
    r = await client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": "+996700121503", "code": "000000"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_otp"
