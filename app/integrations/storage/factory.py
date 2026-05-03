"""Storage client factory — provider switch with module-level cache.

Defaults to :class:`FakeStorageClient` when ``storage_endpoint`` is
unset (dev / unit tests don't need real R2 creds).
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.integrations.storage.base import StorageClient
from app.integrations.storage.fake import FakeStorageClient

_cached_client: StorageClient | None = None


def get_storage_client(settings: Settings | None = None) -> StorageClient:
    global _cached_client  # noqa: PLW0603
    if _cached_client is not None and settings is None:
        return _cached_client
    s = settings or get_settings()
    # The selector key is the presence of an endpoint URL — flip back
    # to fake if creds are missing (test/dev safety).
    if s.storage_endpoint is not None and s.storage_bucket is not None:
        from app.integrations.storage.r2 import R2StorageClient

        client: StorageClient = R2StorageClient(s)
    else:
        client = FakeStorageClient()
    if settings is None:
        _cached_client = client
    return client


def set_storage_client(client: StorageClient | None) -> None:
    global _cached_client  # noqa: PLW0603
    _cached_client = client
