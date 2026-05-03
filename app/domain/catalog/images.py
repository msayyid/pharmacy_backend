"""Product image service — multipart upload + sync Pillow resize.

Phase 5 ships the synchronous-fallback path: open with Pillow, generate
WebP variants (thumbnail 200, medium 600, large 1200, plus original
capped at 2400 px), persist a ``ProductImage`` row.

Phase 10 swaps the disk-write path for an injected
:class:`StorageClient` (R2 in prod, fake-on-disk in dev/test). Phase
11 will replace the inline resize with an ARQ worker that calls the
same :func:`process_image` helper.

The "one primary image per product" UNIQUE is enforced at the DB layer
via the ``primary_product_id`` generated column (BACKEND §6.5). When
flipping ``is_primary=True`` on a non-primary image we clear other
primaries for the same product first to satisfy the constraint.

Reference: PRODUCT §13.3, BACKEND §10, CLAUDE_CODE_PROMPTS Phase 5/10.
"""

from __future__ import annotations

import io
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.domain.catalog.models import ProductImage
from app.domain.catalog.repositories import ProductRepository
from app.domain.catalog.schemas import ProductImageUpdate
from app.domain.identity.models import AdminUser
from app.domain.ops.services import AdminAuditLogService
from app.integrations.storage.base import StorageClient

ALLOWED_IMAGE_MIMES: frozenset[str] = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)

# Max edge in pixels for the 'original' variant (cap absurd uploads).
_ORIGINAL_MAX_EDGE = 2400

# Variant name → max edge in pixels.
_VARIANTS: dict[str, int] = {
    "thumbnail": 200,
    "medium": 600,
    "large": 1200,
}


def process_image(image_bytes: bytes) -> tuple[dict[str, bytes], int, int]:
    """Decode, strip EXIF, generate WebP variants. Returns ``(variants, w, h)``.

    Raises :class:`ValidationError` if the input isn't a recognisable image.
    Phase 11's ARQ worker will call this same function.
    """
    try:
        opened = Image.open(io.BytesIO(image_bytes))
        opened.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValidationError(code="image_invalid") from e

    width, height = opened.size
    img: Image.Image = opened.convert("RGB") if opened.mode != "RGB" else opened
    # Strip EXIF by re-pasting onto a blank canvas of the same size.
    no_exif = Image.new("RGB", img.size)
    no_exif.paste(img)

    out: dict[str, bytes] = {}

    # Original (capped)
    orig = no_exif.copy()
    orig.thumbnail((_ORIGINAL_MAX_EDGE, _ORIGINAL_MAX_EDGE))
    buf = io.BytesIO()
    orig.save(buf, "WEBP", quality=92, method=6)
    out["original"] = buf.getvalue()

    # Variants
    for name, max_edge in _VARIANTS.items():
        v = no_exif.copy()
        v.thumbnail((max_edge, max_edge))
        buf = io.BytesIO()
        v.save(buf, "WEBP", quality=85, method=6)
        out[name] = buf.getvalue()

    return (out, width, height)


def _image_snapshot(img: ProductImage) -> dict[str, Any]:
    return {
        "id": img.id,
        "product_id": str(img.product_id),
        "url": img.url,
        "is_primary": img.is_primary,
        "sort_order": img.sort_order,
    }


