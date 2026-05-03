"""Payment client factory — provider switch with module-level cache."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.integrations.payments.base import PaymentClient
from app.integrations.payments.fake import FakePaymentClient

_cached_client: PaymentClient | None = None


def get_payment_client(settings: Settings | None = None) -> PaymentClient:
    """Return the active payment client, lazily constructed + cached.

    Pass ``settings`` to force a fresh instance (tests that flip the
    provider mid-run).
    """
    global _cached_client  # noqa: PLW0603
    if _cached_client is not None and settings is None:
        return _cached_client
    s = settings or get_settings()
    if s.payment_provider == "freedom_pay":
        from app.integrations.payments.freedom_pay import FreedomPayClient

        client: PaymentClient = FreedomPayClient(s)
    else:
        client = FakePaymentClient()
    if settings is None:
        _cached_client = client
    return client


def set_payment_client(client: PaymentClient | None) -> None:
    """Override the cached client. Tests use this to inject a fresh fake."""
    global _cached_client  # noqa: PLW0603
    _cached_client = client
