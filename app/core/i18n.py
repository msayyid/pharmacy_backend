"""Language resolution.

Storefront picks the first supported language from the Accept-Language header,
falling back to ``settings.default_language``. For authenticated users the
service layer should override with ``users.preferred_language``.

Reference: BACKEND_BLUEPRINT.md §22.1; PRODUCT_BLUEPRINT.md §16.
"""

from __future__ import annotations

from app.core.config import Settings


def resolve_language(accept_language: str | None, settings: Settings) -> str:
    """Pick the first supported language from Accept-Language.

    Falls back to ``settings.default_language`` if header missing or no token
    matches a supported language.

    Examples (with default ``ru``, supported ``("ru","ky","en")``):

    * ``"ru-RU,ru;q=0.9,en;q=0.8"`` → ``"ru"``
    * ``"en-GB,en;q=0.9"`` → ``"en"``
    * ``"fr-FR"`` → ``"ru"``
    * ``None`` → ``"ru"``
    """
    if not accept_language:
        return settings.default_language
    for token in accept_language.split(","):
        code = token.split(";")[0].strip().lower().split("-")[0]
        if code in settings.supported_languages:
            return code
    return settings.default_language
