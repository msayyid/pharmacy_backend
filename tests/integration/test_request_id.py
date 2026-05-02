"""Request-ID middleware integration tests."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_supplied_request_id_round_trips(client: AsyncClient) -> None:
    rid = "test-rid-abc-123"
    r = await client.get("/health", headers={"X-Request-ID": rid})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == rid


async def test_request_id_generated_when_absent(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    rid = r.headers["x-request-id"]
    # Server-generated should be a valid UUID4
    parsed = uuid.UUID(rid)
    assert str(parsed) == rid


async def test_each_request_gets_unique_id(client: AsyncClient) -> None:
    r1 = await client.get("/health")
    r2 = await client.get("/health")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
