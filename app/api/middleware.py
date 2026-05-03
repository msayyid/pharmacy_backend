"""Cross-cutting HTTP middleware.

* :class:`RequestIdMiddleware` — accepts or generates ``X-Request-ID``, binds
  it to the per-request log context, and echoes it on the response.
* :class:`AccessLogMiddleware` — emits one ``http_request`` log per response
  with status and duration in milliseconds.
* :class:`MetricsMiddleware` — records ``pharmacy_http_requests_total`` +
  ``pharmacy_http_request_duration_seconds`` per request (Phase 12).
* :class:`SecurityHeadersMiddleware` — injects HSTS, XFO, CSP, etc.
  (Phase 12).

Reference: BACKEND_BLUEPRINT.md §16.1, §20, §21.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_context, clear_context, get_logger
from app.core.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)

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


def _route_template(request: Request) -> str:
    """Resolve the FastAPI route template (e.g. ``/api/v1/products/{slug}``)
    so metric cardinality stays bounded — labelling on raw ``request.url.path``
    explodes the label set on path-parameterised routes."""
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        return str(route.path)
    return request.url.path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record HTTP request counter + latency histogram per response."""

    async def dispatch(
        self,
        request: Request,
        call_next: _RequestResponseEndpoint,
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_s = time.perf_counter() - started
        # Skip /metrics itself (avoid recursive label growth) and
        # health probes (high-volume noise).
        path = request.url.path
        if path in {"/metrics", "/health", "/health/ready"}:
            return response
        route = _route_template(request)
        method = request.method
        HTTP_REQUESTS_TOTAL.labels(
            route=route, method=method, status=str(response.status_code)
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(route=route, method=method).observe(duration_s)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject HSTS / XFO / CSP / referrer-policy / nosniff on every response.

    HSTS only emits when the request reached us over HTTPS — set via
    ``X-Forwarded-Proto: https`` from the trusted reverse proxy or via the
    ASGI scope's ``scheme``. Behind plain HTTP (dev) we don't claim HSTS.
    """

    HSTS_VALUE = "max-age=31536000; includeSubDomains; preload"
    # API serves JSON only — no HTML, no embedded resources, so the strictest
    # policy is the right one. ``frame-ancestors 'none'`` blocks clickjacking.
    CSP_VALUE = "default-src 'none'; frame-ancestors 'none'"

    async def dispatch(
        self,
        request: Request,
        call_next: _RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        if scheme == "https":
            response.headers["Strict-Transport-Security"] = self.HSTS_VALUE
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = self.CSP_VALUE
        return response
