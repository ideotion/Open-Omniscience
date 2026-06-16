"""
Bundled, dated SIZE ESTIMATES for the offline Wikipedia dumps.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Approximate COMPRESSED sizes of the ``pages-articles-multistream.xml.bz2`` dump
per edition — the DEFAULT kind new downloads use (src.wiki.dumps). These are
coarse, dated ESTIMATES shown INLINE in the edition picker so it is informative
WITHOUT firing a network probe per edition (zero-network boot / airplane mode
stay intact — UI invariant #14). The exact size is always read from the dump
server at download time; a consented one-call "refresh exact sizes" can later
replace these with live figures (the dump date's dumpstatus.json lists every
edition at once, so it is ONE request, not N HEADs).

HONESTY CONTRACT (mirrors the model catalog, src.llm.ollama.CATALOG_AS_OF): real
dump sizes drift each cycle. ``DUMP_SIZES_AS_OF`` is shown wherever the estimates
appear (the caveat reads "estimate · reviewed {date} · exact on download"), and a
repo-invariant freshness test (tests/test_dump_sizes.py) FAILS once it is older
than the window — forcing a re-review against https://dumps.wikimedia.org or a
knowing date bump. Values are deliberately rounded and never presented as a
particular dump's exact size.
"""

from __future__ import annotations

# Review vintage of the estimates below (when they were last compiled/checked),
# NOT a claim about a specific dump date. Format "YYYY-MM" (freshness-tested).
DUMP_SIZES_AS_OF = "2026-06"

_GB = 1024**3

# Edition code -> approximate COMPRESSED bytes of pages-articles-multistream.xml.bz2.
# Rounded, order-of-magnitude estimates only (the caveat says so). Covers the
# dump-eligible editions (src.wiki.languages.APP_LANGUAGE_CODES); any other code
# simply gets no inline estimate (the picker still works, the probe still does).
_ESTIMATE_GB: dict[str, float] = {
    "en": 22.0,
    "fr": 8.0,
    "de": 7.5,
    "ru": 6.0,
    "es": 5.0,
    "it": 4.5,
    "ja": 4.5,
    "pt": 3.0,
    "zh": 3.0,
    "pl": 3.0,
    "ar": 2.5,
    "sv": 2.5,
    "nl": 2.0,
    "tr": 1.5,
    "id": 1.2,
    "hi": 1.0,
    "bn": 0.9,
}


def estimate_bytes(code: str) -> int | None:
    """Approximate compressed size (bytes) of an edition's multistream dump, or
    ``None`` when no estimate is bundled for that code."""
    gb = _ESTIMATE_GB.get((code or "").strip().lower())
    return round(gb * _GB) if gb is not None else None


def estimated_codes() -> frozenset[str]:
    """The set of edition codes that carry a bundled size estimate."""
    return frozenset(_ESTIMATE_GB)
