"""AuthService — refresh rotation + logout."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.security import CUSTOMER_KIND, TokenIssuer, hash_otp
from app.core.time import utcnow
from app.domain.identity.repositories import OtpRepository, UserRepository
from app.domain.identity.services import AuthService, OtpService
from app.integrations.sms.fake import FakeSmsQueue

pytestmark = pytest.mark.integration


async def _seed_user_with_tokens(session: AsyncSession, phone: str) -> tuple[str, str, str]:
    """Helper: create a user, return (user_id, access, refresh)."""
    settings = get_settings()
    code = "123456"
    await OtpRepository(session).create(
        phone=phone,
        code_hash=hash_otp(code, settings.password_pepper.get_secret_value()),
        purpose="login",
        expires_at=utcnow() + timedelta(minutes=5),
        ip_address=None,
    )
    otp_svc = OtpService(
        settings=settings,
        users=UserRepository(session),
        otps=OtpRepository(session),
        sms_queue=FakeSmsQueue(),
        token_issuer=TokenIssuer(settings),
    )
    pair, user = await otp_svc.verify_and_issue_tokens(phone=phone, code=code, accept_language=None)
    return (str(user.id), pair.access, pair.refresh)


def _auth_service(session: AsyncSession) -> AuthService:
    settings = get_settings()
    return AuthService(
        settings=settings,
        users=UserRepository(session),
        token_issuer=TokenIssuer(settings),
    )


async def test_refresh_rotates_jti(session: AsyncSession, redis_clean: None) -> None:
    user_id, _, refresh = await _seed_user_with_tokens(session, "+996700121301")
    auth = _auth_service(session)

    new_pair = await auth.refresh(refresh)
    assert new_pair.access != ""
    assert new_pair.refresh != refresh

    # Old refresh now rejected
    with pytest.raises(AuthenticationError) as excinfo:
        await auth.refresh(refresh)
    assert excinfo.value.context.get("code") == "refresh_revoked"


async def test_refresh_with_unknown_jti_rejected(session: AsyncSession, redis_clean: None) -> None:
    """A valid-looking JWT with a jti not in Redis is rejected."""
    settings = get_settings()
    issuer = TokenIssuer(settings)
    # Issue tokens but DON'T register the jti in Redis
    pair = issuer.issue_pair(
        subject="01999999-1111-7000-8000-000000000000",
        kind=CUSTOMER_KIND,
    )
    auth = _auth_service(session)

    with pytest.raises(AuthenticationError) as excinfo:
        await auth.refresh(pair.refresh)
    assert excinfo.value.context.get("code") == "refresh_revoked"


async def test_refresh_with_expired_token_rejected(
    session: AsyncSession, redis_clean: None
) -> None:
    """An expired refresh JWT is rejected (decode failure)."""
    auth = _auth_service(session)
    settings = get_settings()
    issuer = TokenIssuer(settings)

    with freeze_time("2026-01-01 12:00:00"):
        pair = issuer.issue_pair(
            subject="01999999-1111-7000-8000-000000000001",
            kind=CUSTOMER_KIND,
        )
    # 31 days later — refresh TTL is 30 days
    with freeze_time("2026-02-01 13:00:00"):
        with pytest.raises(AuthenticationError) as excinfo:
            await auth.refresh(pair.refresh)
        assert excinfo.value.context.get("code") == "invalid_refresh"


async def test_logout_revokes_refresh(session: AsyncSession, redis_clean: None) -> None:
    user_id, _, refresh = await _seed_user_with_tokens(session, "+996700121302")
    auth = _auth_service(session)

    await auth.logout(refresh)

    with pytest.raises(AuthenticationError):
        await auth.refresh(refresh)


async def test_logout_idempotent_with_invalid_token(
    session: AsyncSession, redis_clean: None
) -> None:
    """Logout with garbage token is a no-op (no exception)."""
    auth = _auth_service(session)
    await auth.logout("not-a-real-jwt")
    await auth.logout("")
