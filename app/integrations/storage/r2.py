"""Cloudflare R2 real adapter — SCAFFOLD ONLY.

Endpoint URL form, region naming (``"auto"`` vs explicit), ACL
behaviour, presigned-URL TTL ceiling, and public-domain mechanics
are **not yet vendor-verified** (see OPEN_QUESTIONS Q15). The adapter
constructs a boto3 client with plausible defaults but each I/O method
raises ``NotImplementedError`` so we don't ship fabricated behaviour.

When R2 docs are obtained:

1. Confirm boto3 client kwargs (``endpoint_url`` form, ``region_name``).
2. Confirm public-bucket URL pattern (``pub-<hash>.r2.dev`` vs custom
   domain via Cloudflare Workers).
3. Confirm presigned-URL TTL ceiling (S3 max is 7 days; R2 may differ).
4. Confirm whether multipart upload is needed for our largest variant
   (~few MB after Pillow resize — likely below the threshold).
5. Implement each method (boto3 is sync — wrap in
   ``asyncio.to_thread``). Drop ``NotImplementedError``; close
   OPEN_QUESTIONS Q15.

Reference: BACKEND §19 (image pipeline); PRODUCT §13.3.
"""

from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.client import Config

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


class R2StorageError(AppError):
    code = "storage_provider_error"
    status_code = 502


class R2StorageClient:
    """Cloudflare R2 — body raises NotImplementedError pending vendor docs."""

    provider: str = "r2"

    def __init__(self, settings: Settings) -> None:
        if (
            settings.storage_endpoint is None
            or settings.storage_bucket is None
            or settings.storage_access_key is None
            or settings.storage_secret_key is None
        ):
            raise R2StorageError(
                code="storage_provider_misconfigured",
                detail=(
                    "settings.storage_endpoint / storage_bucket / "
                    "storage_access_key / storage_secret_key required"
                ),
            )
        self._settings = settings
        self._bucket = settings.storage_bucket
        self._public_base = (
            str(settings.storage_public_base_url).rstrip("/")
            if settings.storage_public_base_url is not None
            else ""
        )
        # boto3 is synchronous; calls go through asyncio.to_thread.
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=str(settings.storage_endpoint),
            aws_access_key_id=settings.storage_access_key.get_secret_value(),
            aws_secret_access_key=settings.storage_secret_key.get_secret_value(),
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    async def upload(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        """SCAFFOLD — see OPEN_QUESTIONS Q15."""
        raise NotImplementedError(
            "R2StorageClient.upload is unverified scaffold — see OPEN_QUESTIONS "
            "Q15. Use the FakeStorageClient (default when storage_endpoint is "
            "unset) until R2 quirks are vendor-verified."
        )

    async def delete(self, *, key: str) -> None:
        raise NotImplementedError(
            "R2StorageClient.delete is unverified scaffold — see OPEN_QUESTIONS Q15."
        )

    async def sign_url(self, *, key: str, ttl_seconds: int) -> str:
        raise NotImplementedError(
            "R2StorageClient.sign_url is unverified scaffold — see OPEN_QUESTIONS Q15."
        )

    # Reserved for the eventual real implementation: how to wrap a
    # sync boto3 call in an async-friendly call.
    async def _to_thread(self, fn: Any, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        return await asyncio.to_thread(fn, *args, **kwargs)
