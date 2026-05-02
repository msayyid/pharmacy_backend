"""Identity domain — repositories.

Five repositories, one per aggregate root. Repositories are thin: queries
shaped for intent, no business rules, no commits, no Pydantic. Services
own transactions; tests construct repos with a real ``AsyncSession``.

Reference: BACKEND_BLUEPRINT.md §11.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.core.types import uuid7
from app.domain.identity.models import (
    AdminSession,
    AdminUser,
    OtpCode,
    User,
    UserAddress,
)

# ─── UserRepository ───────────────────────────────────────────────────────────


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        stmt = select(User).where(User.phone == phone, User.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_create_by_phone(
        self, phone: str, *, preferred_language: str
    ) -> tuple[User, bool]:
        """Return (user, created) — auto-creates with phone-verified=True."""
        existing = await self.get_by_phone(phone)
        if existing is not None:
            return (existing, False)
        user = User(
            id=uuid7(),
            phone=phone,
            preferred_language=preferred_language,
            is_phone_verified=True,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return (user, True)

    async def update_last_login(self, user: User) -> None:
        user.last_login_at = utcnow()
        await self.session.flush()


# ─── UserAddressRepository ────────────────────────────────────────────────────


class UserAddressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: UUID) -> Sequence[UserAddress]:
        stmt = (
            select(UserAddress)
            .where(UserAddress.user_id == user_id)
            .order_by(UserAddress.is_default.desc(), UserAddress.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_by_id_for_user(self, address_id: int, user_id: UUID) -> UserAddress | None:
        """Owner-scoped fetch — never returns another user's address."""
        stmt = select(UserAddress).where(
            UserAddress.id == address_id,
            UserAddress.user_id == user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_default_for_user(self, user_id: UUID) -> UserAddress | None:
        stmt = select(UserAddress).where(
            UserAddress.user_id == user_id,
            UserAddress.is_default.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def clear_default_for_user(self, user_id: UUID) -> None:
        """Flip ``is_default=False`` on whichever address is currently default.

        Required before the service sets a NEW address as default — otherwise
        the generated-column UNIQUE constraint blocks the insert.
        """
        stmt = (
            update(UserAddress)
            .where(
                UserAddress.user_id == user_id,
                UserAddress.is_default.is_(True),
            )
            .values(is_default=False)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def add(self, address: UserAddress) -> None:
        self.session.add(address)
        await self.session.flush()
        # Server-defaults (created_at, updated_at) and the generated
        # ``default_user_id`` column aren't returned by INSERT on MySQL —
        # explicitly refresh so AddressRead can serialise them.
        await self.session.refresh(address)

    async def delete(self, address: UserAddress) -> None:
        await self.session.delete(address)
        await self.session.flush()


# ─── OtpRepository ────────────────────────────────────────────────────────────


class OtpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        phone: str,
        code_hash: str,
        purpose: str,
        expires_at: datetime,
        ip_address: str | None,
        max_attempts: int = 5,
    ) -> OtpCode:
        otp = OtpCode(
            phone=phone,
            code_hash=code_hash,
            purpose=purpose,
            expires_at=expires_at,
            ip_address=ip_address,
            max_attempts=max_attempts,
        )
        self.session.add(otp)
        await self.session.flush()
        return otp

    async def get_active_for_phone(self, phone: str, *, purpose: str = "login") -> OtpCode | None:
        """Most recent OTP for phone that is unconsumed AND unexpired."""
        stmt = (
            select(OtpCode)
            .where(
                OtpCode.phone == phone,
                OtpCode.purpose == purpose,
                OtpCode.consumed_at.is_(None),
                OtpCode.expires_at > utcnow(),
            )
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def increment_attempts(self, otp: OtpCode) -> None:
        otp.attempts += 1
        await self.session.flush()

    async def mark_consumed(self, otp: OtpCode) -> None:
        otp.consumed_at = utcnow()
        await self.session.flush()


# ─── AdminUserRepository ──────────────────────────────────────────────────────


class AdminUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, admin_id: int) -> AdminUser | None:
        stmt = select(AdminUser).where(AdminUser.id == admin_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> AdminUser | None:
        stmt = select(AdminUser).where(AdminUser.email == email)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def increment_failed_login(self, admin: AdminUser) -> None:
        admin.failed_login_count += 1
        await self.session.flush()

    async def reset_failed_login(self, admin: AdminUser) -> None:
        admin.failed_login_count = 0
        admin.locked_until = None
        await self.session.flush()

    async def set_locked_until(self, admin: AdminUser, until: datetime) -> None:
        admin.locked_until = until
        await self.session.flush()

    async def set_last_login(self, admin: AdminUser, when: datetime) -> None:
        admin.last_login_at = when
        await self.session.flush()

    async def add(self, admin: AdminUser) -> None:
        self.session.add(admin)
        await self.session.flush()


# ─── AdminSessionRepository ───────────────────────────────────────────────────


class AdminSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        admin_user_id: int,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AdminSession:
        session_row = AdminSession(
            id=uuid7(),
            admin_user_id=admin_user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(session_row)
        await self.session.flush()
        return session_row

    async def get_active_by_token_hash(self, token_hash: str) -> AdminSession | None:
        """Active = not revoked, not expired."""
        stmt = (
            select(AdminSession)
            .where(
                AdminSession.token_hash == token_hash,
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > utcnow(),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def revoke(self, session_row: AdminSession) -> None:
        session_row.revoked_at = utcnow()
        await self.session.flush()

    async def update_last_seen(self, session_row: AdminSession) -> None:
        session_row.last_seen_at = utcnow()
        await self.session.flush()
