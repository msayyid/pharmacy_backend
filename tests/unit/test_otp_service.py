"""OtpService — request_code + verify_and_issue_tokens behaviour.

Uses real DB + Redis (per the project's Phase 2/3 conftest fixtures); fake
SMS queue captures messages in memory. The "unit" classification follows
the Phase 4 spec — these tests exercise service orchestration with the
real persistence stack.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import InvalidOTPError, RateLimitExceededError
from app.core.security import TokenIssuer, hash_otp
from app.core.time import utcnow
from app.domain.identity.repositories import OtpRepository, UserRepository
from app.domain.identity.services import OtpService
from app.integrations.sms.fake import FakeSmsQueue

pytestmark = pytest.mark.integration


def _make_service(session: AsyncSession) -> tuple[OtpService, FakeSmsQueue]:
    settings = get_settings()
    sms = FakeSmsQueue()
    service = OtpService(
        settings=settings,
        users=UserRepository(session),
        otps=OtpRepository(session),
        sms_queue=sms,
        token_issuer=TokenIssuer(settings),
    )
    return (service, sms)


# ─── request_code ─────────────────────────────────────────────────────────────


async def test_request_code_success_enqueues_sms(session: AsyncSession, redis_clean: None) -> None:
    service, sms = _make_service(session)
    ttl = await service.request_code(phone="+996700111101", ip_address="127.0.0.1")
    assert ttl == get_settings().otp_ttl_seconds
    assert len(sms.sent) == 1
    msg = sms.sent[0]
    assert msg.phone == "+996700111101"
    assert msg.purpose == "otp"
    # OTP code is interpolated into the body
    assert any(c.isdigit() for c in msg.body)


async def test_request_code_rate_limited_phone_burst(
    session: AsyncSession, redis_clean: None
) -> None:
    """Second request within 60s for the same phone is blocked."""
    service, _ = _make_service(session)
    await service.request_code(phone="+996700111102", ip_address="1.1.1.1")
    with pytest.raises(RateLimitExceededError):
        await service.request_code(phone="+996700111102", ip_address="1.1.1.2")


async def test_request_code_rate_limited_ip_after_10(
    session: AsyncSession, redis_clean: None
) -> None:
    """11th request from the same IP (different phones) is blocked."""
    service, _ = _make_service(session)
    # 10 different phones, each with the burst counter independent
    for i in range(10):
        await service.request_code(
            phone=f"+99670011110{i % 10}",
            ip_address="2.2.2.2",
        )
    # 11th hit on the SAME IP — different phone — should trip the IP limit
    with pytest.raises(RateLimitExceededError):
        await service.request_code(
            phone="+996700110200",
            ip_address="2.2.2.2",
        )


# ─── verify_and_issue_tokens ──────────────────────────────────────────────────


async def test_verify_success_issues_pair_and_creates_user(
    session: AsyncSession, redis_clean: None
) -> None:
    service, sms = _make_service(session)
    settings = get_settings()
    phone = "+996700111201"

    # Manually seed an OTP (bypassing the rate limiter for this test)
    code = "123456"
    await OtpRepository(session).create(
        phone=phone,
        code_hash=hash_otp(code, settings.password_pepper.get_secret_value()),
        purpose="login",
        expires_at=utcnow() + timedelta(minutes=5),
        ip_address=None,
    )
    # Verify
    pair, user = await service.verify_and_issue_tokens(phone=phone, code=code, accept_language="ky")
    assert pair.access
    assert pair.refresh
    assert user.phone == phone
    assert user.is_phone_verified is True
    # preferred_language captured from header
    assert user.preferred_language == "ky"


async def test_verify_wrong_code_increments_attempts(
    session: AsyncSession, redis_clean: None
) -> None:
    service, _ = _make_service(session)
    settings = get_settings()
    phone = "+996700111202"
    code = "123456"
    otp = await OtpRepository(session).create(
        phone=phone,
        code_hash=hash_otp(code, settings.password_pepper.get_secret_value()),
        purpose="login",
        expires_at=utcnow() + timedelta(minutes=5),
        ip_address=None,
    )

    with pytest.raises(InvalidOTPError):
        await service.verify_and_issue_tokens(phone=phone, code="999999", accept_language=None)

    await session.refresh(otp)
    assert otp.attempts == 1


async def test_verify_max_attempts_rejects(session: AsyncSession, redis_clean: None) -> None:
    service, _ = _make_service(session)
    settings = get_settings()
    phone = "+996700111203"
    otp = await OtpRepository(session).create(
        phone=phone,
        code_hash=hash_otp("123456", settings.password_pepper.get_secret_value()),
        purpose="login",
        expires_at=utcnow() + timedelta(minutes=5),
        ip_address=None,
    )
    otp.attempts = 5  # at max
    await session.flush()

    with pytest.raises(InvalidOTPError) as excinfo:
        await service.verify_and_issue_tokens(phone=phone, code="123456", accept_language=None)
    assert excinfo.value.context.get("code") == "too_many_attempts"


async def test_verify_expired_rejected(session: AsyncSession, redis_clean: None) -> None:
    service, _ = _make_service(session)
    settings = get_settings()
    phone = "+996700111204"
    await OtpRepository(session).create(
        phone=phone,
        code_hash=hash_otp("123456", settings.password_pepper.get_secret_value()),
        purpose="login",
        expires_at=utcnow() - timedelta(minutes=1),  # already expired
        ip_address=None,
    )
    with pytest.raises(InvalidOTPError) as excinfo:
        await service.verify_and_issue_tokens(phone=phone, code="123456", accept_language=None)
    assert excinfo.value.context.get("code") == "not_found_or_expired"


async def test_verify_consumed_only_once(session: AsyncSession, redis_clean: None) -> None:
    """A consumed OTP cannot be re-used."""
    service, _ = _make_service(session)
    settings = get_settings()
    phone = "+996700111205"
    code = "123456"
    await OtpRepository(session).create(
        phone=phone,
        code_hash=hash_otp(code, settings.password_pepper.get_secret_value()),
        purpose="login",
        expires_at=utcnow() + timedelta(minutes=5),
        ip_address=None,
    )

    # First verify succeeds
    pair, _ = await service.verify_and_issue_tokens(phone=phone, code=code, accept_language=None)
    assert pair.access

    # Second verify fails — OTP marked consumed
    with pytest.raises(InvalidOTPError):
        await service.verify_and_issue_tokens(phone=phone, code=code, accept_language=None)
