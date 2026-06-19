"""
TENTATIVE keyword translation via the local LLM — the fallback tier for keywords
that no VERIFIED cross-language ring covers (maintainer ruling 2026-06-19:
"Wikidata rings + LLM fallback").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Doctrine (binding): the verified ring translation always wins; this only runs for a
keyword with NO ring translation into the target language. Its output is TENTATIVE
and labelled unreliable — never written into the trusted keyword index, never a
score, full model provenance. Local loopback only (Ollama); airplane mode (the kill
switch) refuses it at the client, surfaced.

Pure here (prompt build + parse), so it is testable with a stub client and no
network. A small process-global cache avoids re-translating the same term.
"""

from __future__ import annotations

import re

# Bump when the prompt changes (provenance flag travels with each tentative result).
TRANSLATE_PROMPT_VERSION = "kw-translate-v1"

# ISO-639-1 -> English language name for the prompt (the app's 12 UI languages + the
# common corpus source languages). An unknown code falls back to the bare code.
_LANG_NAMES = {
    "en": "English", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese",
    "it": "Italian", "nl": "Dutch", "ru": "Russian", "ar": "Arabic", "zh": "Chinese",
    "ja": "Japanese", "hi": "Hindi", "bn": "Bengali", "id": "Indonesian", "tr": "Turkish",
    "el": "Greek", "uk": "Ukrainian", "bg": "Bulgarian", "pl": "Polish", "sv": "Swedish",
    "da": "Danish", "nb": "Norwegian", "no": "Norwegian", "fi": "Finnish", "hu": "Hungarian",
    "ro": "Romanian", "cs": "Czech", "sr": "Serbian", "sl": "Slovenian", "fa": "Persian",
    "ur": "Urdu", "th": "Thai", "vi": "Vietnamese", "ca": "Catalan", "sk": "Slovak",
}

# Refusal / meta phrases that mean the model didn't actually translate.
_REFUSAL = re.compile(
    r"\b(as an ai|i (?:cannot|can't|am unable|am not able)|i'm sorry|sorry,|"
    r"there is no|no direct translation|cannot translate)\b",
    re.IGNORECASE,
)
_LIST_PREFIX = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s*")
# A leading "Translation:" / "Translation =" / "In French:" style label.
_LABEL = re.compile(r"^\s*(?:translation|traduction|in [a-z]+)\s*[:=]\s*", re.IGNORECASE)

_MAX_LEN = 60  # a translated keyword is a word or short phrase, never a sentence


def lang_name(code: str | None) -> str:
    c = (code or "").strip().lower()
    return _LANG_NAMES.get(c, c or "the source language")


def build_system(source_lang: str | None, target_lang: str) -> str:
    src = lang_name(source_lang)
    tgt = lang_name(target_lang)
    return (
        f"You translate a single search KEYWORD from {src} to {tgt}. "
        f"Output ONLY the {tgt} term — the common everyday word or short phrase — with "
        "no explanation, no quotes, no alternatives, no punctuation. If it is a proper "
        "name that stays the same, or you are unsure, output the term unchanged."
    )


def parse_translation(raw: str | None) -> str | None:
    """Clean the model output to a single short term, or None if unusable.

    Takes the first meaningful line; strips a leading list marker, a 'Translation:'
    label, and surrounding quotes; rejects empties, sentences (> _MAX_LEN), and
    refusal/meta text. No score, no alternatives — one tentative term."""
    for line in (raw or "").splitlines():
        s = _LABEL.sub("", _LIST_PREFIX.sub("", line)).strip().strip("\"'“”«»").strip()
        if not s:
            continue
        if len(s) > _MAX_LEN or _REFUSAL.search(s):
            return None
        return s
    return None


def translate_keyword(
    client,
    term: str,
    source_lang: str | None,
    target_lang: str,
    *,
    model: str,
    keep_alive: str | None = None,
) -> str | None:
    """Ask the local model for a TENTATIVE translation of one keyword into
    ``target_lang``. Returns the cleaned term or None (empty input, a no-op
    same-string result, or unusable output). Raises the client's error if Ollama is
    unavailable — the caller decides (the endpoint gates on ``is_available`` first)."""
    t = (term or "").strip()
    tgt = (target_lang or "").strip().lower()
    if not t or not tgt or (source_lang or "").strip().lower() == tgt:
        return None
    result = client.generate(
        t, model=model, system=build_system(source_lang, target_lang), keep_alive=keep_alive
    )
    out = parse_translation(getattr(result, "text", None))
    if not out or out.casefold() == t.casefold():
        return None  # nothing added (the model echoed the source)
    return out


# A small process-global cache: a tentative translation is stable, so the same
# (source, target, term) never needs re-asking the model. Bounded (FIFO-ish drop).
_CACHE: dict[tuple[str, str, str], str | None] = {}
_CACHE_MAX = 5000


def clear_cache() -> None:
    _CACHE.clear()


def translate_keywords(
    client,
    items: list[dict],
    target_lang: str,
    *,
    model: str,
    keep_alive: str | None = None,
    max_items: int = 25,
) -> dict[str, str]:
    """Tentative translations for a batch of ``{term, language}`` items into
    ``target_lang``. A keyword a VERIFIED ring already covers is SKIPPED (the verified
    tier wins). Results are cached per (source, target, term). Per-item failures (a
    mid-batch Ollama outage, a bad term) are swallowed so the caller still gets what
    succeeded. Returns ``{term: tentative_translation}`` (only the ones that produced
    a usable, non-echo translation)."""
    from src.analytics.equivalence import translate_term

    tgt = (target_lang or "").strip().lower()
    out: dict[str, str] = {}
    if not tgt:
        return out
    for it in items[:max_items]:
        term = (it.get("term") or "").strip()
        lang = (it.get("language") or "").strip().lower()
        if not term or lang == tgt:
            continue
        if translate_term(lang, term, tgt):
            continue  # verified ring translation exists — never override it
        key = (lang, tgt, term.casefold())
        if key in _CACHE:
            v = _CACHE[key]
        else:
            try:
                v = translate_keyword(client, term, lang, tgt, model=model, keep_alive=keep_alive)
            except Exception:  # noqa: BLE001 - a mid-batch outage / bad term: skip, keep the rest
                continue
            if len(_CACHE) < _CACHE_MAX:
                _CACHE[key] = v
        if v:
            out[term] = v
    return out
