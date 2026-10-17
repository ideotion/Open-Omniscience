"""
Page furniture and stub signals for the ingest door (source-qualification review, 2026-10-17).

Four stored pages showed what the existing gate in :mod:`src.ingest.non_article` lets through:
a page whose whole "body" was the site menu plus a login prompt, and real teasers padded with
ad-placeholder paragraphs ("Annons") and an app-update banner. This module adds two things, both
EXPLICIT rules with a disclosed reason, never a score:

* :func:`strip_furniture` removes paragraphs that are, in full, a known ad placeholder or app
  banner. It never touches a paragraph that merely contains such a word.
* :func:`stub_verdict` names a THIN body (under ``non_article._ARTICLE_MIN_WORDS`` words after
  stripping) as a ``menu_stub`` (nearly every paragraph is a short unpunctuated menu line) or a
  ``paywall_stub`` (a subscriber prompt in a language the English wall phrases miss).

Precision first, like its caller: a false positive hides a real article. Callers MARK (the
quarantine stamp is reversible), they never delete. What this does NOT see: a teaser of real
prose with no prompt in the text itself (the paywall link was outside the extracted body).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re

# A paragraph that is, in full, one of these (casefolded, edge punctuation dropped) is an ad slot.
AD_PLACEHOLDERS = frozenset({
    "annons", "annonser", "annonse", "annonsørinnhold", "annonce", "reklam", "reklame",
    "mainos", "mainokset", "advertisement", "advertising", "advertorial", "anzeige", "werbung",
    "publicité", "publicidad", "pubblicità", "publicidade", "advertentie", "reclame", "реклама",
})
# A SHORT paragraph containing one of these is an app/update banner, not article text.
APP_BANNER_PHRASES = (
    "för att din app ska fortsätta fungera",
    "for at din app skal fortsette å fungere",
    "jotta sovellus toimii",
    "to keep your app working, update",
)
_BANNER_MAX_WORDS = 40

# Subscriber prompts that sit INSIDE a thin extracted body (the English set lives in non_article).
PAYWALL_PHRASES = (
    "allerede abonnent", "allerede abonnent?", "redan prenumerant", "redan prenumerant?",
    "jo tilaaja", "olet jo tilaaja", "bli abonnent", "bli prenumerant", "tilaa lukeaksesi",
    "kirjaudu sisään lukeaksesi", "prenumerera för att läsa", "abonner for å lese",
    "abonner for at læse", "bereits abonnent", "déjà abonné",
)

MENU_MIN_PARAGRAPHS = 12
MENU_SHORT_WORDS = 6       # a menu entry; the page's own headline (9 words) may exceed it
MENU_MAX_WORDS = 12        # but no paragraph of a menu page is a sentence
MENU_SHARE = 0.8
_END_PUNCT = ".!?…»\"”’"
_EDGE = " \t .:;!?-–—·•|"

_SPLIT = re.compile(r"\n+")


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _SPLIT.split(text or "") if p.strip()]


def is_furniture(paragraph: str) -> bool:
    low = paragraph.casefold().strip(_EDGE)
    if low in AD_PLACEHOLDERS:
        return True
    return len(paragraph.split()) <= _BANNER_MAX_WORDS and any(
        phrase in paragraph.casefold() for phrase in APP_BANNER_PHRASES
    )


def strip_furniture(text: str) -> tuple[str, int]:
    """``(text without furniture paragraphs, how many were removed)``. Unchanged text comes back
    byte-identical, so a page with none changes neither its stored body nor its content hash."""
    paragraphs = _paragraphs(text)
    kept = [p for p in paragraphs if not is_furniture(p)]
    if len(kept) == len(paragraphs):
        return text, 0
    return "\n\n".join(kept), len(paragraphs) - len(kept)


def is_menu_like(text: str) -> bool:
    paragraphs = _paragraphs(text)
    if len(paragraphs) < MENU_MIN_PARAGRAPHS:
        return False
    counts = [len(p.split()) for p in paragraphs]
    if max(counts) > MENU_MAX_WORDS:
        return False
    menu = sum(
        1 for p, n in zip(paragraphs, counts, strict=True)
        if n <= MENU_SHORT_WORDS and not p.endswith(tuple(_END_PUNCT))
    )
    return menu / len(paragraphs) >= MENU_SHARE


def stub_verdict(text: str | None) -> tuple[str, str] | None:
    """``(signal, reason)`` for a thin body that is a menu or a subscriber prompt, else ``None``.
    The caller has already established the body is thin; furniture is stripped first."""
    if not text:
        return None
    body, _ = strip_furniture(text)
    if is_menu_like(body):
        return ("menu_stub", "body is site-menu lines, not article text: nearly every paragraph "
                "is a short unpunctuated entry")
    low = body.casefold()
    for phrase in PAYWALL_PHRASES:
        if phrase in low:
            return ("paywall_stub", f"subscriber prompt in a thin body: '{phrase}'")
    return None
