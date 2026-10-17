"""
Page furniture and stub signals for the ingest door (source-qualification review, 2026-10-17).

Four stored pages showed what the existing gate in :mod:`src.ingest.non_article` lets through:
a page whose whole "body" was the site menu plus a login prompt, and real teasers padded with
ad-placeholder paragraphs ("Annons") and an app-update banner. This module adds two things, both
EXPLICIT rules with a disclosed reason, never a score:

* :func:`strip_furniture` removes lines that are, in full, a known ad placeholder or a
  language-specific app banner. It never touches a line that merely contains such a word, and it
  leaves every other byte of the body exactly as extracted.
* :func:`stub_verdict` names a THIN body (under ``non_article._ARTICLE_MIN_WORDS`` words after
  stripping) as a ``menu_stub`` (nearly every line is a short, unpunctuated, digit-free menu entry)
  or a ``paywall_stub`` (a short line that is a subscriber prompt).

Precision first: a false positive hides a real article. The stub verdict is used ONLY by the
quarantine job, and only when asked for (``include_stubs``): it MARKS, the operator sees dry-run
counts first, nothing is dropped at ingest and nothing is deleted. What this does NOT see: a teaser
of real prose whose paywall prompt was outside the extracted body.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re

# A paragraph that is, in full, one of these (casefolded, edge punctuation dropped) is an ad slot.
# Words that are also ordinary section headings (advertising, Werbung, Reklame, Publicidad,
# Annonser ...) are deliberately NOT here: only labels that name a single ad slot.
AD_PLACEHOLDERS = frozenset({
    "annons", "annonse", "annonce", "mainos", "mainokset", "advertisement", "anzeige",
    "publicité", "pubblicità", "publicidade", "advertentie", "реклама",
})
# A SHORT paragraph containing one of these is an app/update banner, not article text.
APP_BANNER_PHRASES = (
    "för att din app ska fortsätta fungera",
    "for at din app skal fortsette å fungere",
)
_BANNER_MAX_WORDS = 40

# Subscriber prompts that sit INSIDE a thin extracted body (the English set lives in non_article).
# Matched as WHOLE WORDS inside a SHORT line (<= _PROMPT_MAX_WORDS): a prompt is its own line.
PAYWALL_PHRASES = (
    "allerede abonnent", "redan prenumerant", "olet jo tilaaja", "bli abonnent",
    "bli prenumerant", "tilaa lukeaksesi", "kirjaudu sisään lukeaksesi",
    "prenumerera för att läsa", "abonner for å lese", "abonner for at læse",
    "bereits abonnent", "déjà abonné",
)
_PROMPT_MAX_WORDS = 8

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
    """``(text without furniture lines, how many were removed)``. Only the matched lines go (plus
    one blank separator line after each); every other byte is kept, so text without furniture
    comes back identical and text with some is not reformatted."""
    lines = (text or "").splitlines(keepends=True)
    kept: list[str] = []
    removed = 0
    skip_blank = False
    for line in lines:
        if skip_blank and not line.strip():
            skip_blank = False
            continue
        skip_blank = False
        if line.strip() and is_furniture(line.strip()):
            removed += 1
            skip_blank = True
            continue
        kept.append(line)
    if not removed:
        return text, 0
    return "".join(kept), removed


def is_menu_like(text: str) -> bool:
    paragraphs = _paragraphs(text)
    if len(paragraphs) < MENU_MIN_PARAGRAPHS:
        return False
    counts = [len(p.split()) for p in paragraphs]
    if max(counts) > MENU_MAX_WORDS:
        return False
    # A digit means data (a result table, a listing), not a menu entry: such a page is not judged.
    if any(ch.isdigit() for p in paragraphs for ch in p):
        return False
    menu = sum(
        1 for p, n in zip(paragraphs, counts, strict=True)
        if n <= MENU_SHORT_WORDS and not p.endswith(tuple(_END_PUNCT))
    )
    return menu / len(paragraphs) >= MENU_SHARE


def _has_prompt(paragraphs: list[str]) -> str | None:
    for p in paragraphs:
        if len(p.split()) > _PROMPT_MAX_WORDS:
            continue
        low = p.casefold()
        for phrase in PAYWALL_PHRASES:
            if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", low):
                return phrase
    return None


def stub_verdict(text: str | None) -> tuple[str, str] | None:
    """``(signal, reason)`` for a thin body that is a menu or a subscriber prompt, else ``None``.
    The caller has already established the body is thin; furniture is stripped first."""
    if not text:
        return None
    body, _ = strip_furniture(text)
    if is_menu_like(body):
        return ("menu_stub", "body is site-menu lines, not article text: nearly every line "
                "is a short unpunctuated entry")
    phrase = _has_prompt(_paragraphs(body))
    if phrase:
        return ("paywall_stub", f"subscriber prompt line in a thin body: '{phrase}'")
    return None
