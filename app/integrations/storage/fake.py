"""Local-disk fake storage client for tests + dev.

Writes objects under a configurable base directory (defaults to
``<tempdir>/r2-fake``). Returns ``file://`` URLs that tests can read
back to verify upload contents. Records every operation in
:attr:`uploads` / :attr:`deletes` for assertions.

This is also the default client when ``storage_endpoint`` is unset —
so dev doesn't need real R2 creds to run the catalog admin flow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)


class FakeStorageClient:
    """Writes to local disk; returns ``file://`` URLs."""

    provider: str = "fake"

    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(tempfile.gettempdir()) / "r2-fake").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.uploads: list[tuple[str, int, str]] = []  # (key, size, content_type)
        self.deletes: list[str] = []

    async def upload(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.uploads.append((key, len(data), content_type))
        log.info("storage_upload_fake", key=key, size=len(data), content_type=content_type)
        return path.as_uri()

    async def delete(self, *, key: str) -> None:
        path = self.base_dir / key
        if path.exists():
            path.unlink()
        self.deletes.append(key)

    async def sign_url(self, *, key: str, ttl_seconds: int) -> str:
        # No real signing — just a deterministic marker URL the caller
        # can recognise. ``ttl_seconds`` is included for parity with the
        # real client's signature.
        return (self.base_dir / key).as_uri() + f"?ttl={ttl_seconds}"

    def reset(self) -> None:
        self.uploads.clear()
        self.deletes.clear()
