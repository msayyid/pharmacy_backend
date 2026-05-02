"""Identity repository integration tests — real DB constraints exercised."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.domain.identity.models import UserAddress
from app.domain.identity.repositories import (
    OtpRepository,
    UserAddressRepository,
    UserRepository,
)

pytestmark = pytest.mark.integration


# ─── Users ────────────────────────────────────────────────────────────────────


async def test_user_phone_uniqueness(session: AsyncSession) -> None:
    """A second user with the same phone fails the UNIQUE constraint."""
    users = UserRepository(session)
    u1, _ = await users.get_or_create_by_phone("+996700000001", preferred_language="ru")
    assert u1.id is not None

    # get_or_create returns existing — so call it again should NOT create
    u2, created = await users.get_or_create_by_phone("+996700000001", preferred_language="ru")
    assert u2.id == u1.id
    assert created is False


async def test_user_get_by_phone_finds_existing(session: AsyncSession) -> None:
    users = UserRepository(session)
    u, _ = await users.get_or_create_by_phone("+996700000002", preferred_language="ky")
    found = await users.get_by_phone("+996700000002")
    assert found is not None
    assert found.id == u.id
    assert found.preferred_language == "ky"


async def test_user_get_by_phone_returns_none_when_absent(session: AsyncSession) -> None:
    users = UserRepository(session)
    found = await users.get_by_phone("+996700000999")
    assert found is None


# ─── Addresses ────────────────────────────────────────────────────────────────


async def test_address_default_uniqueness_enforced(session: AsyncSession) -> None:
    """The generated-column UNIQUE blocks two ``is_default=True`` per user."""
    users = UserRepository(session)
    addresses = UserAddressRepository(session)

    u, _ = await users.get_or_create_by_phone("+996700000003", preferred_language="ru")

    a1 = UserAddress(
        user_id=u.id,
        city="Bishkek",
        address_line="мкр Асанбай 12",
        is_default=True,
    )
    await addresses.add(a1)

    a2 = UserAddress(
        user_id=u.id,
        city="Bishkek",
        address_line="улица Чуй 5",
        is_default=True,
    )
    session.add(a2)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_address_clear_default_then_set_new_works(session: AsyncSession) -> None:
    """Service flow: clear old default, then add new default."""
    users = UserRepository(session)
    addresses = UserAddressRepository(session)

    u, _ = await users.get_or_create_by_phone("+996700000004", preferred_language="ru")

    a1 = UserAddress(
        user_id=u.id,
        city="Bishkek",
        address_line="мкр Асанбай 12",
        is_default=True,
    )
    await addresses.add(a1)

    # Clear, then set new default — works
    await addresses.clear_default_for_user(u.id)
    a2 = UserAddress(
        user_id=u.id,
        city="Bishkek",
        address_line="улица Чуй 5",
        is_default=True,
    )
    await addresses.add(a2)

    found = await addresses.get_default_for_user(u.id)
    assert found is not None
    assert found.id == a2.id
    assert found.is_default is True


async def test_address_owner_scoped_lookup(session: AsyncSession) -> None:
    """get_by_id_for_user only returns addresses owned by that user."""
    users = UserRepository(session)
    addresses = UserAddressRepository(session)

    u1, _ = await users.get_or_create_by_phone("+996700000005", preferred_language="ru")
    u2, _ = await users.get_or_create_by_phone("+996700000006", preferred_language="ru")

    a = UserAddress(
        user_id=u1.id,
        city="Bishkek",
        address_line="addr",
        is_default=False,
    )
    await addresses.add(a)

    # u1 finds it; u2 does not
    assert await addresses.get_by_id_for_user(a.id, u1.id) is not None
    assert await addresses.get_by_id_for_user(a.id, u2.id) is None


# ─── OTP ──────────────────────────────────────────────────────────────────────


async def test_otp_create_and_get_active(session: AsyncSession) -> None:
    repo = OtpRepository(session)
    expires = utcnow() + timedelta(minutes=5)
    otp = await repo.create(
        phone="+996700000010",
        code_hash="hashed-code",
        purpose="login",
        expires_at=expires,
        ip_address="127.0.0.1",
    )
    assert otp.id is not None

    found = await repo.get_active_for_phone("+996700000010")
    assert found is not None
    assert found.id == otp.id


async def test_otp_consumed_excluded_from_active(session: AsyncSession) -> None:
    repo = OtpRepository(session)
    expires = utcnow() + timedelta(minutes=5)
    otp = await repo.create(
        phone="+996700000011",
        code_hash="x",
        purpose="login",
        expires_at=expires,
        ip_address=None,
    )
    await repo.mark_consumed(otp)

    found = await repo.get_active_for_phone("+996700000011")
    assert found is None


async def test_otp_expired_excluded_from_active(session: AsyncSession) -> None:
    repo = OtpRepository(session)
    # Already-expired OTP
    past = utcnow() - timedelta(minutes=1)
    await repo.create(
        phone="+996700000012",
        code_hash="x",
        purpose="login",
        expires_at=past,
        ip_address=None,
    )
    found = await repo.get_active_for_phone("+996700000012")
    assert found is None


async def test_otp_get_active_returns_most_recent(session: AsyncSession) -> None:
    """If multiple unconsumed OTPs exist, the newest is returned."""
    repo = OtpRepository(session)
    phone = "+996700000013"
    expires = utcnow() + timedelta(minutes=5)
    await repo.create(
        phone=phone,
        code_hash="older",
        purpose="login",
        expires_at=expires,
        ip_address=None,
    )
    newer = await repo.create(
        phone=phone,
        code_hash="newer",
        purpose="login",
        expires_at=expires,
        ip_address=None,
    )
    found = await repo.get_active_for_phone(phone)
    assert found is not None
    assert found.id == newer.id


async def test_otp_increment_attempts(session: AsyncSession) -> None:
    repo = OtpRepository(session)
    expires = utcnow() + timedelta(minutes=5)
    otp = await repo.create(
        phone="+996700000014",
        code_hash="x",
        purpose="login",
        expires_at=expires,
        ip_address=None,
    )
    assert otp.attempts == 0
    await repo.increment_attempts(otp)
    await repo.increment_attempts(otp)
    assert otp.attempts == 2
