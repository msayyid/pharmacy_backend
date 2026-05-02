"""URL-slug generation for categories, symptoms, products.

* Cyrillic → Latin transliteration via ``python-slugify[unidecode]``.
* Restricts to ``[a-z0-9-]``.
* Collision suffix: ``base``, ``base-2``, ``base-3``, ….

The collision loop lives in services (it needs a "does this slug exist"
predicate that is repository-specific). This module provides only the
pure ``slugify_name`` step.

Reference: PRODUCT_BLUEPRINT.md §13.4; CLAUDE_CODE_PROMPTS Phase 5.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from slugify import slugify as _slugify


def slugify_name(name: str) -> str:
    """Transliterate + lowercase + hyphenate. Returns ``""`` if input collapses."""
    if not name:
        return ""
    return _slugify(name, lowercase=True, separator="-", allow_unicode=False)


_MAX_SLUG_SUFFIX_TRIES = 1000


async def unique_slug(
    base: str,
    exists: Callable[[str], Awaitable[bool]],
) -> str:
    """Append ``-2``, ``-3``, … until ``exists(candidate)`` returns False.

    ``exists`` is a repository-supplied async predicate (``slug_exists``).
    Raises ``ValueError`` after ``_MAX_SLUG_SUFFIX_TRIES`` collisions —
    a guard against runaway loops, never expected in practice.
    """
    if not base:
        raise ValueError("slug base is empty")
    if not await exists(base):
        return base
    for i in range(2, _MAX_SLUG_SUFFIX_TRIES + 2):
        candidate = f"{base}-{i}"
        if not await exists(candidate):
            return candidate
    raise ValueError(f"could not generate unique slug from base={base!r}")
