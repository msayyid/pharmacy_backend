"""Nikita SMSPRO real adapter — SCAFFOLD ONLY.

The send-XML body, signature/auth shape, status-code map, and phone-format
rules are **not yet vendor-verified** (see OPEN_QUESTIONS Q13). The
adapter compiles, type-checks, and is wired through the factory, but
:meth:`NikitaSmsClient.send` raises ``NotImplementedError`` so it cannot
silently ship a fabricated request.

When vendor docs are obtained:

1. Confirm the request envelope (XML vs JSON), endpoint URL, and field
   names against current Nikita SMSPRO docs.
2. Reshape :class:`Settings` if needed (the adapter's research notes
   suggest ``sms_login`` + ``sms_password`` rather than a single
   ``sms_api_key`` — verify).
3. Implement :meth:`send` with httpx + tenacity (retry only on 5xx /
   network; never on auth/validation 4xx).
4. Add a unit test against a captured request fixture (``respx``).
5. Drop the ``NotImplementedError``; close OPEN_QUESTIONS Q13.

Reference: PRODUCT §14, §21.3; BACKEND §10.
"""

from __future__ import annotations

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.integrations.sms.base import SendResult

log = get_logger(__name__)


_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class NikitaSmsError(AppError):
    """Base for Nikita-specific failures (auth, balance, sender, etc.)."""

    code = "sms_provider_error"
    status_code = 502


class NikitaSmsClient:
    """Real Nikita SMSPRO client — body raises NotImplementedError pending vendor docs."""

    provider: str = "nikita"

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        if settings.sms_api_url is None:
            raise NikitaSmsError(
                code="sms_provider_misconfigured",
                detail="settings.sms_api_url is required for the Nikita provider",
            )
        self._settings = settings
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._endpoint = str(settings.sms_api_url).rstrip("/")
        self._sender = settings.sms_sender

    async def send(self, *, phone: str, body: str) -> SendResult:
        """Deliver one SMS via Nikita SMSPRO.

        SCAFFOLD: pending vendor-doc verification (OPEN_QUESTIONS Q13).
        The retry wrapper, request shape, and signature/auth body must
        match the current Nikita contract before this can be called.
        """
        # The retry wrapper is wired so the eventual implementation
        # inherits jittered backoff for free.
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.3, jitter=0.5, max=5.0),
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        ):
            with attempt:
                raise NotImplementedError(
                    "NikitaSmsClient.send is unverified scaffold — see "
                    "OPEN_QUESTIONS Q13. Use sms_provider='fake' until the "
                    "Nikita SMSPRO contract is vendor-verified."
                )
        raise AssertionError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        await self._http.aclose()
