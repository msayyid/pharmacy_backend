"""ARQ ``process_product_import`` worker function.

Phase 5 ships an inline import endpoint capped at 500 rows; Phase 11
adds the worker so admin can hand off larger files. Progress streams
to a Redis hash ``v1:import:<import_id>`` (``processed`` /
``total`` / ``status`` / ``errors_json``) so the admin UI can poll.

The route swap (return ``202 + import_id`` for >500-row uploads) is
Phase 12 cleanup; the worker body is shipped now so it's exercisable.

JSON-serialisable args (BACKEND §17.5):
* ``import_id`` — string, the Redis key suffix the admin polls.
* ``csv_bytes_b64`` — base64-encoded CSV file.
* ``actor_id`` — int admin id (worker re-loads inside the new session).
"""

from __future__ import annotations

import base64
import time
from typing import Any

import orjson

from app.core.db import session_scope
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.domain.catalog.import_csv import ProductImportService
from app.domain.catalog.products import ProductService
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    ProductRepository,
    SymptomRepository,
)
from app.domain.identity.models import AdminUser
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService

log = get_logger(__name__)


WORKER_MAX_ROWS = 10_000  # >500 path; inline endpoint stays at 500
PROGRESS_TTL_SECONDS = 24 * 3600


def _progress_key(import_id: str) -> str:
    return f"v1:import:{import_id}"


async def _set_progress(import_id: str, **fields: Any) -> None:
    """Best-effort Redis hash write for the polling UI."""
    try:
        redis = get_redis()
    except RuntimeError:
        return
    key = _progress_key(import_id)
    encoded: dict[str, str | int | bytes] = {}
    for k, v in fields.items():
        if isinstance(v, str | int):
            encoded[k] = v
        else:
            encoded[k] = orjson.dumps(v)
    # Redis 5.x async typing returns Awaitable[int] for hset/expire when
    # the client is async; the actual coroutine awaits cleanly. Cast
    # via a local to silence mypy without losing runtime correctness.
    hset_result: Any = redis.hset(key, mapping=encoded)
    await hset_result
    expire_result: Any = redis.expire(key, PROGRESS_TTL_SECONDS)
    await expire_result


async def process_product_import(
    ctx: dict[str, Any],
    *,
    import_id: str,
    csv_bytes_b64: str,
    actor_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Worker body — opens session, runs ProductImportService.apply
    with the higher worker-only ``max_rows=10000`` cap.

    The admin-facing inline endpoint (Phase 5) keeps its 500-row cap;
    a route returning 413 ``use_worker`` for >500 rows is Phase 12.
    """
    csv_bytes = base64.b64decode(csv_bytes_b64)
    started = time.monotonic()
    await _set_progress(
        import_id,
        status="running",
        processed=0,
        total=0,
        started_at=int(started),
    )

    async with session_scope() as session:
        actor = await session.get(AdminUser, actor_id)
        if actor is None:
            log.warning("process_product_import_unknown_actor", actor_id=actor_id)
            await _set_progress(import_id, status="failed", error="unknown_actor")
            return {"status": "unknown_actor"}

        svc = ProductImportService(
            products=ProductRepository(session),
            manufacturers=ManufacturerRepository(session),
            categories=CategoryRepository(session),
            ingredients=ActiveIngredientRepository(session),
            symptoms=SymptomRepository(session),
            product_service=_product_service(session),
            max_rows=WORKER_MAX_ROWS,
        )
        try:
            summary = await svc.apply(
                csv_bytes,
                actor=actor,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except Exception as exc:
            await _set_progress(import_id, status="failed", error=str(exc))
            log.warning("process_product_import_failed", import_id=import_id, error=str(exc))
            raise

    duration_s = round(time.monotonic() - started, 3)
    payload = {
        "n_rows": summary.n_rows,
        "n_create": summary.n_create,
        "n_update": summary.n_update,
        "n_skip": summary.n_skip,
    }
    await _set_progress(
        import_id,
        status="done",
        processed=summary.n_rows,
        total=summary.n_rows,
        n_create=summary.n_create,
        n_update=summary.n_update,
        n_skip=summary.n_skip,
        duration_s=str(duration_s),
        errors=[e.model_dump(mode="json") for e in summary.errors],
    )
    log.info(
        "process_product_import_done",
        import_id=import_id,
        duration_s=duration_s,
        **payload,
    )
    return {"status": "done", **payload}


def _product_service(session: Any) -> ProductService:
    return ProductService(
        products=ProductRepository(session),
        manufacturers=ManufacturerRepository(session),
        categories=CategoryRepository(session),
        ingredients=ActiveIngredientRepository(session),
        symptoms=SymptomRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
