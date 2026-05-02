"""Async database engine + session factory.

Phase 1 placeholder. Phase 2 lands:

* ``engine`` (``create_async_engine``) wired to ``settings.mysql_dsn``
* ``SessionLocal`` (``async_sessionmaker``) with ``expire_on_commit=False``
* ``get_db`` FastAPI dependency (one session per request, commit/rollback on exit)
* ``session_scope`` async-context-manager for workers and scripts

Reference: BACKEND_BLUEPRINT.md §7.
"""

from __future__ import annotations

# Intentionally empty in Phase 1.
