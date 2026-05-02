"""Settings unit tests."""

from __future__ import annotations

import pytest


def test_settings_load_from_env_test() -> None:
    from app.core.config import get_settings

    s = get_settings()
    assert s.env == "test"
    assert s.app_name == "pharmacy-api-test"
    assert s.default_language == "ru"
    assert s.supported_languages == ("ru", "ky", "en")
    assert s.api_v1_prefix == "/api/v1"
    assert s.admin_v1_prefix == "/api/admin/v1"


def test_secret_fields_do_not_leak_in_repr() -> None:
    from app.core.config import get_settings

    s = get_settings()
    repr_str = repr(s)
    # SecretStr never renders the underlying value in repr / str / model_dump.
    assert "test-jwt-secret-not-for-production-use" not in repr_str
    assert "test-pepper-not-for-production-use" not in repr_str
    # Pydantic v2 SecretStr renders as "**********" or similar
    assert "**" in repr_str or "SecretStr" in repr_str


def test_supported_languages_parses_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """SUPPORTED_LANGUAGES=ru,en should parse to a 2-tuple."""
    from app.core.config import Settings

    monkeypatch.setenv("SUPPORTED_LANGUAGES", "ru,en")
    s = Settings()  # type: ignore[call-arg]
    assert s.supported_languages == ("ru", "en")


def test_cors_origins_parses_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,https://app.pharmacy.kg")
    s = Settings()  # type: ignore[call-arg]
    assert len(s.cors_origins) == 2
    # AnyHttpUrl is coerced; str(...) gives canonical form
    assert str(s.cors_origins[0]).startswith("http://localhost:3000")
    assert str(s.cors_origins[1]).startswith("https://app.pharmacy.kg")


def test_cors_origins_empty_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "")
    s = Settings()  # type: ignore[call-arg]
    assert s.cors_origins == []
