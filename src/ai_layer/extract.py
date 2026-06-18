"""
LLM keyword/entity extraction — the FIRST writer into the AI layer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This reads an article's text and asks the LOCAL model for the salient keywords and
named entities. The result is AI-DERIVED and lands ONLY in the separate AI store
(src.ai_layer.store), never the trusted, rule-based keyword index in the main DB —
it is a parallel lens, labelled and disposable (maintainer ruling, strict physical
separation). Honesty by construction: no score, full model provenance per term, and
unconfirmed until a user curates the lens.

The extraction is pure here (it takes an LLM client + text and returns a term list),
so it is testable with a stub client and no network; the batch runner that persists
the terms lives in :mod:`src.ai_layer.jobs`.
"""

from __future__ import annotations

import re

# Prompt provenance — stored on every AI keyword row (bump when this prompt changes).
EXTRACT_PROMPT_VERSION = "ai-keywords-v1"

# Keep the prompt within a small CPU model's context (mirrors src.api.llm._MAX_CHARS).
_MAX_CHARS = 6000

_EXTRACT_SYSTEM = (
    "You are a research assistant indexing an article for an investigative journalist. "
    "From the text below, list the most salient KEYWORDS and NAMED ENTITIES (people, "
    "organisations, places, topics) the article is actually about — using only its text. "
    "Output ONE per line, at most {max_terms} lines, no numbering, no commentary, no "
    "duplicates; keep proper nouns as written. If the text is not a usable article "
    "(paywall, navigation, error page), output nothing."
)

# Strip a leading list marker the model may emit despite the instruction:
# "1. ", "2) ", "- ", "* ", "• ".
_LIST_PREFIX = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s*")


def parse_terms(text: str | None, *, max_terms: int) -> list[str]:
    """Turn raw model output into a clean, de-duplicated, bounded term list.

    One term per line; list markers and surrounding quotes stripped; blank lines and
    obvious non-terms (longer than 80 chars — that is a sentence, not a keyword)
    dropped; de-duplicated case-insensitively keeping the first form (so a proper
    noun's casing survives); capped at ``max_terms``.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        term = _LIST_PREFIX.sub("", line).strip().strip("\"'").strip()
        if not term or len(term) > 80:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


def extract_terms(
    client,
    title: str | None,
    content: str | None,
    *,
    model: str,
    max_terms: int = 20,
    keep_alive: str | None = None,
    system: str | None = None,
) -> list[str]:
    """Ask the local model for an article's salient terms. Returns a clean list (may
    be empty — an unusable page yields nothing). Raises the client's ``LLMUnavailable``
    / ``LLMError`` (the caller decides how to handle a mid-run outage).

    A custom ``system`` prompt (a user-defined extractor) overrides the built-in keyword
    instruction; the parsing (one item per line, deduped, bounded) is SHARED, so every
    extractor — built-in or user-defined — yields the same unified, typed AI-metadata
    shape. ``{max_terms}`` is substituted in whichever system prompt is used."""
    text = (content or "").strip()
    if not text:
        return []
    base = system if (system and system.strip()) else _EXTRACT_SYSTEM
    sys_prompt = base.replace("{max_terms}", str(max_terms))
    prompt = f"Article title: {title or '(untitled)'}\n\n{text[:_MAX_CHARS]}"
    result = client.generate(prompt, model=model, system=sys_prompt, keep_alive=keep_alive)
    return parse_terms(result.text, max_terms=max_terms)
