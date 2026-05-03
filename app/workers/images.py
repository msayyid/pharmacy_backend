"""ARQ ``process_image_upload`` worker function.

Reads a temp-file blob written by the API route, runs Pillow resize +
storage upload via the Phase 5+10 :class:`ProductImageService`, removes
the temp file. The route invocation switch (inline call → enqueue
job + return 202) is Phase 12 cleanup; the worker body is shipped
now so it's exercisable.

Reference: BACKEND §17.3, §19.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.logging import get_logger
from app.domain.catalog.images import ProductImageService
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import AdminUser
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from app.integrations.storage.factory import get_storage_client

log = get_logger(__name__)


async def process_image_upload(
    ctx: dict[str, Any],
    *,
    temp_path: str,
    product_id: str,
    content_type: str,
    actor_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Worker body — opens session, runs the inline upload helper,
    then removes the temp file.

    JSON-serialisable args (per BACKEND §17.5): ``product_id`` is a UUID
    string, ``actor_id`` is an int admin id; the worker re-loads the
    AdminUser inside the new session.
    """
    path = Path(temp_path)
    if not path.exists():
        log.warning("process_image_upload_missing_temp", temp_path=temp_path)
        return {"status": "missing_temp"}
    file_bytes = path.read_bytes()
    settings = get_settings()
    pid = UUID(product_id)

    async with session_scope() as session:
        actor = await session.get(AdminUser, actor_id)
        if actor is None:
            log.warning("process_image_upload_unknown_actor", actor_id=actor_id)
            return {"status": "unknown_actor"}
        svc = ProductImageService(
            products=ProductRepository(session),
            audit=AdminAuditLogService(AdminAuditLogRepository(session)),
            storage_dir=Path(settings.image_storage_dir),
            public_base_url=settings.image_public_base_url,
            max_bytes=settings.image_max_bytes,
            storage=get_storage_client(),
        )
        record = await svc.upload(
            product_id=pid,
            file_bytes=file_bytes,
            content_type=content_type,
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # Best-effort cleanup; missing temp file is fine (already gone).
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        log.warning("process_image_upload_cleanup_failed", error=str(exc))

    log.info(
        "process_image_upload_done",
        product_id=product_id,
        image_id=record.id,
        actor_id=actor_id,
    )
    return {"status": "ok", "image_id": record.id}
