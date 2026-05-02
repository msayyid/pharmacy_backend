"""Security primitives.

* :func:`hash_password` / :func:`verify_password` — argon2id via ``passlib``,
  pepper appended before hashing.
* :func:`hash_otp` / :func:`verify_otp` — HMAC-SHA256 with pepper, constant-
  time compare. argon2 is overkill for short numeric OTPs.
* :func:`generate_numeric_code` — cryptographically random N-digit string.
* :func:`normalise_phone` — parse to E.164 via ``phonenumbers``; default
  region "KG" per PRODUCT §16.5.
* :class:`TokenIssuer` — JWT access (15 min) + refresh (30 days). Includes
  ``kid`` header (rotation scaffold) and ``jti`` claim from uuid7.
* :class:`TokenPair` — wraps the issued tokens + jtis (refresh ``jti`` is
  what Phase 4 will store in Redis for revocation).

Reference: BACKEND_BLUEPRINT.md §14.6, §20.3; PRODUCT_BLUEPRINT.md §16.5.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import phonenumbers
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import Settings, get_settings
from app.core.types import uuid7

# ─── Password hashing (argon2id) ──────────────────────────────────────────────

_pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__type="ID",
    argon2__memory_cost=65536,
    argon2__time_cost=3,
    argon2__parallelism=2,
)


def hash_password(plain: str, pepper: str) -> str:
    """Hash a password with argon2id + appended pepper."""
    return _pwd_context.hash(plain + pepper)


def verify_password(plain: str, hashed: str, pepper: str) -> bool:
    """Verify a password against an argon2 hash. False on any error."""
    try:
        return _pwd_context.verify(plain + pepper, hashed)
    except Exception:
        return False


# ─── OTP hashing (HMAC-SHA256, constant-time verify) ──────────────────────────


def hash_otp(code: str, pepper: str) -> str:
    """HMAC-SHA256 of ``code`` keyed by ``pepper`` — fast, deterministic, hex out."""
    return hmac.new(pepper.encode(), code.encode(), hashlib.sha256).hexdigest()


def verify_otp(code: str, hashed: str, pepper: str) -> bool:
    """Constant-time compare against the stored HMAC hex digest."""
    return hmac.compare_digest(hash_otp(code, pepper), hashed)


def generate_numeric_code(length: int) -> str:
    """Cryptographically random N-digit numeric string (uses ``secrets``)."""
    if length <= 0:
        raise ValueError("length must be > 0")
    return "".join(secrets.choice("0123456789") for _ in range(length))


# ─── Phone normalization ──────────────────────────────────────────────────────


def normalise_phone(value: str, default_region: str = "KG") -> str:
    """Parse and normalise to E.164 (e.g. ``+996700123456``).

    * ``"+996 700 12 34 56"`` → ``"+996700123456"``
    * ``"0700123456"`` (with default ``"KG"``) → ``"+996700123456"``
    * Raises :class:`ValueError` on invalid input.
    """
    try:
        n = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException as e:
        raise ValueError(f"invalid phone: {e}") from e
    if not phonenumbers.is_valid_number(n):
        raise ValueError("invalid phone")
    return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)


# ─── JWT ──────────────────────────────────────────────────────────────────────

CUSTOMER_KIND = "customer"
ADMIN_KIND = "admin"
ACCESS_TYPE = "access"
REFRESH_TYPE = "refresh"

# Single key id for now — rotation deferred per DECISION_LOG.
DEFAULT_KID = "k1"


@dataclass(frozen=True, slots=True)
class TokenPair:
    """Issued token bundle. ``refresh_jti`` is what Phase 4 stores in Redis."""

    access: str
    refresh: str
    access_jti: str
    refresh_jti: str


class TokenIssuer:
    """Issues and decodes JWT access/refresh pairs.

    Access TTL: ``settings.jwt_access_ttl_minutes`` (default 15).
    Refresh TTL: ``settings.jwt_refresh_ttl_days`` (default 30).
    Header carries ``kid`` for future rotation; algorithm is ``HS256``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def issue_pair(self, *, subject: str, kind: str) -> TokenPair:
        access_jti = str(uuid7())
        refresh_jti = str(uuid7())
        access = self._encode(
            subject=subject,
            kind=kind,
            token_type=ACCESS_TYPE,
            jti=access_jti,
            ttl=timedelta(minutes=self.settings.jwt_access_ttl_minutes),
        )
        refresh = self._encode(
            subject=subject,
            kind=kind,
            token_type=REFRESH_TYPE,
            jti=refresh_jti,
            ttl=timedelta(days=self.settings.jwt_refresh_ttl_days),
        )
        return TokenPair(access, refresh, access_jti, refresh_jti)

    def _encode(
        self,
        *,
        subject: str,
        kind: str,
        token_type: str,
        jti: str,
        ttl: timedelta,
    ) -> str:
        now = datetime.now(UTC)
        claims = {
            "sub": subject,
            "kind": kind,
            "type": token_type,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
        }
        token: str = jwt.encode(
            claims,
            self.settings.jwt_secret.get_secret_value(),
            algorithm=self.settings.jwt_algorithm,
            headers={"kid": DEFAULT_KID},
        )
        return token

    def decode(
        self,
        token: str,
        *,
        expected_type: str,
        expected_kind: str,
    ) -> dict[str, Any]:
        """Decode and validate ``type`` + ``kind``. Raises ``JWTError`` on invalid."""
        claims: dict[str, Any] = jwt.decode(
            token,
            self.settings.jwt_secret.get_secret_value(),
            algorithms=[self.settings.jwt_algorithm],
        )
        if claims.get("type") != expected_type:
            raise JWTError(f"wrong token type: expected {expected_type!r}")
        if claims.get("kind") != expected_kind:
            raise JWTError(f"wrong token kind: expected {expected_kind!r}")
        return claims
