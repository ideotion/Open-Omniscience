"""Which content languages the keyword/analytics engine can MANAGE today.

A language is *managed* when keyword extraction is functional: a stoplist exists
AND the script is space-segmented. ``zh``/``ja`` have no word segmentation, so their
extraction is broken; the *no_stoplist* languages tokenise but leak function words —
junk that pollutes analytics (false keywords, skewed associations) AND inflates the
corpus (every aggregation pays for it).

Maintainer ruling (2026-06-18): sources in UNMANAGED languages seed **disabled by
default** — kept, never deleted, re-enablable — so the app stops accumulating
un-analysable junk until a stoplist for that language lands. This module is the ONE
source of truth; both the engine report and the source gating read it.

The managed set mirrors the verified-present stoplists (self-test covers
en/de/fr/es/it/pt/nl/ru/ar/hu/id; the evidence batch seeded sv/da/nb/no/pl/sr/sl).
fi/tr/hi/bn and the rest are deliberately NOT claimed: they tokenise but leak.
"""

from __future__ import annotations

MANAGED_LANGUAGES: frozenset[str] = frozenset(
    {
        "en", "fr", "de", "es", "it", "pt", "nl", "ru", "ar", "hu", "id",
        "sv", "da", "nb", "no", "pl", "sr", "sl",
    }
)
# No word segmentation -> keyword extraction is broken regardless of a stoplist.
UNSEGMENTED: frozenset[str] = frozenset({"zh", "ja"})


def normalize_lang(lang: str | None) -> str:
    """Bare ISO-639-1 code: lowercased, region/script stripped ('en-US' -> 'en')."""
    if not lang:
        return ""
    return lang.strip().lower().replace("_", "-").split("-")[0]


def is_managed(lang: str | None) -> bool:
    """True when the keyword engine can analyse this language today.

    An unknown/empty language is NOT 'managed' but is also not 'unmanaged' for the
    gating purpose — callers decide; the source gating leaves unknown-language
    sources enabled (we cannot justify disabling what we cannot classify)."""
    return normalize_lang(lang) in MANAGED_LANGUAGES


def language_status(lang: str | None) -> str:
    """'functional' | 'unsegmented' | 'no_stoplist' | 'unknown' for one language."""
    n = normalize_lang(lang)
    if not n:
        return "unknown"
    if n in UNSEGMENTED:
        return "unsegmented"
    if n in MANAGED_LANGUAGES:
        return "functional"
    return "no_stoplist"


def is_unmanaged(lang: str | None) -> bool:
    """True only for a KNOWN language the engine cannot analyse (no_stoplist or
    unsegmented). Unknown/empty returns False — never disable what we can't classify."""
    return language_status(lang) in ("no_stoplist", "unsegmented")
