"""Identity domain — services.

Four services orchestrating the OTP / JWT / admin auth use cases:

* :class:`OtpService` — request_code, verify_and_issue_tokens.
* :class:`AuthService` — refresh, logout (rotates ``jti`` in Redis).
* :class:`AccountService` — get_me, update_me, addresses CRUD with
  default-toggle handling.
* :class:`AdminAuthService` — login_with_password (with lockout),
  get_admin_by_token, logout.

Reference: BACKEND_BLUEPRINT.md §12, §14; PRODUCT_BLUEPRINT.md §8.1.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

from jose import JWTError

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    InvalidOTPError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.i18n import resolve_language, t
from app.core.logging import get_logger
from app.core.ratelimit import hit
from app.core.redis import get_redis
from app.core.security import (
    CUSTOMER_KIND,
    REFRESH_TYPE,
    TokenIssuer,
    TokenPair,
    generate_numeric_code,
    hash_otp,
    verify_otp,
    verify_password,
)
from app.core.time import ensure_utc, utcnow
from app.domain.identity.models import AdminUser, User, UserAddress
from app.domain.identity.repositories import (
    AdminSessionRepository,
    AdminUserRepository,
    OtpRepository,
    UserAddressRepository,
    UserRepository,
)
from app.integrations.sms.base import SmsMessage, SmsQueue

log = get_logger(__name__)


# ─── Refresh-jti store (Redis) ────────────────────────────────────────────────

# Keyed under v1:session:refresh:<jti>; value = user_id; TTL = refresh TTL.
# Logout / rotation deletes the jti; absence = "revoked".

_REFRESH_PREFIX = "v1:session:refresh"


async def _store_refresh_jti(*, jti: str, user_id: str, ttl_seconds: int) -> None:
    r = get_redis()
    await r.set(f"{_REFRESH_PREFIX}:{jti}", user_id, ex=ttl_seconds)


async def _delete_refresh_jti(jti: str) -> None:
    r = get_redis()
    await r.delete(f"{_REFRESH_PREFIX}:{jti}")


async def _refresh_jti_owner(jti: str) -> str | None:
    r = get_redis()
    val = await r.get(f"{_REFRESH_PREFIX}:{jti}")
    return val if val is None else str(val)


# ─── OtpService ───────────────────────────────────────────────────────────────


class OtpService:
    """Issue and verify SMS-OTP codes; mint customer JWT pairs."""

    def __init__(
        self,
        *,
        settings: Settings,
        users: UserRepository,
        otps: OtpRepository,
        sms_queue: SmsQueue,
        token_issuer: TokenIssuer,
    ) -> None:
        self.settings = settings
        self.users = users
        self.otps = otps
        self.sms_queue = sms_queue
        self.token_issuer = token_issuer

    async def request_code(self, *, phone: str, ip_address: str | None) -> int:
        """Rate-limit, generate a code, hash, store, enqueue SMS. Returns TTL."""
        # Per-phone burst (1/60s) + sustained (3/15m) + per-IP (10/h).
        # Order: burst first (cheapest signal), then sustained, then IP.
        await hit(
            key=f"v1:rl:otp:phone_burst:{phone}",
            limit=1,
            window_seconds=60,
        )
        await hit(
            key=f"v1:rl:otp:phone:{phone}",
            limit=self.settings.rl_otp_request_per_phone_max,
            window_seconds=self.settings.rl_otp_request_per_phone_window_seconds,
        )
        if ip_address:
            await hit(
                key=f"v1:rl:otp:ip:{ip_address}",
                limit=10,
                window_seconds=3600,
            )

        code = generate_numeric_code(self.settings.otp_length)
        code_hash = hash_otp(code, self.settings.password_pepper.get_secret_value())
        ttl = self.settings.otp_ttl_seconds
        await self.otps.create(
            phone=phone,
            code_hash=code_hash,
            purpose="login",
            expires_at=utcnow() + timedelta(seconds=ttl),
            ip_address=ip_address,
            max_attempts=self.settings.otp_max_attempts,
        )

        # SMS templates only exist in ru.json — Phase 4 sends RU codes;
        # Phase 10 may revisit. Body template carries `{code}` placeholder.
        body = t("sms.otp", "ru", code=code)
        await self.sms_queue.enqueue(SmsMessage(phone=phone, body=body, purpose="otp"))
        log.info("otp_requested", phone=phone)
        return ttl

    async def verify_and_issue_tokens(
        self,
        *,
        phone: str,
        code: str,
        accept_language: str | None = None,
    ) -> tuple[TokenPair, User]:
        """Verify OTP, auto-create user if needed, issue token pair."""
        otp = await self.otps.get_active_for_phone(phone)
        if otp is None:
            raise InvalidOTPError(code="not_found_or_expired")
        if otp.attempts >= otp.max_attempts:
            raise InvalidOTPError(code="too_many_attempts")
        if not verify_otp(
            code,
            otp.code_hash,
            self.settings.password_pepper.get_secret_value(),
        ):
            await self.otps.increment_attempts(otp)
            raise InvalidOTPError(code="wrong_code")
        await self.otps.mark_consumed(otp)

        language = resolve_language(accept_language)
        user, _created = await self.users.get_or_create_by_phone(phone, preferred_language=language)
        await self.users.update_last_login(user)

        pair = self.token_issuer.issue_pair(subject=str(user.id), kind=CUSTOMER_KIND)
        await _store_refresh_jti(
            jti=pair.refresh_jti,
            user_id=str(user.id),
            ttl_seconds=self.settings.jwt_refresh_ttl_days * 86400,
        )
        log.info("otp_verified", user_id=str(user.id), phone=phone)
        return (pair, user)


# ─── AuthService ──────────────────────────────────────────────────────────────


class AuthService:
    """Refresh + logout — rotates the ``jti`` stored in Redis."""

    def __init__(
        self,
        *,
        settings: Settings,
        users: UserRepository,
        token_issuer: TokenIssuer,
    ) -> None:
        self.settings = settings
        self.users = users
        self.token_issuer = token_issuer

    async def refresh(self, refresh_token: str) -> TokenPair:
        try:
            claims = self.token_issuer.decode(
                refresh_token,
                expected_type=REFRESH_TYPE,
                expected_kind=CUSTOMER_KIND,
            )
        except JWTError as e:
            raise AuthenticationError(code="invalid_refresh") from e

        old_jti: str = claims["jti"]
        user_id_str: str = claims["sub"]

        owner = await _refresh_jti_owner(old_jti)
        if owner is None or owner != user_id_str:
            raise AuthenticationError(code="refresh_revoked")

        user = await self.users.get_by_id(UUID(user_id_str))
        if user is None or not user.is_active:
            raise AuthenticationError(code="user_inactive")

        new_pair = self.token_issuer.issue_pair(subject=user_id_str, kind=CUSTOMER_KIND)
        await _delete_refresh_jti(old_jti)
        await _store_refresh_jti(
            jti=new_pair.refresh_jti,
            user_id=user_id_str,
            ttl_seconds=self.settings.jwt_refresh_ttl_days * 86400,
        )
        return new_pair

    async def logout(self, refresh_token: str) -> None:
        """Idempotent — invalid token is a no-op (security through silence)."""
        try:
            claims = self.token_issuer.decode(
                refresh_token,
                expected_type=REFRESH_TYPE,
                expected_kind=CUSTOMER_KIND,
            )
        except JWTError:
            return
        await _delete_refresh_jti(claims["jti"])


# ─── AccountService ───────────────────────────────────────────────────────────


class AccountService:
    """Customer profile + addresses CRUD."""

    def __init__(
        self,
        *,
        users: UserRepository,
        addresses: UserAddressRepository,
    ) -> None:
        self.users = users
        self.addresses = addresses

    async def get_me(self, user: User) -> User:
        return user

    async def update_me(
        self,
        user: User,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        preferred_language: str | None = None,
    ) -> User:
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if email is not None:
            user.email = email
        if preferred_language is not None:
            user.preferred_language = preferred_language
        await self.users.session.flush()
        return user

    async def list_addresses(self, user: User) -> list[UserAddress]:
        return list(await self.addresses.list_for_user(user.id))

    async def create_address(self, user: User, payload: dict[str, Any]) -> UserAddress:
        if payload.get("is_default"):
            await self.addresses.clear_default_for_user(user.id)
        addr = UserAddress(user_id=user.id, **payload)
        await self.addresses.add(addr)
        return addr

    async def update_address(
        self, user: User, address_id: int, payload: dict[str, Any]
    ) -> UserAddress:
        addr = await self.addresses.get_by_id_for_user(address_id, user.id)
        if addr is None:
            raise NotFoundError(code="address_not_found")
        if payload.get("is_default") is True and not addr.is_default:
            await self.addresses.clear_default_for_user(user.id)
        for key, value in payload.items():
            if value is not None:
                setattr(addr, key, value)
        await self.addresses.session.flush()
        # Refresh: ``updated_at`` (onupdate=utc_timestamp) and the
        # ``default_user_id`` generated column are server-set; without
        # refresh, AddressRead can't serialise them post-commit.
        await self.addresses.session.refresh(addr)
        return addr

    async def delete_address(self, user: User, address_id: int) -> None:
        addr = await self.addresses.get_by_id_for_user(address_id, user.id)
        if addr is None:
            raise NotFoundError(code="address_not_found")
        await self.addresses.delete(addr)


# ─── AdminAuthService ─────────────────────────────────────────────────────────


_ADMIN_LOCKOUT_THRESHOLD = 5
_ADMIN_LOCKOUT_MINUTES = 15


class AdminAuthService:
    """Email + password admin login with 5-attempt lockout."""

    def __init__(
        self,
        *,
        settings: Settings,
        admins: AdminUserRepository,
        sessions: AdminSessionRepository,
    ) -> None:
        self.settings = settings
        self.admins = admins
        self.sessions = sessions

    async def login_with_password(
        self,
        *,
        email: str,
        password: str,
        totp_code: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[AdminUser, str]:
        """Returns ``(admin, plaintext_token)``. Route sets the cookie."""
        admin = await self.admins.get_by_email(email)
        if admin is None or not admin.is_active:
            raise AuthenticationError(code="invalid_credentials")

        if admin.locked_until is not None and ensure_utc(admin.locked_until) > utcnow():
            raise PermissionDeniedError(code="account_locked")

        if not verify_password(
            password,
            admin.password_hash,
            self.settings.password_pepper.get_secret_value(),
        ):
            await self.admins.increment_failed_login(admin)
            if admin.failed_login_count >= _ADMIN_LOCKOUT_THRESHOLD:
                await self.admins.set_locked_until(
                    admin,
                    utcnow() + timedelta(minutes=_ADMIN_LOCKOUT_MINUTES),
                )
            # Commit the security side-effect BEFORE raising. This is a
            # documented exception to the "services don't commit" rule
            # (BACKEND §11.3, §12) — the lockout counter MUST survive the
            # exception-driven rollback that ``get_db`` performs.
            await self.admins.session.commit()
            raise AuthenticationError(code="invalid_credentials")

        # MFA: if mfa_secret is set, totp_code SHOULD be required. Phase 4
        # does not enforce TOTP — column exists, verification deferred to a
        # later phase (no pyotp dep yet). Document.
        if admin.mfa_secret and totp_code is None:
            log.warning("admin_mfa_skipped_phase4", admin_id=admin.id)

        await self.admins.reset_failed_login(admin)
        await self.admins.set_last_login(admin, utcnow())

        # Generate session token (plaintext for cookie, hash for DB).
        plaintext = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        await self.sessions.create(
            admin_user_id=admin.id,
            token_hash=token_hash,
            expires_at=utcnow() + timedelta(hours=self.settings.admin_session_ttl_hours),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        log.info("admin_login", admin_id=admin.id, email=email)
        return (admin, plaintext)

    async def get_admin_by_token(self, token: str) -> AdminUser | None:
        """Resolve cookie token → admin. None if invalid/expired/revoked."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        session_row = await self.sessions.get_active_by_token_hash(token_hash)
        if session_row is None:
            return None
        admin = await self.admins.get_by_id(session_row.admin_user_id)
        if admin is None or not admin.is_active:
            return None
        await self.sessions.update_last_seen(session_row)
        return admin

    async def logout(self, token: str) -> None:
        """Revoke the session for ``token``. No-op if not found."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        session_row = await self.sessions.get_active_by_token_hash(token_hash)
        if session_row is not None:
            await self.sessions.revoke(session_row)
