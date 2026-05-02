"""Operations services — admin audit log writer.

The :class:`AdminAuditLogService` is the single helper every catalog /
inventory / order admin service uses to record mutations. Phase 9 adds
the read-side viewer; Phase 5 ships only the writer.

The audit row is committed in the SAME transaction as the mutation. If
the mutation rolls back, the audit also rolls back — the log records
what happened, not what was attempted (CLAUDE_CODE_PROMPTS Phase 5
guidance).

Reference: PHARMACY_BLUEPRINT_2.md §8.1.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.domain.ops.models import AdminAuditLog
from app.domain.ops.repositories import AdminAuditLogRepository


class AdminAuditLogService:
    def __init__(self, repo: AdminAuditLogRepository) -> None:
        self.repo = repo

    async def record(
        self,
        *,
        admin_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int | str | UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AdminAuditLog:
        """Record a mutation. ``before`` / ``after`` form the JSON ``changes`` blob."""
        changes: dict[str, Any] | None = None
        if before is not None or after is not None:
            changes = {"before": before, "after": after}
        return await self.repo.create(
            admin_user_id=admin_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent,
        )
