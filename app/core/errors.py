"""Application error hierarchy.

Every domain error subclasses ``AppError``. Routers do **not** catch these —
the global exception handlers in ``app.api.errors`` translate them into RFC
7807 Problem Details responses.

Reference: BACKEND_BLUEPRINT.md §15.1.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base for every application error."""

    code: str = "internal_error"
    status_code: int = 500
    message: str = "Internal error"

    def __init__(self, message: str | None = None, **context: Any) -> None:
        super().__init__(message or self.message)
        self.context: dict[str, Any] = context


class ValidationError(AppError):
    code = "validation_error"
    status_code = 400
    message = "Invalid input"


class AuthenticationError(AppError):
    code = "unauthorized"
    status_code = 401
    message = "Authentication required"


class PermissionDeniedError(AppError):
    code = "forbidden"
    status_code = 403
    message = "Permission denied"


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "Resource not found"


class ConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "Conflict"


class RateLimitExceededError(AppError):
    code = "rate_limited"
    status_code = 429
    message = "Too many requests"


# ─── Domain-specific subclasses ──────────────────────────────────────────────


class OutOfStockError(ConflictError):
    code = "out_of_stock"


class InvalidOTPError(AuthenticationError):
    code = "invalid_otp"


class IdempotencyConflictError(ConflictError):
    code = "idempotency_conflict"
