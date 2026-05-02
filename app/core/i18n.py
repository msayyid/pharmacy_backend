"""Language resolution and translation loader.

* :func:`resolve_language` — picks the first supported language from the
  ``Accept-Language`` header, falling back to ``settings.default_language``.
* :func:`t` — translate a key. Lookup chain: target lang → default lang →
  the key itself (with a warning logged so it surfaces in tests/dev).
* JSON files live in ``app/i18n/<lang>.json`` and are loaded lazily on first
  access; cached in module-level dict for the life of the process.

Reference: BACKEND_BLUEPRINT.md §22; PRODUCT_BLUEPRINT.md §16, §21.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_I18N_DIR = Path(__file__).parent.parent / "i18n"

# Module-level cache: {"ru": {"key": "value"}, ...}
_translations: dict[str, dict[str, str]] = {}


def _load_translations(lang: str) -> dict[str, str]:
    """Load a language's JSON file once per process; cache thereafter."""
    cached = _translations.get(lang)
    if cached is not None:
        return cached
    path = _I18N_DIR / f"{lang}.json"
    if not path.exists():
        log.warning("i18n_file_missing", lang=lang, path=str(path))
        _translations[lang] = {}
        return _translations[lang]
    with path.open(encoding="utf-8") as f:
        data: dict[str, str] = json.load(f)
    _translations[lang] = data
    return data


def clear_translation_cache() -> None:
    """Reset the in-memory cache. Tests use this to test reload behaviour."""
    _translations.clear()


def resolve_language(accept_language: str | None) -> str:
    """Pick the first supported language from Accept-Language.

    Falls back to ``settings.default_language`` if header missing or no token
    matches.

    Examples (default ``ru``, supported ``("ru","ky","en")``):

    * ``"ru-RU,ru;q=0.9,en;q=0.8"`` → ``"ru"``
    * ``"en-GB,en;q=0.9"`` → ``"en"``
    * ``"fr-FR"`` → ``"ru"``
    * ``None`` → ``"ru"``
    """
    settings = get_settings()
    if not accept_language:
        return settings.default_language
    for token in accept_language.split(","):
        code = token.split(";")[0].strip().lower().split("-")[0]
        if code in settings.supported_languages:
            return code
    return settings.default_language


def t(key: str, lang: str, **variables: Any) -> str:
    """Translate ``key`` into ``lang``, with optional ``str.format`` interpolation.

    Lookup chain:

    1. ``lang.json[key]``
    2. ``default_language.json[key]`` (if ``lang != default_language``)
    3. The literal key string (and a ``i18n_missing_key`` warning is logged)

    If interpolation fails (missing variable in ``**variables``), the
    unformatted template is returned and ``i18n_missing_var`` is logged —
    we never raise on a translation lookup.
    """
    settings = get_settings()
    candidates: list[str] = [lang]
    if lang != settings.default_language:
        candidates.append(settings.default_language)

    for candidate in candidates:
        bundle = _load_translations(candidate)
        if key in bundle:
            value = bundle[key]
            if not variables:
                return value
            try:
                return value.format(**variables)
            except KeyError as exc:
                log.warning(
                    "i18n_missing_var",
                    key=key,
                    lang=candidate,
                    missing=str(exc).strip("'"),
                )
                return value
            except (IndexError, ValueError):
                log.warning("i18n_format_error", key=key, lang=candidate)
                return value

    log.warning("i18n_missing_key", key=key, lang=lang)
    return key
