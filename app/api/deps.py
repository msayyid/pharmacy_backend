"""FastAPI dependencies (DI graph).

Phase 1 stub. Phase 2+ adds:

* ``DbSession`` (``Annotated[AsyncSession, Depends(get_db)]``)
* ``SettingsDep``
* Repository / service factory functions
* ``LangDep`` (Accept-Language resolution)
* ``CurrentUser`` / ``CurrentAdmin`` (Phase 4)
* ``get_arq_pool`` (Phase 11)

Reference: BACKEND_BLUEPRINT.md §13.2.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from app.core.config import Settings, get_settings
from app.core.i18n import resolve_language

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_lang(
    settings: SettingsDep,
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve the request language from Accept-Language."""
    return resolve_language(accept_language, settings)


LangDep = Annotated[str, Depends(get_lang)]
