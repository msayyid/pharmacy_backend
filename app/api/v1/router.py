"""Customer API — ``/api/v1`` namespace.

Sub-routers (Phase 4+): auth, account. Phase 5+ adds catalog, search;
Phase 8+ adds cart, checkout, orders.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import account, auth

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(account.router)
