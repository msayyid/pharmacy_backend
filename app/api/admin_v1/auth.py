"""Admin auth endpoints — ``/api/admin/v1/auth/*``.

* ``POST /admin/v1/auth/login``  — email + password (+ optional totp_code);
  sets ``admin_session`` HttpOnly cookie.
* ``POST /admin/v1/auth/logout`` — revokes the session, clears the cookie.
* ``GET  /admin/v1/auth/me``     — returns the current admin (cookie-based).

The cookie's ``Secure`` flag is gated on ``settings.env`` — disabled in
``local``/``test`` (HTTP dev) and enabled everywhere else.

Reference: BACKEND_BLUEPRINT.md §13, §14.4.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.deps import SettingsDep, get_admin_auth_service
from app.domain.identity.dependencies import ADMIN_COOKIE_NAME, CurrentAdmin
from app.domain.identity.schemas import AdminLoginIn, AdminMeRead
from app.domain.identity.services import AdminAuthService

router = APIRouter(prefix="/auth", tags=["admin-auth"])


@router.post("/login", response_model=AdminMeRead)
async def admin_login(
    payload: AdminLoginIn,
    request: Request,
    response: Response,
    settings: SettingsDep,
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> AdminMeRead:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    admin, token = await service.login_with_password(
        email=str(payload.email),
        password=payload.password,
        totp_code=payload.totp_code,
        ip_address=ip,
        user_agent=ua,
    )
    # Secure flag off in local/test (HTTP dev); on everywhere else.
    secure = settings.env not in ("local", "test")
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        max_age=settings.admin_session_ttl_hours * 3600,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    return AdminMeRead.model_validate(admin)


@router.post("/logout")
async def admin_logout(
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
    admin_session: Annotated[str | None, Cookie(alias=ADMIN_COOKIE_NAME)] = None,
) -> Response:
    if admin_session:
        await service.logout(admin_session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response


@router.get("/me", response_model=AdminMeRead)
async def admin_me(admin: CurrentAdmin) -> AdminMeRead:
    return AdminMeRead.model_validate(admin)
