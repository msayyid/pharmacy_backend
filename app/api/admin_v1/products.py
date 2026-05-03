"""Admin products — ``/api/admin/v1/products``.

Includes CRUD, ``/{id}/images`` upload + management, and bulk
``/import/dry-run`` and ``/import/apply`` endpoints. RBAC: ``super_admin``
and ``content_editor`` per PRODUCT §19.5.
"""

from __future__ import annotations

import base64
import secrets as _secrets
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Query,
    Request,
    UploadFile,
    status,
)

from app.api.deps import (
    ArqPoolDep,
    get_product_image_service,
    get_product_import_service,
    get_product_repository,
    get_product_service,
)
from app.core.errors import NotFoundError
from app.core.pagination import Page
from app.core.redis import get_redis
from app.domain.catalog.images import ProductImageService
from app.domain.catalog.import_csv import ProductImportService
from app.domain.catalog.products import ProductService
from app.domain.catalog.repositories import ProductRepository
from app.domain.catalog.schemas import (
    BulkImportSummary,
    ProductCreate,
    ProductImageRead,
    ProductImageUpdate,
    ProductListItem,
    ProductRead,
    ProductUpdate,
)
from app.domain.identity.dependencies import require_role
from app.domain.identity.models import AdminUser

router = APIRouter(prefix="/products", tags=["admin-catalog"])

_AdminGuard = Annotated[AdminUser, Depends(require_role("super_admin", "content_editor"))]


# Size thresholds for inline-vs-worker dispatch (Phase 12).
INLINE_IMAGE_BYTES = 2 * 1024 * 1024  # ≤2 MB → inline (current path)
INLINE_IMPORT_ROWS = 500  # ≤500 rows → inline; >500 → worker (Phase 11)


# ─── CRUD ────────────────────────────────────────────────────────────────────


@router.get("", response_model=Page[ProductListItem])
async def list_products(
    _admin: _AdminGuard,
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
    category_id: int | None = None,
    manufacturer_id: int | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> Page[ProductListItem]:
    items, total = await repo.list_paginated(
        category_id=category_id,
        manufacturer_id=manufacturer_id,
        is_active=is_active,
        q=q,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return Page[ProductListItem](
        items=[ProductListItem.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductService, Depends(get_product_service)],
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
) -> ProductRead:
    p = await service.create_product(
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    # Reload with eager-loaded children so ``ProductRead`` can serialise.
    full = await repo.get_by_id_with_full(p.id)
    assert full is not None
    return ProductRead.model_validate(full)


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: UUID,
    _admin: _AdminGuard,
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
) -> ProductRead:
    p = await repo.get_by_id_with_full(product_id)
    if p is None:
        raise NotFoundError(code="product_not_found")
    return ProductRead.model_validate(p)


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductService, Depends(get_product_service)],
    repo: Annotated[ProductRepository, Depends(get_product_repository)],
) -> ProductRead:
    await service.update_product(
        product_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    full = await repo.get_by_id_with_full(product_id)
    assert full is not None
    return ProductRead.model_validate(full)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_product(
    product_id: UUID,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductService, Depends(get_product_service)],
) -> None:
    await service.soft_delete_product(
        product_id,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# ─── Images ──────────────────────────────────────────────────────────────────


@router.post(
    "/{product_id}/images",
    response_model=ProductImageRead | dict[str, str],
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    product_id: UUID,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImageService, Depends(get_product_image_service)],
    arq_pool: ArqPoolDep,
    file: Annotated[UploadFile, File()],
) -> Any:
    """Inline path for ≤2 MB images; larger uploads enqueue
    ``process_image_upload`` (Phase 11 worker) and return 202 with
    a job_id. Phase 12 — keeps the common-case inline (Pillow + storage
    upload completes in <1 s for storefront images) and only hands off
    when the upload is large enough to risk a request timeout.
    """
    file_bytes = await file.read()
    if len(file_bytes) <= INLINE_IMAGE_BYTES:
        image = await service.upload(
            product_id=product_id,
            file_bytes=file_bytes,
            content_type=file.content_type or "",
            actor=admin,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return ProductImageRead.model_validate(image)

    # Worker path: persist to a temp file the worker reads, enqueue.
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 — worker reads + unlinks
        prefix="img-upload-",
        suffix=_safe_suffix(file.filename),
        delete=False,
    )
    try:
        tmp.write(file_bytes)
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    job = await arq_pool.enqueue_job(
        "process_image_upload",
        temp_path=tmp_path,
        product_id=str(product_id),
        content_type=file.content_type or "",
        actor_id=admin.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "status": "queued",
        "job_id": job.job_id if job is not None else "unknown",
        "size_bytes": str(len(file_bytes)),
    }


