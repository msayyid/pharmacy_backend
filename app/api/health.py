"""Liveness check.

``GET /health`` is used by the Docker healthcheck, uptime monitors, and load
balancers. Returns immediately and does **not** touch the database or Redis —
those are Phase 2 / Phase 3 readiness probes.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str = "ok"
    version: str


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok", version=__version__)
