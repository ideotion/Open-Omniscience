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
  or a ``paywall_stub`` (a short line that is a subscriber prompt and no sentence of article prose
  beside it: a body that carries a full sentence is a short article that ends on a subscribe call).

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
# Non-prompt text of at least this many words, with a paragraph ending in terminal punctuation, is
# SENTENCES; a body that has them is a short article that merely ends on a subscribe call, and is spared as a paywall_stub. A
# headline carries no terminal punctuation, so "headline + subscriber prompt + Log in" still is one.
# FITTED TO TWO DATA POINTS ONLY (the Fjordabladet headline shape, and a 12-word brief with a closing
# prompt); no corpus has measured it. The quarantine dry-run counts and samples are what should
# confirm or move it, and stub signals only run when the operator switches them on after those counts.
_PROMPT_SENTENCE_MIN_WORDS = 6
# ...and the paragraph that ends in terminal punctuation must itself be this long, so a login line
# ("Logg inn her.") or a "Les mer?" link does not pass for a sentence. Fitted like the 6 above.
_SENTENCE_LINE_MIN_WORDS = 4
_SENTENCE_END = ".!?…"
# Closing marks and a trailing agency tag ("[NTB]") that may follow a sentence's final punctuation.
_CLOSER_CHARS = " \t\r\n»\"”“’'()}›"


def _without_closers(paragraph: str) -> str:
    """``paragraph`` minus trailing closing marks and a trailing ``[tag]``. A right-to-left scan, so
    the cost is linear in the length (a regex for this backtracked cubically on long whitespace)."""
    text = paragraph
    while True:
        stripped = text.rstrip(_CLOSER_CHARS)
        if stripped.endswith("]"):
            open_at = stripped.rfind("[", max(0, len(stripped) - 22))
            if open_at != -1:
                stripped = stripped[:open_at]
        if stripped == text:
            return text
        text = stripped

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


LEARN_MAX_WORDS = 12


def learn_repeated_lines(texts: list[str], *, min_share: float = 0.3, min_articles: int = 3) -> dict:
    """Lines that recur across ONE source's bodies: a candidate list for a human to read, never a rule.

    A line counts once per body, is compared casefolded with edge punctuation dropped, and is a
    candidate only when it is SHORT (``LEARN_MAX_WORDS`` words or fewer; a repeated long paragraph is
    syndication or a quotation, not a slot) and appears in at least ``min_share`` of the bodies AND at
    least ``min_articles`` of them. Lines ``is_furniture`` already names are marked ``known`` so the
    reader sees what the rules already catch. Nothing is stripped or marked here."""
    bodies = [t for t in texts if t and t.strip()]
    n = len(bodies)
    counts: dict[str, int] = {}
    shown: dict[str, str] = {}
    for body in bodies:
        seen = set()
        for para in _paragraphs(body):
            if len(para.split()) > LEARN_MAX_WORDS:
                continue
            key = para.casefold().strip(_EDGE)
            if not key or key in seen:
                continue
            seen.add(key)
            shown.setdefault(key, para)
        for key in seen:
            counts[key] = counts.get(key, 0) + 1
    floor = max(min_articles, min_share * n)
    kept = sorted((k for k, c in counts.items() if c >= floor), key=lambda k: (-counts[k], shown[k]))
    rows = [
        {"line": shown[k], "articles": counts[k], "share": round(counts[k] / n, 3),
         "known": is_furniture(shown[k])}
        for k in kept
    ]
    return {"examined": n, "candidates": rows}


def strip_furniture(text: str) -> tuple[str, int]:
    """``(text without furniture lines, how many were removed)``. Only the matched lines go (plus
    one blank separator line after each); every other byte is kept, so text without furniture
    comes back identical, and a removed line never merges the paragraphs around it."""
    lines = (text or "").splitlines(keepends=True)
    kept: list[str] = []
    removed = 0
    skip_blank = False
    tail_removed = False
    for line in lines:
        if skip_blank and not line.strip():
            skip_blank = False
            continue
        skip_blank = False
        if line.strip() and is_furniture(line.strip()):
            removed += 1
            # The blank after a removed line goes only when a blank (or the start) already precedes
            # it; otherwise it is the separator between two paragraphs and must stay.
            skip_blank = not kept or not kept[-1].strip()
            tail_removed = True
            continue
        if line.strip():
            tail_removed = False
        kept.append(line)
    if not removed:
        return text, 0
    if tail_removed:  # furniture was the last content: the blanks it leaves behind go with it
        while kept and not kept[-1].strip():
            kept.pop()
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
    # A colon line among the first two paragraphs (a headline may come first) introduces a list
    # ("The nominees are:"): a short list article, not a menu. A colon line deeper in the page is a
    # widget label ("Choose a theme:") and does not count.
    if any(p.endswith(":") for p in paragraphs[:2]):
        return False
    menu = sum(
        1 for p, n in zip(paragraphs, counts, strict=True)
        if n <= MENU_SHORT_WORDS and not p.endswith(tuple(_END_PUNCT))
    )
    return menu / len(paragraphs) >= MENU_SHARE


def _has_prompt(paragraphs: list[str]) -> str | None:
    """The first prompt phrase found, unless the body also carries more prose than a prompt line
    could: a complete short brief that ends on "subscribe?" is an article, not a stub (a teaser
    lead that is a full sentence is spared too, which is the safe error for a precision-first signal)."""
    found = None
    ends_a_sentence = False
    prose_words = 0
    for p in paragraphs:
        n = len(p.split())
        hit = None
        if n <= _PROMPT_MAX_WORDS:
            low = p.casefold()
            for phrase in PAYWALL_PHRASES:
                if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", low):
                    hit = phrase
                    break
        if hit:
            found = found or hit
        else:
            prose_words += n
            ends_a_sentence = ends_a_sentence or (
                n >= _SENTENCE_LINE_MIN_WORDS and _without_closers(p).endswith(tuple(_SENTENCE_END)))
    # Judged over the whole non-prompt text, so a brief of short sentences or one wrapped over
    # several lines is spared like a single long paragraph.
    sentence = ends_a_sentence and prose_words >= _PROMPT_SENTENCE_MIN_WORDS
    return found if found and not sentence else None


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
