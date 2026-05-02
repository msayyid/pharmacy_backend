"""FastAPI exception handlers — RFC 7807 Problem Details.

Translates :class:`AppError` (and its subclasses), Pydantic
:class:`RequestValidationError`, SQLAlchemy ``IntegrityError``, and any
unhandled :class:`Exception` into a uniform JSON shape::

    {
      "type": "about:blank#<code>",
      "title": "...",
      "status": <int>,
      "code": "<machine-readable>",
      "detail": "...",
      "context": {...}     // optional
    }

Routers must NOT catch these errors — let them propagate.

Reference: BACKEND_BLUEPRINT.md §15.2.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


def _problem(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"about:blank#{code}",
        "title": title,
        "status": status,
        "code": code,
    }
    if detail is not None:
        body["detail"] = detail
    body.update({k: v for k, v in extra.items() if v is not None})
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Register the four global exception handlers."""

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=exc.status_code,
            content=_problem(
                exc.status_code,
                exc.code,
                exc.message,
                detail=str(exc),
                context=exc.context or None,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> ORJSONResponse:
        return ORJSONResponse(
            status_code=422,
            content=_problem(
                422,
                "validation_error",
                "Invalid request",
                errors=exc.errors(),
            ),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_request: Request, exc: IntegrityError) -> ORJSONResponse:
        log.warning("integrity_error", error=str(exc.orig))
        return ORJSONResponse(
            status_code=409,
            content=_problem(409, "conflict", "Data conflict"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, _exc: Exception) -> ORJSONResponse:
        log.exception("unhandled_exception", path=str(request.url.path))
        return ORJSONResponse(
            status_code=500,
            content=_problem(500, "internal_error", "Internal error"),
        )
