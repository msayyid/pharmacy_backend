"""ARQ worker entrypoint marker.

Run via ``arq app.workers.settings.WorkerSettings`` (or ``make worker``).
This module re-exports :class:`WorkerSettings` for convenience and exists
because :file:`BACKEND_BLUEPRINT.md §3` mandates the file under ``app/``.
"""

from __future__ import annotations

from app.workers.settings import WorkerSettings

__all__ = ["WorkerSettings"]
