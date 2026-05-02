"""Admin API — ``/api/admin/v1`` namespace.

Sub-routers:
* ``auth`` (Phase 4)
* ``manufacturers``, ``active_ingredients``, ``categories``, ``symptoms``,
  ``products`` (Phase 5)
* ``inventory`` (Phase 6)
* ``orders``, ``reports``, ``audit`` (Phase 9)
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.admin_v1 import (
    active_ingredients,
    audit,
    auth,
    categories,
    inventory,
    manufacturers,
    orders,
    products,
    reports,
    symptoms,
)

router = APIRouter(prefix="/api/admin/v1")
router.include_router(auth.router)
router.include_router(manufacturers.router)
router.include_router(active_ingredients.router)
router.include_router(categories.router)
router.include_router(symptoms.router)
router.include_router(products.router)
router.include_router(inventory.router)
router.include_router(orders.router)
router.include_router(reports.router)
router.include_router(audit.router)
