"""i18n loader, t(), fallback chain, missing-key behaviour."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.i18n import clear_translation_cache, resolve_language, t


@pytest.fixture(autouse=True)
def _clear_translation_cache() -> Iterator[None]:
    """Reset the in-memory cache between tests so file changes are visible."""
    clear_translation_cache()
    yield
    clear_translation_cache()


# ─── resolve_language ─────────────────────────────────────────────────────────


def test_resolve_language_picks_first_supported() -> None:
    assert resolve_language("ru-RU,ru;q=0.9,en;q=0.8") == "ru"


def test_resolve_language_picks_en() -> None:
    assert resolve_language("en-GB,en;q=0.9") == "en"


def test_resolve_language_picks_ky() -> None:
    assert resolve_language("ky") == "ky"


def test_resolve_language_falls_back_when_unsupported() -> None:
    assert resolve_language("fr-FR,fr;q=0.9") == "ru"


def test_resolve_language_falls_back_when_empty() -> None:
    assert resolve_language(None) == "ru"
    assert resolve_language("") == "ru"


# ─── t() ──────────────────────────────────────────────────────────────────────


def test_t_returns_ru_value() -> None:
    assert t("auth.otp.title", "ru") == "Введите номер телефона"


def test_t_returns_ky_value() -> None:
    assert t("auth.otp.title", "ky") == "Телефон номериңизди жазыңыз"


def test_t_returns_en_value() -> None:
    assert t("auth.otp.title", "en") == "Enter your phone number"


def test_t_falls_back_to_default_when_key_missing_in_target_lang() -> None:
    """SMS keys exist only in ru.json → KY/EN fall back to RU."""
    expected = "Pharmacy: ваш код 123. Никому не сообщайте."
    assert t("sms.otp", "ky", code="123") == expected
    assert t("sms.otp", "en", code="123") == expected


def test_t_interpolates_variables_ru() -> None:
    out = t("checkout.free_delivery_hint", "ru", amount=350)
    assert "350" in out
    assert "сом" in out


def test_t_interpolates_variables_en() -> None:
    out = t("search.no_results.title", "en", q="paracetamol")
    assert "paracetamol" in out


def test_t_missing_key_returns_key_string() -> None:
    """Missing key returns the literal key (and logs a warning, not asserted here)."""
    assert t("does.not.exist.anywhere", "ru") == "does.not.exist.anywhere"


def test_t_missing_var_returns_template_unformatted() -> None:
    """Interpolation failure returns the raw template; never raises."""
    result = t("checkout.free_delivery_hint", "ru")
    assert "{amount}" in result


def test_t_no_variables_returns_value_verbatim() -> None:
    """Keys without ``{var}`` placeholders work unchanged."""
    assert t("cart.empty.title", "ru") == "Ваша корзина пуста"