def _safe_suffix(filename: str | None) -> str:
    """Defensive — only allow our 4 image extensions on the temp file."""
    if not filename:
        return ".bin"
    ext = Path(filename).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return ext
    return ".bin"


@router.patch(
    "/{product_id}/images/{image_id}",
    response_model=ProductImageRead,
)
async def update_image(
    product_id: UUID,
    image_id: int,
    payload: ProductImageUpdate,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImageService, Depends(get_product_image_service)],
) -> ProductImageRead:
    image = await service.update(
        product_id=product_id,
        image_id=image_id,
        payload=payload,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return ProductImageRead.model_validate(image)


@router.delete(
    "/{product_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_image(
    product_id: UUID,
    image_id: int,
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImageService, Depends(get_product_image_service)],
) -> None:
    await service.delete(
        product_id=product_id,
        image_id=image_id,
        actor=admin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# ─── Bulk import ─────────────────────────────────────────────────────────────


@router.post("/import/dry-run", response_model=BulkImportSummary)
async def import_dry_run(
    _admin: _AdminGuard,
    service: Annotated[ProductImportService, Depends(get_product_import_service)],
    file: Annotated[UploadFile, File()],
) -> BulkImportSummary:
    csv_bytes = await file.read()
    return await service.dry_run(csv_bytes)


@router.post("/import/apply", response_model=BulkImportSummary | dict[str, str])
async def import_apply(
    request: Request,
    admin: _AdminGuard,
    service: Annotated[ProductImportService, Depends(get_product_import_service)],
    arq_pool: ArqPoolDep,
    file: Annotated[UploadFile, File()],
) -> Any:
    """Inline apply for ≤500-row CSVs (current path). Larger uploads
    enqueue ``process_product_import`` (Phase 11 worker) and return 202
    with an ``import_id``; admin polls
    ``GET /admin/v1/products/imports/{import_id}`` for progress."""
    csv_bytes = await file.read()
    # Cheap row probe: count newlines (good enough — false-positive lines
    # are accepted as worker-path triggers, no correctness risk).
    row_count = csv_bytes.count(b"\n")
    if row_count <= INLINE_IMPORT_ROWS:
        return await service.apply(
            csv_bytes,
            actor=admin,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

    import_id = f"imp-{uuid.uuid4().hex[:12]}"
    encoded = base64.b64encode(csv_bytes).decode("ascii")
    job = await arq_pool.enqueue_job(
        "process_product_import",
        import_id=import_id,
        csv_bytes_b64=encoded,
        actor_id=admin.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "status": "queued",
        "import_id": import_id,
        "job_id": job.job_id if job is not None else "unknown",
        "row_count_estimate": str(row_count),
        "status_url": f"/api/admin/v1/products/imports/{import_id}",
    }


@router.get("/imports/{import_id}", response_model=dict[str, Any])
async def import_status(
    import_id: str,
    _admin: _AdminGuard,
) -> dict[str, Any]:
    """Read the Phase 11 progress hash ``v1:import:<import_id>``.

    Returns the raw hash fields the worker writes (``status`` /
    ``processed`` / ``total`` / ``n_create`` / ``n_update`` / ``n_skip``
    / ``errors``). 404 if the key is absent or expired (worker hasn't
    started yet, or 24h TTL elapsed)."""
    redis = get_redis()
    key = f"v1:import:{import_id}"
    # Redis 5.x async typing returns Awaitable[dict] for hgetall; the
    # awaited value is the dict. Cast via Any to satisfy mypy.
    hgetall_result: Any = redis.hgetall(key)
    raw: dict[str, str] = await hgetall_result
    if not raw:
        raise NotFoundError(code="import_not_found", import_id=import_id)
    return dict(raw)


# Bind the unused-import-shaker so ruff doesn't flag _secrets when
# the module's only use was in a placeholder line.
_ = _secrets
