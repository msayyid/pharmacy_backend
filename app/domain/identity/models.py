"""Identity domain — customers, addresses, OTP, admins, admin sessions.

* :class:`User` — end-customer; UUID PK; phone is the primary identifier.
* :class:`UserAddress` — delivery addresses; "one default per user" is
  enforced via a generated column ``default_user_id`` + UNIQUE constraint
  (BACKEND §6.5 partial-unique workaround for MySQL).
* :class:`OtpCode` — phone-OTP codes; hashed at rest; hard-deleted by a
  cleanup job after 7 days.
* :class:`AdminUser` — pharmacy staff; email + argon2 password + optional
  TOTP; ``branch_id`` is NULL only for ``super_admin`` (CHECK constraint).
* :class:`AdminSession` — server-side admin sessions; cookie carries the
  plaintext token, the table stores its SHA-256 hash.

Reference: PHARMACY_BLUEPRINT_2.md §4; BACKEND_BLUEPRINT.md §8, §14.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BINARY, DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, SoftDeleteMixin, TimestampMixin
from app.core.types import GUID

if TYPE_CHECKING:
    from app.domain.inventory.models import Branch


# ─── User ─────────────────────────────────────────────────────────────────────


class User(Base, TimestampMixin, SoftDeleteMixin):
    """End-customer account. Phone is the only identifier; email is optional."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    # email is optional; case-insensitive uniqueness comes from the column's
    # default collation (utf8mb4_0900_ai_ci). Multiple NULLs are allowed by
    # InnoDB's UNIQUE semantics.
    email: Mapped[str | None] = mapped_column(String(255))
    # Optional argon2id hash. SMS-OTP users have ``None``; password-auth
    # users (dev convenience added 2026-05-03 — see DECISION_LOG) have a
    # hash here. Two parallel auth flows by design.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    date_of_birth: Mapped[date | None] = mapped_column()
    preferred_language: Mapped[str] = mapped_column(String(2), nullable=False, default="ru")
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))

    addresses: Mapped[list[UserAddress]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("phone", name="uq_users_phone"),
        UniqueConstraint("email", name="uq_users_email"),
        Index("idx_users_created_at", "created_at"),
        CheckConstraint(
            "preferred_language IN ('ru','ky','en')",
            name="chk_users_lang",
        ),
        # MySQL REGEXP — `[+]` to avoid backslash escaping pain.
        CheckConstraint(
            "phone REGEXP '^[+][0-9]{10,15}$'",
            name="chk_users_phone_format",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── UserAddress ──────────────────────────────────────────────────────────────


class UserAddress(Base, TimestampMixin):
    """Delivery address. Free-text address line + optional landmark
    (Bishkek addresses don't fit Western forms).

    "One default address per user" is enforced via the ``default_user_id``
    generated column: it equals ``user_id`` when ``is_default=TRUE`` and
    NULL otherwise. UNIQUE on that column = at most one default per user.
    BACKEND §6.5 workaround for MySQL's lack of partial-unique indexes.
    """

    __tablename__ = "user_addresses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # NOTE: ON DELETE RESTRICT (not CASCADE per PHARMACY §4.2) — MySQL forbids
    # a STORED generated column from referencing a column whose FK uses
    # CASCADE/SET NULL/SET DEFAULT. The default_user_id generated column needs
    # this FK to be NO ACTION/RESTRICT. Users are soft-deleted in practice
    # (deleted_at), so RESTRICT never fires; ORM-level cascade="all,
    # delete-orphan" handles orphan cleanup before any hard delete.
    # See DECISION_LOG.
    user_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("users.id", name="fk_user_addresses_user", ondelete="RESTRICT"),
        nullable=False,
    )
    label: Mapped[str | None] = mapped_column(String(40))
    recipient_name: Mapped[str | None] = mapped_column(String(160))
    recipient_phone: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="Bishkek")
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    landmark: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Generated column: equals user_id (BINARY(16)) when is_default, else NULL.
    # UNIQUE on this column enforces "at most one default address per user".
    default_user_id: Mapped[bytes | None] = mapped_column(
        BINARY(16),
        Computed("IF(is_default, user_id, NULL)", persisted=True),
    )

    user: Mapped[User] = relationship(back_populates="addresses", lazy="raise")

    __table_args__ = (
        UniqueConstraint(
            "default_user_id",
            name="uq_user_addresses_default_user",
        ),
        Index("idx_user_addresses_user", "user_id"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── OtpCode ──────────────────────────────────────────────────────────────────


class OtpCode(Base):
    """Phone-verification OTP. Hashed at rest; never plaintext.

    Hard-deleted by a cleanup job (cron, Phase 11) after 7 days.
    The ``attempts`` counter is the lockout mechanism; combined with the
    request rate limit (3/15m/phone), brute-force is bounded.
    """

    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    consumed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        Index("idx_otp_phone_expires", "phone", "expires_at"),
        Index("idx_otp_expires_at", "expires_at"),
        CheckConstraint(
            "purpose IN ('login','signup','phone_change')",
            name="chk_otp_purpose",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── AdminUser ────────────────────────────────────────────────────────────────


class AdminUser(Base, TimestampMixin):
    """Pharmacy staff account. Email + argon2id password + optional TOTP."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    branch_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("branches.id", name="fk_admin_users_branch", ondelete="RESTRICT"),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))

    branch: Mapped[Branch | None] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("email", name="uq_admin_users_email"),
        Index("idx_admin_users_branch", "branch_id"),
        CheckConstraint(
            "role IN ('super_admin','branch_manager','pharmacist','content_editor')",
            name="chk_admin_role",
        ),
        CheckConstraint(
            "role = 'super_admin' OR branch_id IS NOT NULL",
            name="chk_admin_branch_required",
        ),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


# ─── AdminSession ─────────────────────────────────────────────────────────────


class AdminSession(Base):
    """Server-side admin session. Cookie carries the plaintext token; the
    table stores its SHA-256 hash for lookup."""

    __tablename__ = "admin_sessions"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    admin_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", name="fk_admin_sessions_admin", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    last_seen_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6),
        nullable=False,
        server_default=func.utc_timestamp(6),
    )

    __table_args__ = (
        Index("idx_admin_sessions_admin", "admin_user_id"),
        Index("idx_admin_sessions_token", "token_hash"),
        Index("idx_admin_sessions_expires", "expires_at"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )
