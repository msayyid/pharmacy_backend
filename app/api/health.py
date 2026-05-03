"""Liveness, readiness, and Prometheus metrics endpoints.

* ``GET /health`` — liveness. Returns immediately, no I/O. Used by the
  Docker healthcheck and uptime monitors.
* ``GET /health/ready`` — readiness. Pings DB (``SELECT 1``) and Redis
  (``PING``); 503 on either failure with a structured body. Used by the
  load balancer for traffic routing.
* ``GET /metrics`` — Prometheus exposition. Bearer-token guarded via
  ``settings.metrics_token`` — when unset, returns 401 (lock-by-default).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import Response
from prometheus_client import generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.api.deps import DbSession, RedisDep, SettingsDep
from app.core.metrics import REGISTRY

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str = "ok"
    version: str


class ReadyOut(BaseModel):
    status: str
    db: str
    redis: str
    version: str


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok", version=__version__)


@router.get("/health/ready", response_model=ReadyOut)
async def health_ready(session: DbSession, redis: RedisDep) -> ReadyOut:
    """Probe DB + Redis. 503 on either failure.

    Both probes are wrapped individually so the response body indicates
    *which* dependency failed — the LB only cares about the status code,
    but the body helps oncall.
    """
    db_state = "ok"
    redis_state = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_state = f"error: {exc.__class__.__name__}"
    try:
        await redis.ping()
    except Exception as exc:
        redis_state = f"error: {exc.__class__.__name__}"

    if db_state != "ok" or redis_state != "ok":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "db": db_state,
                "redis": redis_state,
                "version": __version__,
            },
        )
    return ReadyOut(status="ok", db=db_state, redis=redis_state, version=__version__)


def _require_metrics_token(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token guard — 401 if no token configured (lock-by-default)
    or if the supplied token doesn't match.
    """
    expected = (
        settings.metrics_token.get_secret_value() if settings.metrics_token is not None else None
    )
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="metrics endpoint disabled (no METRICS_TOKEN configured)",
        )
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


@router.get(
    "/metrics",
    response_class=Response,
    dependencies=[Depends(_require_metrics_token)],
    include_in_schema=False,
)
async def metrics() -> Response:
    """Prometheus exposition. Serves the module-local registry (NOT the
    process-global one — keeps third-party library counters out)."""
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
