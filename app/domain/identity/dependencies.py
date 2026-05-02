"""Identity — auth dependencies for the API layer.

* :func:`get_current_user` — Bearer JWT → ``User`` (customer flow).
* :func:`get_current_admin` — admin session cookie → ``AdminUser``.
* :func:`require_role` — factory that returns a dep gating on admin role.
* :func:`require_branch_access` — factory that returns a dep ensuring the
  acting admin's ``branch_id`` matches a path parameter (``super_admin``
  bypasses).

Type aliases ``CurrentUser`` / ``CurrentAdmin`` are re-exported for routes.

Reference: BACKEND_BLUEPRINT.md §14.3, §14.5; PRODUCT_BLUEPRINT.md §19.5.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Cookie, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.api.deps import (
    SettingsDep,
    get_admin_auth_service,
    get_token_issuer,
    get_user_repository,
)
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import ACCESS_TYPE, CUSTOMER_KIND, TokenIssuer
from app.domain.identity.models import AdminUser, User
from app.domain.identity.repositories import UserRepository
from app.domain.identity.services import AdminAuthService

# ─── Customer JWT ─────────────────────────────────────────────────────────────

# auto_error=False so we can produce a typed AuthenticationError instead of
# FastAPI's default 403/401 HTTPException — exception_handlers translate it.
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    token_issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> User:
    """Resolve the current customer from the ``Authorization: Bearer`` header.

    Raises :class:`AuthenticationError` (HTTP 401) on missing / invalid /
    expired / wrong-kind / wrong-type / inactive-user cases.
    """
    if creds is None or not creds.credentials:
        raise AuthenticationError(code="missing_token")
    try:
        claims = token_issuer.decode(
            creds.credentials,
            expected_type=ACCESS_TYPE,
            expected_kind=CUSTOMER_KIND,
        )
    except JWTError as e:
        raise AuthenticationError(code="invalid_token") from e

    try:
        user_id = UUID(claims["sub"])
    except (KeyError, ValueError) as e:
        raise AuthenticationError(code="invalid_token") from e

    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError(code="user_inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ─── Admin session cookie ─────────────────────────────────────────────────────

ADMIN_COOKIE_NAME = "admin_session"


async def get_current_admin(
    admin_session: Annotated[str | None, Cookie(alias=ADMIN_COOKIE_NAME)] = None,
    admin_auth: Annotated[AdminAuthService, Depends(get_admin_auth_service)] = ...,  # type: ignore[assignment]
) -> AdminUser:
    """Resolve the current admin from the ``admin_session`` cookie."""
    if admin_session is None or not admin_session:
        raise AuthenticationError(code="missing_session")
    admin = await admin_auth.get_admin_by_token(admin_session)
    if admin is None:
        raise AuthenticationError(code="invalid_session")
    return admin


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]


# ─── RBAC dependency factories ────────────────────────────────────────────────


def require_role(
    *allowed: str,
) -> Callable[[AdminUser], Coroutine[Any, Any, AdminUser]]:
    """FastAPI dependency factory: require the current admin to have a role in ``allowed``.

    Usage::

        @router.post("/admin/products",
                     dependencies=[Depends(require_role("super_admin", "content_editor"))])
    """

    async def _dep(
        admin: Annotated[AdminUser, Depends(get_current_admin)],
    ) -> AdminUser:
        if admin.role not in allowed:
            raise PermissionDeniedError(
                code="forbidden_role",
                role=admin.role,
                allowed=list(allowed),
            )
        return admin

    return _dep


def require_branch_access(
    target_branch_id_param: str = "branch_id",
) -> Callable[..., Coroutine[Any, Any, AdminUser]]:
    """FastAPI dependency factory: ensure admin's branch matches a path param.

    ``super_admin`` bypasses the check (NULL ``branch_id``).
    """

    async def _dep(
        request: Request,
        admin: Annotated[AdminUser, Depends(get_current_admin)],
    ) -> AdminUser:
        if admin.role == "super_admin":
            return admin
        try:
            target_raw = request.path_params[target_branch_id_param]
            target = int(target_raw)
        except (KeyError, ValueError, TypeError) as e:
            raise PermissionDeniedError(code="branch_param_missing") from e
        if admin.branch_id != target:
            raise PermissionDeniedError(
                code="forbidden_branch",
                admin_branch=admin.branch_id,
                target_branch=target,
            )
        return admin

    return _dep
