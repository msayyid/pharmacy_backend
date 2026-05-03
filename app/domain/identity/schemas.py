"""Identity domain — Pydantic schemas (request/response shapes).

Naming convention (BACKEND §10):

* ``XxxIn``   — request body  (extra="forbid")
* ``XxxOut``  — response body (from_attributes=True for ORM-fed reads)
* ``XxxRead`` — list-item read shape
* ``XxxUpdate`` — PATCH-shape, all fields Optional, extra="forbid"

Reference: BACKEND_BLUEPRINT.md §10; PRODUCT_BLUEPRINT.md §8.1, §8.3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import normalise_phone


def _validate_phone(value: str) -> str:
    """Phone validator — normalises to E.164 (KG default) and raises on invalid."""
    try:
        return normalise_phone(value)
    except ValueError as e:
        # Re-raise as ValueError so Pydantic includes it in the validation report.
        raise ValueError(str(e)) from e


# ─── OTP / Auth ───────────────────────────────────────────────────────────────


class OtpRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _validate_phone(v)


class OtpRequestOut(BaseModel):
    sent: bool
    expires_in_seconds: int


class OtpVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str
    code: Annotated[str, Field(min_length=4, max_length=10)]

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _validate_phone(v)

    @field_validator("code")
    @classmethod
    def _digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("code must be all digits")
        return v


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — OAuth scheme literal, not a secret
    expires_in: int  # access-token TTL in seconds


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


class LogoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str


# ─── Password auth (dev convenience — see DECISION_LOG) ──────────────────────


class RegisterIn(BaseModel):
    """``POST /api/v1/auth/register`` — email + password + phone.

    Production deploys still use SMS-OTP per spec; this is a local-dev
    convenience added on top of v1.0.0-rc1.
    """

    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]
    phone: str
    first_name: Annotated[str | None, Field(max_length=80)] = None
    last_name: Annotated[str | None, Field(max_length=80)] = None
    preferred_language: Literal["ru", "ky", "en"] = "ru"

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return _validate_phone(v)


class PasswordLoginIn(BaseModel):
    """``POST /api/v1/auth/login`` — email + password → JWT pair."""

    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class RegisterOut(BaseModel):
    """Register returns the user's id + the full token pair."""

    user_id: UUID
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — OAuth scheme literal
    expires_in: int


# ─── /me ──────────────────────────────────────────────────────────────────────


class UserMeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    phone: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    preferred_language: str
    is_phone_verified: bool
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserMeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: Annotated[str | None, Field(max_length=80)] = None
    last_name: Annotated[str | None, Field(max_length=80)] = None
    email: EmailStr | None = None
    preferred_language: Literal["ru", "ky", "en"] | None = None


# ─── Addresses ────────────────────────────────────────────────────────────────


class AddressBase(BaseModel):
    label: Annotated[str | None, Field(max_length=40)] = None
    recipient_name: Annotated[str | None, Field(max_length=160)] = None
    recipient_phone: str | None = None
    city: Annotated[str, Field(max_length=80)] = "Bishkek"
    address_line: Annotated[str, Field(min_length=1)]
    landmark: str | None = None
    is_default: bool = False

    @field_validator("recipient_phone")
    @classmethod
    def _opt_phone(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _validate_phone(v)


class AddressCreate(AddressBase):
    model_config = ConfigDict(extra="forbid")


class AddressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Annotated[str | None, Field(max_length=40)] = None
    recipient_name: Annotated[str | None, Field(max_length=160)] = None
    recipient_phone: str | None = None
    city: Annotated[str | None, Field(max_length=80)] = None
    address_line: str | None = None
    landmark: str | None = None
    is_default: bool | None = None

    @field_validator("recipient_phone")
    @classmethod
    def _opt_phone(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _validate_phone(v)


class AddressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    city: str
    address_line: str
    landmark: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime


# ─── Admin auth ───────────────────────────────────────────────────────────────


class AdminLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: Annotated[str, Field(min_length=1)]
    totp_code: Annotated[str | None, Field(min_length=6, max_length=6)] = None


class AdminMeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    branch_id: int | None
    is_active: bool
