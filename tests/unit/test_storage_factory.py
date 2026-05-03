"""Unit tests — storage client factory + FakeStorageClient + R2 scaffold guard."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.integrations.storage.factory import (
    get_storage_client,
    set_storage_client,
)
from app.integrations.storage.fake import FakeStorageClient

pytestmark = pytest.mark.unit


def _settings_with(*, configured: bool) -> Settings:
    """Build a Settings; ``configured=True`` means real-R2-mode."""
    base: dict[str, object] = {
        "environment": "test",
        "secret_key": "x" * 32,
        "password_pepper": "x" * 32,
        "otp_pepper": "x" * 32,
        "mysql_dsn": "mysql+asyncmy://test:test@localhost:3307/pharmacy_test",
        "redis_dsn": "redis://localhost:6379/15",
    }
    if configured:
        base.update(
            storage_endpoint="https://example.r2.cloudflarestorage.com",
            storage_bucket="pharmacy-images",
            storage_access_key="ak" * 8,
            storage_secret_key="sk" * 16,
        )
    return Settings(**base)  # type: ignore[arg-type]


def test_factory_returns_fake_when_endpoint_unset() -> None:
    set_storage_client(None)
    client = get_storage_client(_settings_with(configured=False))
    assert isinstance(client, FakeStorageClient)
    assert client.provider == "fake"


def test_factory_returns_r2_scaffold_when_configured() -> None:
    from app.integrations.storage.r2 import R2StorageClient

    set_storage_client(None)
    client = get_storage_client(_settings_with(configured=True))
    assert isinstance(client, R2StorageClient)
    assert client.provider == "r2"


async def test_fake_upload_writes_disk_returns_url() -> None:
    with tempfile.TemporaryDirectory() as td:
        client = FakeStorageClient(base_dir=Path(td))
        url = await client.upload(
            key="products/abc/large.webp",
            data=b"\x00\x01\x02 fake webp",
            content_type="image/webp",
        )
        assert url.startswith("file://")
        assert (Path(td) / "products/abc/large.webp").read_bytes() == b"\x00\x01\x02 fake webp"
        assert client.uploads == [
            ("products/abc/large.webp", len(b"\x00\x01\x02 fake webp"), "image/webp"),
        ]


async def test_fake_delete_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        client = FakeStorageClient(base_dir=Path(td))
        await client.upload(
            key="x/y.webp",
            data=b"hi",
            content_type="image/webp",
        )
        await client.delete(key="x/y.webp")
        await client.delete(key="x/y.webp")  # no error on second
        assert client.deletes == ["x/y.webp", "x/y.webp"]


async def test_fake_sign_url_returns_uri_with_ttl() -> None:
    with tempfile.TemporaryDirectory() as td:
        client = FakeStorageClient(base_dir=Path(td))
        url = await client.sign_url(key="z.webp", ttl_seconds=600)
        assert url.startswith("file://")
        assert "ttl=600" in url


async def test_r2_scaffold_methods_raise_not_implemented() -> None:
    from app.integrations.storage.r2 import R2StorageClient

    client = R2StorageClient(_settings_with(configured=True))
    with pytest.raises(NotImplementedError, match="OPEN_QUESTIONS Q15"):
        await client.upload(key="x.webp", data=b"a", content_type="image/webp")
    with pytest.raises(NotImplementedError, match="OPEN_QUESTIONS Q15"):
        await client.delete(key="x.webp")
    with pytest.raises(NotImplementedError, match="OPEN_QUESTIONS Q15"):
        await client.sign_url(key="x.webp", ttl_seconds=60)
