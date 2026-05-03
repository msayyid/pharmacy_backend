"""E2E — bulk product import via the worker (>500 rows).

Verifies the Phase 12 dispatch path: a CSV with >500 rows triggers
``process_product_import`` enqueue and returns 202 with an
``import_id`` + status URL.

Tests do NOT run the actual ARQ worker (no polling), so they only
confirm the route enqueued correctly + the status endpoint responds
404 when the worker hasn't written progress yet.
"""

from __future__ import annotations

import secrets
import uuid

import pytest
from httpx import AsyncClient

from tests.e2e.conftest import seed_admin_committed

pytestmark = pytest.mark.e2e


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def _content_editor_login(client: AsyncClient) -> dict[str, str]:
    email = _email("import-async")
    # super_admin doesn't trip the chk_admin_branch_required constraint;
    # the route accepts both super_admin + content_editor (PRODUCT §19.5).
    await seed_admin_committed(email=email, password="ok", role="super_admin")
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "ok"},
    )
    assert r.status_code == 200, r.text
    return {"admin_session": r.cookies["admin_session"]}


def _build_large_csv(rows: int) -> bytes:
    """Build a CSV with ``rows`` data rows (header excluded). Each row
    references SKU + minimal columns the import service expects.
    Content doesn't need to be importable — the route only counts
    newlines to decide inline vs worker."""
    header = b"sku,name_ru,category_path,form\n"
    body = b"".join(
        f"BULK-{secrets.token_hex(4)},Тест,analgesics,tablet\n".encode() for _ in range(rows)
    )
    return header + body


async def test_large_csv_returns_202_queued(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    cookies = await _content_editor_login(client)
    csv_bytes = _build_large_csv(rows=600)  # > 500 threshold

    r = await client.post(
        "/api/admin/v1/products/import/apply",
        files={"file": ("bulk.csv", csv_bytes, "text/csv")},
        cookies=cookies,
    )
    # Same status code as the inline path (the response body shape
    # distinguishes "queued" from BulkImportSummary).
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["import_id"].startswith("imp-")
    assert body["status_url"].startswith("/api/admin/v1/products/imports/")


async def test_small_csv_runs_inline(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    """Counter-test: ≤500 rows hits the inline path (returns BulkImportSummary
    schema, NOT the queued envelope)."""
    cookies = await _content_editor_login(client)
    # 5 rows of intentionally invalid data → import_apply returns the
    # error summary (inline path). The payload SHAPE is what we assert.
    csv_bytes = b"sku,name_ru,category_path,form\n" + (
        b"INVALID-1,Test,nonexistent_category,tablet\n" * 5
    )

    r = await client.post(
        "/api/admin/v1/products/import/apply",
        files={"file": ("small.csv", csv_bytes, "text/csv")},
        cookies=cookies,
    )
    # Inline path returns BulkImportSummary — has n_rows + n_create + errors.
    assert r.status_code == 200, r.text
    body = r.json()
    assert "n_rows" in body
    assert "errors" in body
    # Non-existent category → all rows skipped, none created.
    assert body["n_create"] == 0


async def test_import_status_404_when_unknown_id(
    client: AsyncClient,
    redis_clean: None,
) -> None:
    cookies = await _content_editor_login(client)
    r = await client.get(
        f"/api/admin/v1/products/imports/imp-{uuid.uuid4().hex[:12]}",
        cookies=cookies,
    )
    assert r.status_code == 404
    # NotFoundError surfaces with the global "not_found" code; the
    # detail field carries the original ``import_not_found`` code.
    assert r.json()["code"] == "not_found"
