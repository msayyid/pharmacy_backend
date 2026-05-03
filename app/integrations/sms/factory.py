"""SMS client factory — provider switch.

Returns a :class:`SmsClient` implementation chosen by
``settings.sms_provider``. The factory caches a single instance per
process; tests can override via :func:`set_sms_client`.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.integrations.sms.base import SmsClient
from app.integrations.sms.fake import FakeSmsClient

_cached_client: SmsClient | None = None


def get_sms_client(settings: Settings | None = None) -> SmsClient:
    """Return the active SMS client.

    Construction is lazy + cached. Pass ``settings`` to force a fresh
    instance (used by tests that flip the provider mid-run).
    """
    global _cached_client  # noqa: PLW0603
    if _cached_client is not None and settings is None:
        return _cached_client
    s = settings or get_settings()
    if s.sms_provider == "nikita":
        from app.integrations.sms.nikita import NikitaSmsClient

        client: SmsClient = NikitaSmsClient(s)
    else:
        client = FakeSmsClient()
    if settings is None:
        _cached_client = client
    return client


def set_sms_client(client: SmsClient | None) -> None:
    """Override the cached SMS client. Tests use this to inject a fresh fake."""
    global _cached_client  # noqa: PLW0603
    _cached_client = client
