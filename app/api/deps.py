"""FastAPI dependencies (DI graph).

* Type aliases: ``SettingsDep``, ``LangDep``, ``RedisDep``, ``DbSession``.
* Repository factories: ``get_*_repository`` per aggregate.
* Service factories: ``get_otp_service``, ``get_auth_service``,
  ``get_account_service``, ``get_admin_auth_service``.
* Customer / admin auth deps live in
  :mod:`app.domain.identity.dependencies` to keep the domain self-contained.

Reference: BACKEND_BLUEPRINT.md §13.2.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.i18n import resolve_language
from app.core.redis import get_redis
from app.core.security import TokenIssuer
from app.domain.identity.repositories import (
    AdminSessionRepository,
    AdminUserRepository,
    OtpRepository,
    UserAddressRepository,
    UserRepository,
)
from app.domain.identity.services import (
    AccountService,
    AdminAuthService,
    AuthService,
    OtpService,
)
from app.domain.inventory.repositories import BranchRepository
from app.integrations.sms.base import get_sms_queue

# ─── Type aliases ─────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_lang(
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve the request language from ``Accept-Language``."""
    return resolve_language(accept_language)


LangDep = Annotated[str, Depends(get_lang)]


def get_redis_dep() -> Redis:
    """FastAPI dependency wrapping the module-level Redis client."""
    return get_redis()


RedisDep = Annotated[Redis, Depends(get_redis_dep)]


# ─── Repository factories ────────────────────────────────────────────────────


def get_user_repository(session: DbSession) -> UserRepository:
    return UserRepository(session)


def get_user_address_repository(session: DbSession) -> UserAddressRepository:
    return UserAddressRepository(session)


def get_otp_repository(session: DbSession) -> OtpRepository:
    return OtpRepository(session)


def get_admin_user_repository(session: DbSession) -> AdminUserRepository:
    return AdminUserRepository(session)


def get_admin_session_repository(session: DbSession) -> AdminSessionRepository:
    return AdminSessionRepository(session)


def get_branch_repository(session: DbSession) -> BranchRepository:
    return BranchRepository(session)


# ─── Service factories ───────────────────────────────────────────────────────


def get_token_issuer(settings: SettingsDep) -> TokenIssuer:
    return TokenIssuer(settings)


def get_otp_service(
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    otps: Annotated[OtpRepository, Depends(get_otp_repository)],
    token_issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> OtpService:
    return OtpService(
        settings=settings,
        users=users,
        otps=otps,
        sms_queue=get_sms_queue(),
        token_issuer=token_issuer,
    )


def get_auth_service(
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    token_issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> AuthService:
    return AuthService(
        settings=settings,
        users=users,
        token_issuer=token_issuer,
    )


def get_account_service(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    addresses: Annotated[UserAddressRepository, Depends(get_user_address_repository)],
) -> AccountService:
    return AccountService(users=users, addresses=addresses)


def get_admin_auth_service(
    settings: SettingsDep,
    admins: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
    sessions: Annotated[AdminSessionRepository, Depends(get_admin_session_repository)],
) -> AdminAuthService:
    return AdminAuthService(settings=settings, admins=admins, sessions=sessions)
