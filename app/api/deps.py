"""FastAPI dependencies (DI graph).

* :data:`SettingsDep` — settings injected per request.
* :data:`LangDep` — language resolved from ``Accept-Language``.
* :data:`RedisDep` — Redis client (initialised in lifespan).

Phase 4+ will add ``DbSession``, ``CurrentUser``, ``CurrentAdmin``,
repository / service factories, ``get_arq_pool``.

Reference: BACKEND_BLUEPRINT.md §13.2.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.i18n import resolve_language
from app.core.redis import get_redis

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_lang(
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve the request language from ``Accept-Language``."""
    return resolve_language(accept_language)


LangDep = Annotated[str, Depends(get_lang)]


def get_redis_dep() -> Redis:
    """FastAPI dependency wrapping the module-level Redis client."""
    return get_redis()


RedisDep = Annotated[Redis, Depends(get_redis_dep)]
