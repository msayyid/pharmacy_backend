"""Admin API — ``/api/admin/v1`` namespace.

Sub-routers:
* ``auth`` (Phase 4)
* ``manufacturers``, ``active_ingredients``, ``categories``, ``symptoms``,
  ``products`` (Phase 5)

Phase 6+ adds inventory; Phase 9+ adds orders, reports, users, team, audit.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.admin_v1 import (
    active_ingredients,
    auth,
    categories,
    manufacturers,
    products,
    symptoms,
)

router = APIRouter(prefix="/api/admin/v1")
router.include_router(auth.router)
router.include_router(manufacturers.router)
router.include_router(active_ingredients.router)
router.include_router(categories.router)
router.include_router(symptoms.router)
router.include_router(products.router)