class ProductImageService:
    """Multipart upload, primary-toggle, delete."""

    def __init__(
        self,
        *,
        products: ProductRepository,
        audit: AdminAuditLogService,
        storage_dir: Path,
        public_base_url: str,
        max_bytes: int,
        storage: StorageClient | None = None,
    ) -> None:
        self.products = products
        self.audit = audit
        self.storage_dir = storage_dir
        self.public_base_url = public_base_url.rstrip("/")
        self.max_bytes = max_bytes
        self.storage = storage

    async def _get_image_for_product(self, product_id: UUID, image_id: int) -> ProductImage | None:
        stmt = select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id == product_id,
        )
        return (await self.products.session.execute(stmt)).scalar_one_or_none()

    async def upload(
        self,
        *,
        product_id: UUID,
        file_bytes: bytes,
        content_type: str,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ProductImage:
        # ─── Validation ─────────────────────────────────────────────────────
        product = await self.products.get_by_id(product_id)
        if product is None:
            raise NotFoundError(code="product_not_found")
        if content_type not in ALLOWED_IMAGE_MIMES:
            raise ValidationError(code="invalid_content_type", content_type=content_type)
        if len(file_bytes) > self.max_bytes:
            raise ValidationError(
                code="image_too_large",
                size=len(file_bytes),
                max_bytes=self.max_bytes,
            )

        # ─── Process ────────────────────────────────────────────────────────
        variants, width, height = process_image(file_bytes)

        # ─── Save ───────────────────────────────────────────────────────────
        storage_key = secrets.token_hex(8)
        urls: dict[str, str] = {}
        if self.storage is not None:
            # Phase 10 path: hand bytes to the StorageClient (R2 in
            # prod, fake-on-disk in dev/test). The client's return URL
            # is what we persist; ``public_base_url`` is unused.
            for variant_name, data in variants.items():
                key = f"products/{product_id}/{storage_key}/{variant_name}.webp"
                urls[variant_name] = await self.storage.upload(
                    key=key,
                    data=data,
                    content_type="image/webp",
                )
        else:
            # Phase 5 fallback (still here so existing tests that
            # don't pass a storage client keep working).
            base_dir = self.storage_dir / "products" / str(product_id) / storage_key
            base_dir.mkdir(parents=True, exist_ok=True)
            for variant_name, data in variants.items():
                path = base_dir / f"{variant_name}.webp"
                path.write_bytes(data)
                urls[variant_name] = (
                    f"{self.public_base_url}/products/{product_id}/{storage_key}/"
                    f"{variant_name}.webp"
                )

        record = ProductImage(
            product_id=product_id,
            url=urls["original"],
            thumbnail_url=urls["thumbnail"],
            medium_url=urls["medium"],
            large_url=urls["large"],
            width=width,
            height=height,
            sort_order=0,
            is_primary=False,
        )
        self.products.session.add(record)
        await self.products.session.flush()
        await self.products.session.refresh(record)

        await self.audit.record(
            admin_user_id=actor.id,
            action="create",
            entity_type="product_image",
            entity_id=record.id,
            after=_image_snapshot(record),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return record

    async def update(
        self,
        *,
        product_id: UUID,
        image_id: int,
        payload: ProductImageUpdate,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ProductImage:
        record = await self._get_image_for_product(product_id, image_id)
        if record is None:
            raise NotFoundError(code="product_image_not_found")
        before = _image_snapshot(record)

        # ``is_primary=True``: clear other primaries first to honour the
        # generated-column UNIQUE constraint.
        if payload.is_primary is True and not record.is_primary:
            stmt = (
                update(ProductImage)
                .where(
                    ProductImage.product_id == product_id,
                    ProductImage.id != image_id,
                    ProductImage.is_primary.is_(True),
                )
                .values(is_primary=False)
            )
            await self.products.session.execute(stmt)
            await self.products.session.flush()
            record.is_primary = True
        elif payload.is_primary is False:
            record.is_primary = False

        if payload.sort_order is not None:
            record.sort_order = payload.sort_order
        if payload.alt_text is not None:
            record.alt_text = payload.alt_text

        await self.products.session.flush()
        await self.products.session.refresh(record)

        await self.audit.record(
            admin_user_id=actor.id,
            action="update",
            entity_type="product_image",
            entity_id=record.id,
            before=before,
            after=_image_snapshot(record),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return record

    async def delete(
        self,
        *,
        product_id: UUID,
        image_id: int,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        record = await self._get_image_for_product(product_id, image_id)
        if record is None:
            raise NotFoundError(code="product_image_not_found")
        before = _image_snapshot(record)
        # Disk files are not removed in Phase 5 — orphan cleanup is a
        # Phase 11 worker job (and trivially fixed when R2 lands).
        await self.products.session.delete(record)
        await self.products.session.flush()
        await self.audit.record(
            admin_user_id=actor.id,
            action="delete",
            entity_type="product_image",
            entity_id=image_id,
            before=before,
            ip_address=ip_address,
            user_agent=user_agent,
        )


__all__ = [
    "ALLOWED_IMAGE_MIMES",
    "ProductImageService",
    "process_image",
]


# Suppress unused-warnings for ConflictError import (intentional re-export
# for future use in this module if "duplicate primary" needs a typed error).
_ = ConflictError
