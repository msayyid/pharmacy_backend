"""Structured logging via structlog.

Every log line carries ``request_id`` (set by middleware) and is emitted as
JSON. Sensitive structured fields are auto-redacted by name:

* Full redaction (`<redacted>`):
    password, password_hash, code, otp, otp_code, token, access_token,
    refresh_token, jwt, secret, api_key, authorization, cookie.
* Phone masking (``+996****NNNN``):
    phone, recipient_phone, courier_phone, contact_phone.

Phone masking follows PHARMACY_BLUEPRINT §20.4 ("logged with last 4 only").

Reference: BACKEND_BLUEPRINT.md §19; CLAUDE.md "Sacred invariants" §5.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import Settings

# ─── PII redaction ────────────────────────────────────────────────────────────

_FULL_REDACT_FIELDS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "code",
        "otp",
        "otp_code",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "secret",
        "api_key",
        "authorization",
        "cookie",
        "set-cookie",
    }
)

_PHONE_FIELDS: frozenset[str] = frozenset(
    {
        "phone",
        "recipient_phone",
        "courier_phone",
        "contact_phone",
    }
)

# Minimum length to safely keep a 4-char prefix + 4-char suffix.
_MIN_PHONE_MASK_LEN = 8


def mask_phone(value: str) -> str:
    """Mask middle digits of an E.164 phone.

    ``+996700123456`` → ``+996****3456``. Fewer than 8 chars → ``<redacted>``.
    """
    if not isinstance(value, str) or len(value) < _MIN_PHONE_MASK_LEN:
        return "<redacted>"
    return value[:4] + "****" + value[-4:]


def redact_pii(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor: redact PII fields by name."""
    for key in list(event_dict.keys()):
        kl = key.lower()
        if kl in _FULL_REDACT_FIELDS:
            event_dict[key] = "<redacted>"
        elif kl in _PHONE_FIELDS:
            v = event_dict[key]
            event_dict[key] = mask_phone(v) if isinstance(v, str) else "<redacted>"
    return event_dict


# ─── Per-request context ──────────────────────────────────────────────────────

# Default is None (immutable); each .set() call writes a fresh dict, so the
# default is never shared/mutated across tasks.
_log_ctx: ContextVar[dict[str, Any] | None] = ContextVar("log_ctx", default=None)


def bind_context(**kwargs: Any) -> None:
    """Bind fields to the per-request log context.

    Subsequent log calls in this task will include these fields automatically.
    Call from middleware on request entry.
    """
    current = _log_ctx.get() or {}
    _log_ctx.set({**current, **kwargs})


def clear_context() -> None:
    """Clear the per-request log context. Call in middleware ``finally``."""
    _log_ctx.set(None)


def _ctx_processor(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Merge the per-request context into every event."""
    ctx = _log_ctx.get()
    if ctx:
        for key, value in ctx.items():
            event_dict.setdefault(key, value)
    return event_dict


# ─── Configuration ────────────────────────────────────────────────────────────


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the stdlib root logger.

    Idempotent — safe to call multiple times. Invoked from FastAPI lifespan,
    ARQ ``on_startup``, and the test conftest.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _ctx_processor,
        redact_pii,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO,
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)


def get_logger(name: str) -> Any:
    """Return a structlog logger. ``name`` is typically ``__name__``."""
    return structlog.get_logger(name)
