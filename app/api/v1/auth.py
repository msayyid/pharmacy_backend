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
    RefreshIn,
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
