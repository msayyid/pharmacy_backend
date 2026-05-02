"""Cross-cutting HTTP middleware.

* :class:`RequestIdMiddleware` — accepts or generates ``X-Request-ID``, binds
  it to the per-request log context, and echoes it on the response.
* :class:`AccessLogMiddleware` — emits one ``http_request`` log per response
  with status and duration in milliseconds.

Reference: BACKEND_BLUEPRINT.md §16.1.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_context, clear_context, get_logger

log = get_logger(__name__)

REQUEST_ID_HEADER = "x-request-id"

_RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Bind a request-id to every log line and echo it on the response."""

    async def dispatch(
        self,
        request: Request,
        call_next: _RequestResponseEndpoint,
    ) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        bind_context(
            request_id=rid,
            path=request.url.path,
            method=request.method,
        )
        try:
            response = await call_next(request)
        finally:
            clear_context()
        response.headers[REQUEST_ID_HEADER] = rid
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One ``http_request`` log per response: status and duration_ms."""

    async def dispatch(
        self,
        request: Request,
        call_next: _RequestResponseEndpoint,
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        log.info(
            "http_request",
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response
