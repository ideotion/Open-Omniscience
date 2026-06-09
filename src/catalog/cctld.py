"""
Infer a source's country (and, where unambiguous, language) from its domain's
country-code TLD — so the catalogue's geographic/linguistic skew becomes
*measurable* (see docs/ROADMAP.md).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

HONEST + CONSERVATIVE by design:
- A ccTLD only counts when it reliably maps to one country. ccTLDs that are widely
  *repurposed as generic* (``.io .co .me .ai .tv .cc .gg .ly .fm .sh .to .ws .st``)
  are treated as **unknown** rather than mis-attributed (a ``.io`` site is almost
  never British Indian Ocean Territory).
- Generic gTLDs (``.com .org .net .info .news`` …) yield ``None`` — we don't guess.
- Language is inferred only for ccTLDs with a single dominant language; multilingual
  countries (``.ch .be .ca .in .za .sg`` …) yield ``None``.

Pure + network-free; the ccTLD list is derived from the ISO codes in
``countries.py`` so it stays in sync. Tune the sets below freely.
"""

from __future__ import annotations

from src.catalog.countries import ISO_3166_1_ALPHA2

# Ambiguous ccTLDs dominated by generic/vanity use — excluded to avoid false hits.
GENERIC_CCTLDS: frozenset[str] = frozenset(
    [
        "io",
        "co",
        "me",
        "ai",
        "tv",
        "cc",
        "gg",
        "ly",
        "fm",
        "sh",
        "to",
        "ws",
        "st",
        "nu",
        "mu",
        "vc",
        "ag",
        "im",
        "je",
    ]
)

# ccTLDs whose live string differs from the ISO alpha-2 (or that we add explicitly).
_SPECIAL_COUNTRY: dict[str, str] = {"uk": "gb"}


def _country_map() -> dict[str, str]:
    m = {c: c for c in ISO_3166_1_ALPHA2 if c not in GENERIC_CCTLDS}
    m.update(_SPECIAL_COUNTRY)
    return m


CCTLD_COUNTRY: dict[str, str] = _country_map()

# ccTLD -> ISO-639-1 language, only where one language clearly dominates.
CCTLD_LANGUAGE: dict[str, str] = {
    "fr": "fr",
    "de": "de",
    "at": "de",
    "it": "it",
    "es": "es",
    "pt": "pt",
    "br": "pt",
    "ru": "ru",
    "ua": "uk",
    "by": "ru",
    "pl": "pl",
    "nl": "nl",
    "se": "sv",
    "no": "no",
    "dk": "da",
    "fi": "fi",
    "is": "is",
    "gr": "el",
    "cz": "cs",
    "sk": "sk",
    "hu": "hu",
    "ro": "ro",
    "bg": "bg",
    "hr": "hr",
    "rs": "sr",
    "si": "sl",
    "lt": "lt",
    "lv": "lv",
    "ee": "et",
    "tr": "tr",
    "jp": "ja",
    "kr": "ko",
    "cn": "zh",
    "tw": "zh",
    "th": "th",
    "vn": "vi",
    "id": "id",
    "ir": "fa",
    "il": "he",
    "sa": "ar",
    "eg": "ar",
    "ge": "ka",
    "am": "hy",
    "az": "az",
    "kz": "kk",
    "mn": "mn",
    "np": "ne",
    "lk": "si",
}


def _tld(domain: str | None) -> str | None:
    if not domain:
        return None
    parts = domain.strip().strip(".").lower().split(".")
    return parts[-1] if len(parts) >= 2 and parts[-1] else None


def infer_country(domain: str | None) -> str | None:
    """Return a 2-letter ISO country for a reliable ccTLD, else ``None``."""
    return CCTLD_COUNTRY.get(_tld(domain) or "")


def infer_language(domain: str | None) -> str | None:
    """Return a language code for a single-language-dominant ccTLD, else ``None``."""
    return CCTLD_LANGUAGE.get(_tld(domain) or "")
