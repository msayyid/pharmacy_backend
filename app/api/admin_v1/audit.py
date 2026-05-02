"""Admin audit log viewer.

* ``GET /admin/v1/audit?actor=&entity_type=&entity_id=&action=&from=&to=&page=&page_size=``

PRODUCT §F-ADM-AUD-001: super_admin sees everything; branch_manager
sees their branch (filtered server-side via the ``admin_user_id`` →
admin's ``branch_id`` join).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_admin_audit_repository
from app.core.pagination import Page
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.orders.admin_schemas import AuditLogEntry

router = APIRouter(prefix="/audit", tags=["admin-audit"])

_AUDIT_ROLES = ("super_admin", "branch_manager")
_AuditActor = Annotated[AdminUser, Depends(require_role(*_AUDIT_ROLES))]


@router.get("", response_model=Page[AuditLogEntry])
async def list_audit(
    actor: _AuditActor,
    repo: Annotated[AdminAuditLogRepository, Depends(get_admin_audit_repository)],
    actor_id: Annotated[int | None, Query(alias="actor")] = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    from_dt: Annotated[datetime | None, Query(alias="from")] = None,
    to_dt: Annotated[datetime | None, Query(alias="to")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[AuditLogEntry]:
    items, total = await repo.list_paginated(
        admin_user_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        from_dt=from_dt,
        to_dt=to_dt,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[AuditLogEntry](
        items=[AuditLogEntry.model_validate(row) for row in items],
        total=total,
        page=page,
        page_size=page_size,
    )
