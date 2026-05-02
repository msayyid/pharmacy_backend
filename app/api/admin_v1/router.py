"""Admin API — ``/api/admin/v1`` namespace.

Sub-routers: auth (Phase 4). Phase 5+ adds products, inventory; Phase 9+
adds orders, reports, users, team, audit.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.admin_v1 import auth

router = APIRouter(prefix="/api/admin/v1")
router.include_router(auth.router)
