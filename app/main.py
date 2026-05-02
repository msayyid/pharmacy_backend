"""FastAPI application factory and ASGI entry point.

Wires:

* ``/health`` (top-level)
* ``/api/v1`` customer router (empty in Phase 1)
* ``/api/admin/v1`` admin router (empty in Phase 1)
* Exception handlers (RFC 7807)
* ``RequestIdMiddleware`` (outermost — every log gets a request_id)
* ``AccessLogMiddleware``
* ``GZipMiddleware``
* ``CORSMiddleware`` (only when ``settings.cors_origins`` non-empty)

Lifespan configures structlog and Sentry (no-op when DSN absent).

Reference: BACKEND_BLUEPRINT.md §13.3 + §16.5.

Note on middleware ordering: Starlette's ``add_middleware`` *prepends* to the
user middleware list, so the **last** ``add_middleware`` call ends up
**outermost** in the final stack. We call them in reverse-of-desired order:
inner (CORS, GZip) first, outer (AccessLog, RequestId) last. The spec listing
in §16.5 is read top-to-bottom as outermost-to-innermost — this file emits
the corresponding ``add_middleware`` order accordingly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from app import __version__
from app.api.admin_v1.router import router as admin_v1_router
from app.api.errors import register_exception_handlers
from app.api.health import router as health_router
from app.api.middleware import AccessLogMiddleware, RequestIdMiddleware
from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup + shutdown hooks. Idempotent across reloads."""
    settings = get_settings()
    configure_logging(settings)

    # Sentry — dsn=None makes init a no-op (per Sentry SDK contract).
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else None
    sentry_sdk.init(
        dsn=dsn,
        release=f"pharmacy-api@{__version__}",
        environment=settings.env,
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        send_default_pii=False,
    )
    log.info("startup_complete", version=__version__, env=settings.env)
    yield
    log.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Pharmacy API",
        version=__version__,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    # Middleware (Starlette prepends; later add = outermost).
    # Innermost first:
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(o).rstrip("/") for o in settings.cors_origins],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(AccessLogMiddleware)
    # Outermost — every log line gets a request_id:
    app.add_middleware(RequestIdMiddleware)

    # Routers
    app.include_router(health_router)
    app.include_router(v1_router)
    app.include_router(admin_v1_router)

    # Global exception handlers (RFC 7807)
    register_exception_handlers(app)

    return app


app = create_app()
