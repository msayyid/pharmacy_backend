"""``/health`` endpoint integration tests."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "version": "0.1.0"}


async def test_health_response_has_request_id_header(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert "x-request-id" in r.headers
    assert len(r.headers["x-request-id"]) > 0


async def test_health_content_type_is_json(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.headers["content-type"].startswith("application/json")
