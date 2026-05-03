"""Storage client Protocol — uniform interface for R2 / fake / future S3.

Three operations:

* :meth:`StorageClient.upload` — put ``data`` at ``key`` with the
  given ``content_type``. Returns the public URL the storefront uses
  to fetch the object (catalog images live in a public bucket served
  via the CDN).
* :meth:`StorageClient.delete` — remove an object. Idempotent: missing
  keys are not an error.
* :meth:`StorageClient.sign_url` — presigned GET URL for private
  objects (admin exports, future use). TTL is in seconds.

Phase 10 ships :class:`FakeStorageClient` (writes to a tmp dir,
returns ``file://`` URLs) and a scaffolded :class:`R2StorageClient`
that constructs a boto3 client correctly but whose ``upload`` raises
``NotImplementedError`` pending vendor-doc verification (R2 quirks
around region naming, ACL, presigned-URL TTL — see OPEN_QUESTIONS Q15).
"""

from __future__ import annotations

from typing import Protocol


class StorageClient(Protocol):
    """The contract every object-storage adapter implements."""

    provider: str

    async def upload(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """Persist ``data``. Return the public URL."""
        ...

    async def delete(self, *, key: str) -> None:
        """Remove an object. Missing keys are not an error."""
        ...

    async def sign_url(self, *, key: str, ttl_seconds: int) -> str:
        """Return a presigned GET URL valid for ``ttl_seconds``."""
        ...
