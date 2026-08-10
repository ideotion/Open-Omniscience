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

from src.ai_layer.sampling import sweep_options

# Prompt provenance — stored on every AI keyword row (bump when this prompt changes).
EXTRACT_PROMPT_VERSION = "ai-keywords-v1"

# WHOLE-ARTICLE COVERAGE since 2026-08-10 (maintainer ruling: truncating background
# sweeps "is not acceptable"). The article is split into parts that each fit the
# window, every part is extracted, and the term lists are merged ROUND-ROBIN so the
# ``max_terms`` cap cannot quietly restore the head bias the chunking removes.
# See src.ai_layer.coverage.

# The English body lives in ONE place (src/llm/prompts_i18n) alongside its eleven
# translations, so the two can never drift apart -- a second copy here would be a
# silent fork the moment either is edited. The name is kept because callers and
# tests refer to it, and because this stays the honest default for any path that
# has no UI language to select with.
from src.llm.prompts_i18n import PROMPTS as _PROMPTS

_EXTRACT_SYSTEM = _PROMPTS["ai_keywords"]["en"]

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
    budget_chars: int | None = None,
) -> list[str]:
    """Ask the local model for an article's salient terms. Returns a clean list (may
    be empty — an unusable page yields nothing). Raises the client's ``LLMUnavailable``
    / ``LLMError`` (the caller decides how to handle a mid-run outage).

    A custom ``system`` prompt (a user-defined extractor) overrides the built-in keyword
    instruction; the parsing (one item per line, deduped, bounded) is SHARED, so every
    extractor — built-in or user-defined — yields the same unified, typed AI-metadata
    shape. ``{max_terms}`` is substituted in whichever system prompt is used.

    An article longer than the window is read in PARTS (2026-08-10 ruling) and the term
    lists merged round-robin, so ``max_terms`` remains a per-article budget spread
    across the whole article rather than a cap that lands entirely on its opening.
    ``budget_chars`` is an explicit override; the batch caller does not pass it, because
    the per-article half of the budget is that article's script (see
    ``coverage.sweep_text_budget``)."""
    text = (content or "").strip()
    if not text:
        return []
    base = system if (system and system.strip()) else _EXTRACT_SYSTEM
    sys_prompt = base.replace("{max_terms}", str(max_terms))

    from src.ai_layer.coverage import merge_items, split_for_sweep, sweep_text_budget

    basis: dict = {}
    if budget_chars and budget_chars > 0:
        budget = budget_chars
    else:
        budget, basis = sweep_text_budget(text)
    parts, _coverage = split_for_sweep(text, budget)
    options = sweep_options(num_ctx=basis.get("num_ctx"))

    head = f"Article title: {title or '(untitled)'}"
    per_part: list[list[str]] = []
    for part in parts:
        result = client.generate(
            f"{head}\n\n{part}",
            model=model,
            system=sys_prompt,
            options=options,
            keep_alive=keep_alive,
        )
        per_part.append(parse_terms(result.text, max_terms=max_terms))
    return merge_items(per_part, limit=max_terms)
