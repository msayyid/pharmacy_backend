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
from typing import ClassVar

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

    The default CSP is the strictest possible (the API serves JSON only —
    no HTML, no embedded resources). The Swagger UI / ReDoc HTML pages at
    ``/docs`` and ``/redoc`` are exceptions: FastAPI's default Swagger
    template loads JS + CSS from a CDN (cdn.jsdelivr.net) plus inline
    initialiser scripts, so those paths get a relaxed CSP that allows
    those specific sources. ``/openapi.json`` is plain JSON and stays
    under the strict default.
    """

    HSTS_VALUE = "max-age=31536000; includeSubDomains; preload"
    CSP_STRICT = "default-src 'none'; frame-ancestors 'none'"
    # Swagger UI + ReDoc need scripts/styles/fonts/images from the
    # FastAPI default CDN (cdn.jsdelivr.net) plus inline init scripts.
    CSP_DOCS = (
        "default-src 'none'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    DOCS_PATHS: ClassVar[set[str]] = {"/docs", "/docs/", "/redoc", "/redoc/"}

    async def dispatch(
        self,
        request: Request,
        call_next: _RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        if scheme == "https":
            response.headers["Strict-Transport-Security"] = self.HSTS_VALUE
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Docs pages need the CDN; everything else gets the strict policy.
        if request.url.path in self.DOCS_PATHS:
            response.headers["Content-Security-Policy"] = self.CSP_DOCS
            # Don't deny iframe on the docs (admins iframe them sometimes
            # in internal dashboards). Strict everywhere else.
        else:
            response.headers["Content-Security-Policy"] = self.CSP_STRICT
            response.headers["X-Frame-Options"] = "DENY"
        return response
