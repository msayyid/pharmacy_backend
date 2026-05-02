"""E2E — product image upload, primary toggle, delete.

Uses Pillow to synthesise a small valid PNG in-memory; the service
re-encodes to WebP variants on disk under ``IMAGE_STORAGE_DIR``.
"""

from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

from tests.e2e.conftest import seed_admin_committed
from tests.factories.catalog import (
    seed_category_committed,
    seed_product_committed,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _clean_image_dir() -> None:
    """Per-test reset of the test image directory to avoid stale files."""
    from app.core.config import get_settings

    storage = Path(get_settings().image_storage_dir)
    if storage.exists():
        shutil.rmtree(storage)
    storage.mkdir(parents=True, exist_ok=True)


def _png_bytes(width: int = 64, height: int = 64) -> bytes:
    img = Image.new("RGB", (width, height), color=(123, 200, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def _login_as_admin(client: AsyncClient, *, prefix: str) -> dict[str, str]:
    email = _unique_email(prefix)
    await seed_admin_committed(email=email, password="ok", role="super_admin")
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "ok"},
    )
    assert r.status_code == 200, r.text
    return {"admin_session": r.cookies["admin_session"]}


async def _seed_product(*, prefix: str) -> str:
    cat_id = await seed_category_committed(slug=f"cat-img-{uuid.uuid4().hex[:6]}")
    pid = await seed_product_committed(
        sku=f"{prefix}-{uuid.uuid4().hex[:8]}",
        slug=f"{prefix.lower()}-{uuid.uuid4().hex[:6]}",
        category_id=cat_id,
    )
    return str(pid)


async def test_admin_can_upload_product_image(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_admin(client, prefix="img-up")
    pid = await _seed_product(prefix="IMG-UP")

    r = await client.post(
        f"/api/admin/v1/products/{pid}/images",
        cookies=cookies,
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["url"].endswith("original.webp")
    assert body["thumbnail_url"]
    assert body["is_primary"] is False


async def test_admin_can_promote_image_to_primary(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_admin(client, prefix="img-prim")
    pid = await _seed_product(prefix="IMG-PRIM")

    r1 = await client.post(
        f"/api/admin/v1/products/{pid}/images",
        cookies=cookies,
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/admin/v1/products/{pid}/images",
        cookies=cookies,
        files={"file": ("b.png", _png_bytes(), "image/png")},
    )
    img1_id = r1.json()["id"]
    img2_id = r2.json()["id"]

    # Promote img1
    r3 = await client.patch(
        f"/api/admin/v1/products/{pid}/images/{img1_id}",
        json={"is_primary": True},
        cookies=cookies,
    )
    assert r3.status_code == 200
    assert r3.json()["is_primary"] is True

    # Promote img2 — img1 should clear automatically
    r4 = await client.patch(
        f"/api/admin/v1/products/{pid}/images/{img2_id}",
        json={"is_primary": True},
        cookies=cookies,
    )
    assert r4.status_code == 200
    assert r4.json()["is_primary"] is True

    # Re-fetch product, only one primary
    r5 = await client.get(f"/api/admin/v1/products/{pid}", cookies=cookies)
    primaries = [i for i in r5.json()["images"] if i["is_primary"]]
    assert len(primaries) == 1
    assert primaries[0]["id"] == img2_id


async def test_admin_can_delete_image(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_admin(client, prefix="img-del")
    pid = await _seed_product(prefix="IMG-DEL")

    r = await client.post(
        f"/api/admin/v1/products/{pid}/images",
        cookies=cookies,
        files={"file": ("p.png", _png_bytes(), "image/png")},
    )
    img_id = r.json()["id"]

    r2 = await client.delete(f"/api/admin/v1/products/{pid}/images/{img_id}", cookies=cookies)
    assert r2.status_code == 204

    r3 = await client.get(f"/api/admin/v1/products/{pid}", cookies=cookies)
    assert all(i["id"] != img_id for i in r3.json()["images"])


async def test_invalid_content_type_rejected(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_as_admin(client, prefix="img-bad")
    pid = await _seed_product(prefix="IMG-BAD")

    r = await client.post(
        f"/api/admin/v1/products/{pid}/images",
        cookies=cookies,
        files={"file": ("evil.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 400
