"""Customer auth endpoints — ``/api/v1/auth/*``.

Endpoints:

* ``POST /auth/otp/request``  — issue OTP, rate-limit per phone + IP.
* ``POST /auth/otp/verify``   — verify code, auto-create user, return tokens.
* ``POST /auth/refresh``      — rotate the refresh ``jti``, return new pair.
* ``POST /auth/logout``       — revoke refresh ``jti``.

Reference: BACKEND_BLUEPRINT.md §13, §14; PRODUCT_BLUEPRINT.md §8.1.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import SettingsDep, get_auth_service, get_otp_service
from app.domain.identity.schemas import (
    LogoutIn,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    PasswordLoginIn,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    TokenPairOut,
)
from app.domain.identity.services import AuthService, OtpService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/otp/request",
    response_model=OtpRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_otp(
    payload: OtpRequestIn,
    request: Request,
    service: Annotated[OtpService, Depends(get_otp_service)],
) -> OtpRequestOut:
    ip = request.client.host if request.client else None
    ttl = await service.request_code(phone=payload.phone, ip_address=ip)
    return OtpRequestOut(sent=True, expires_in_seconds=ttl)


@router.post("/otp/verify", response_model=TokenPairOut)
async def verify_otp(
    payload: OtpVerifyIn,
    request: Request,
    settings: SettingsDep,
    service: Annotated[OtpService, Depends(get_otp_service)],
) -> TokenPairOut:
    accept_language = request.headers.get("accept-language")
    pair, _ = await service.verify_and_issue_tokens(
        phone=payload.phone,
        code=payload.code,
        accept_language=accept_language,
    )
    return TokenPairOut(
        access_token=pair.access,
        refresh_token=pair.refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


@router.post("/refresh", response_model=TokenPairOut)
async def refresh(
    payload: RefreshIn,
    settings: SettingsDep,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPairOut:
    pair = await service.refresh(payload.refresh_token)
    return TokenPairOut(
        access_token=pair.access,
        refresh_token=pair.refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def logout(
    payload: LogoutIn,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    await service.logout(payload.refresh_token)


# ─── Password auth (dev convenience — see DECISION_LOG) ─────────────────────


@router.post(
    "/register",
    response_model=RegisterOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer with email + password (dev)",
    description=(
        "Create a customer account using email + argon2id password + phone. "
        "Returns the user id + a JWT pair. **Local-dev convenience added on "
        "top of v1.0.0-rc1.** Production deploys still use SMS-OTP per spec "
        "(see PRODUCT §17 + PHARMACY §3.2)."
    ),
)
async def register(
    payload: RegisterIn,
    settings: SettingsDep,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> RegisterOut:
    user, pair = await service.register_with_password(
        email=str(payload.email),
        password=payload.password,
        phone=payload.phone,
        first_name=payload.first_name,
        last_name=payload.last_name,
        preferred_language=payload.preferred_language,
    )
    return RegisterOut(
        user_id=user.id,
        access_token=pair.access,
        refresh_token=pair.refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


@router.post(
    "/login",
    response_model=TokenPairOut,
    summary="Log in with email + password (dev)",
    description=(
        "Email + argon2id password verify → JWT pair. Returns the same shape "
        "as ``/auth/otp/verify``. **Local-dev convenience.**"
    ),
)
async def password_login(
    payload: PasswordLoginIn,
    settings: SettingsDep,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenPairOut:
    pair = await service.login_with_password(
        email=str(payload.email),
        password=payload.password,
    )
    return TokenPairOut(
        access_token=pair.access,
        refresh_token=pair.refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )
