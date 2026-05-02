"""AdminAuthService — login, wrong password counter, lockout, logout."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import hash_password
from app.domain.identity.models import AdminUser
from app.domain.identity.repositories import (
    AdminSessionRepository,
    AdminUserRepository,
)
from app.domain.identity.services import AdminAuthService

pytestmark = pytest.mark.integration


async def _seed_admin(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    role: str = "super_admin",
    branch_id: int | None = None,
) -> AdminUser:
    pepper = get_settings().password_pepper.get_secret_value()
    admin = AdminUser(
        email=email,
        password_hash=hash_password(password, pepper),
        first_name="Test",
        last_name="Admin",
        role=role,
        branch_id=branch_id,
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin


def _admin_auth(session: AsyncSession) -> AdminAuthService:
    return AdminAuthService(
        settings=get_settings(),
        admins=AdminUserRepository(session),
        sessions=AdminSessionRepository(session),
    )


async def test_admin_login_success_returns_token(session: AsyncSession) -> None:
    await _seed_admin(session, email="aibek@pharmacy.kg", password="hunter2-correct")
    svc = _admin_auth(session)
    admin, token = await svc.login_with_password(
        email="aibek@pharmacy.kg",
        password="hunter2-correct",
        ip_address="127.0.0.1",
        user_agent="curl/8",
    )
    assert admin.email == "aibek@pharmacy.kg"
    assert admin.failed_login_count == 0
    assert admin.last_login_at is not None
    assert token  # opaque, ~43 chars urlsafe


async def test_admin_login_wrong_password_increments_counter(
    session: AsyncSession,
) -> None:
    seeded = await _seed_admin(session, email="aida@pharmacy.kg", password="correct-pass")
    svc = _admin_auth(session)

    for expected_count in (1, 2, 3, 4):
        with pytest.raises(AuthenticationError):
            await svc.login_with_password(
                email="aida@pharmacy.kg",
                password="wrong-pass",
            )
        await session.refresh(seeded)
        assert seeded.failed_login_count == expected_count
        assert seeded.locked_until is None


async def test_admin_lockout_at_fifth_failure(session: AsyncSession) -> None:
    seeded = await _seed_admin(session, email="nurzat@pharmacy.kg", password="correct-pass")
    svc = _admin_auth(session)

    for _ in range(5):
        with pytest.raises(AuthenticationError):
            await svc.login_with_password(
                email="nurzat@pharmacy.kg",
                password="wrong-pass",
            )

    await session.refresh(seeded)
    assert seeded.failed_login_count == 5
    assert seeded.locked_until is not None

    # 6th attempt — even with the RIGHT password — is locked out
    with pytest.raises(PermissionDeniedError) as excinfo:
        await svc.login_with_password(
            email="nurzat@pharmacy.kg",
            password="correct-pass",
        )
    assert excinfo.value.context.get("code") == "account_locked"


async def test_admin_login_resets_counter_on_success(session: AsyncSession) -> None:
    seeded = await _seed_admin(session, email="marat@pharmacy.kg", password="correct-pass")
    svc = _admin_auth(session)

    # Two failed attempts
    for _ in range(2):
        with pytest.raises(AuthenticationError):
            await svc.login_with_password(email="marat@pharmacy.kg", password="wrong")
    await session.refresh(seeded)
    assert seeded.failed_login_count == 2

    # Then a success — counter resets
    await svc.login_with_password(email="marat@pharmacy.kg", password="correct-pass")
    await session.refresh(seeded)
    assert seeded.failed_login_count == 0


async def test_admin_login_inactive_rejected(session: AsyncSession) -> None:
    admin = await _seed_admin(session, email="suspended@pharmacy.kg", password="x")
    admin.is_active = False
    await session.flush()
    svc = _admin_auth(session)
    with pytest.raises(AuthenticationError):
        await svc.login_with_password(email="suspended@pharmacy.kg", password="x")


async def test_admin_get_by_token_round_trip(session: AsyncSession) -> None:
    """Login produces a token; ``get_admin_by_token`` resolves it."""
    seeded = await _seed_admin(session, email="resolve@pharmacy.kg", password="ok")
    svc = _admin_auth(session)
    _, token = await svc.login_with_password(email="resolve@pharmacy.kg", password="ok")
    found = await svc.get_admin_by_token(token)
    assert found is not None
    assert found.id == seeded.id


async def test_admin_logout_revokes(session: AsyncSession) -> None:
    await _seed_admin(session, email="logout@pharmacy.kg", password="ok")
    svc = _admin_auth(session)
    _, token = await svc.login_with_password(email="logout@pharmacy.kg", password="ok")
    assert await svc.get_admin_by_token(token) is not None

    await svc.logout(token)
    assert await svc.get_admin_by_token(token) is None
