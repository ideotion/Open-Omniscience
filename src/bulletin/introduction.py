"""
The edition's introduction — Layer B over the edition's own figures.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §20 question 2, RULED by the maintainer 2026-09-07: **narrated by
the model**, chosen over a templated opening and over none at all.

THE FALLBACK IS NOT A HEDGE. It is the same §8 rule every other Layer-B sentence
obeys — a model failure, an empty answer, or a paragraph whose sentences fail the
grounding check resolves to a deterministic template with the reason recorded.
Without it a document produced below the hardware gate, or in airplane mode, or on
a machine whose model is down would simply *open with nothing*, and §2's own
argument against calling this feature an "AI summary" — that the artifact must not
be named for output it may not contain — applies just as hard to its first
paragraph.

WHAT THE MODEL IS GIVEN, and it is not article text: the edition's OWN figures.
The introduction describes the shape of the period — how much was collected, from
how many sources, how concentrated, how many days had any ingest at all — and
every one of those numbers is Layer A's. So the evidence corpus for the grounding
check is the fact bundle itself, and a figure the model invents is a figure that
does not appear in it and the sentence is dropped. The model is never asked which
subject mattered: that is the "top story" §11 refuses, and no number here can be
turned into one.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_LOG = logging.getLogger(__name__)

INTRODUCTION_PROMPT_VERSION = "bulletin-introduction-v1"

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_SYSTEM = (
    "You write the opening paragraph of a periodic document built from one "
    "person's own news archive.\n"
    "You are given the archive's measurements for the period. Write 2 to 3 plain "
    "sentences describing the SHAPE of what was collected.\n"
    "RULES:\n"
    "- Use ONLY the figures given. Do not add any number that is not listed.\n"
    "- Do not say any subject was important, major, dominant or notable.\n"
    "- Do not name a leading story, a top topic or a most-covered subject.\n"
    "- Do not speculate about why anything was or was not collected.\n"
    "- No heading, no greeting, no closing line. Sentences only."
)


def _fmt(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def introduction_facts(edition: dict) -> dict:
    """The figures the introduction may speak about — and only these.

    Drawn from the masthead and the period, never recomputed: the introduction has
    to agree with the document under it, and a second derivation is how two
    surfaces come to disagree about one number.
    """
    head = edition.get("masthead") or {}
    period = edition.get("period") or {}
    sections = [s for s in (edition.get("sections") or []) if isinstance(s, dict)]
    stories = (edition.get("stories") or {}).get("stories") or []
    langs = head.get("languages") or []
    return {
        "cadence": str(period.get("cadence") or ""),
        "start": str(period.get("start") or ""),
        "end": str(period.get("end") or ""),
        "days": period.get("days"),
        "articles": head.get("articles"),
        "corpus_articles": head.get("corpus_articles"),
        "sources_contributing": head.get("sources_contributing"),
        "top_3_share": head.get("top_3_share"),
        "languages": len(langs),
        "source_countries": len(head.get("source_countries") or []),
        "days_with_ingest": head.get("days_with_ingest"),
        "period_days": head.get("period_days") or period.get("days"),
        "sections": len(sections),
        "stories": len(stories),
    }


def facts_text(facts: dict) -> str:
    """The bundle as the model sees it — and as the grounding check reads it.

    ONE rendering feeds both, so a figure the checker cannot find is a figure the
    model was never shown. Two renderings would let an invented number be "found"
    in a bundle the model never received.
    """
    lines = [
        f"Period: {facts['cadence']} covering {facts['start']} to {facts['end']} "
        f"({_fmt(facts['days'])} days).",
        f"Articles collected in the period: {_fmt(facts['articles'])}.",
        f"Articles in the whole archive: {_fmt(facts['corpus_articles'])}.",
        f"Sources that contributed at least one article: {_fmt(facts['sources_contributing'])}.",
        f"Languages present: {_fmt(facts['languages'])}.",
        f"Source countries present: {_fmt(facts['source_countries'])}.",
        f"Days with any collection at all: {_fmt(facts['days_with_ingest'])} "
        f"of {_fmt(facts['period_days'])}.",
        f"Sections in this document: {_fmt(facts['sections'])}.",
        f"Story clusters found: {_fmt(facts['stories'])}.",
    ]
    share = facts.get("top_3_share")
    if isinstance(share, (int, float)):
        lines.append(
            f"Share of the period's articles carried by its three largest sources: "
            f"{round(float(share) * 100)} per cent."
        )
    return "\n".join(lines)


def deterministic_introduction(edition: dict) -> str:
    """The opening the document gets with no model, or when the model's is rejected.

    Entirely Layer A's own counts, which is the point: it is what the document says
    without a model, so the model's absence costs style and never substance.
    """
    f = introduction_facts(edition)
    bits = [
        f"This {f['cadence'] or 'period'} edition covers {f['start']} to {f['end']} "
        f"and describes {_fmt(f['articles'])} articles collected from "
        f"{_fmt(f['sources_contributing'])} sources."
    ]
    if f.get("days_with_ingest") is not None and f.get("period_days"):
        bits.append(
            f"Collection happened on {_fmt(f['days_with_ingest'])} of the period's "
            f"{_fmt(f['period_days'])} days."
        )
    if f.get("languages"):
        bits.append(
            f"The articles are in {_fmt(f['languages'])} languages from "
            f"{_fmt(f['source_countries'])} source countries."
        )
    bits.append(
        "What follows is the record: exact counts with the method beside each one, "
        "and no judgement about which of them matters."
    )
    return " ".join(bits)


def _base(edition: dict, *, model: str, backend: str, language: str | None) -> dict:
    return {
        "unit": "introduction",
        "model": model,
        "backend": backend,
        "prompt_version": INTRODUCTION_PROMPT_VERSION,
        "language": language,
    }


def narrate_introduction(
    edition: dict,
    *,
    client,
    model: str,
    backend: str,
    language: str | None = None,
    options: dict | None = None,
) -> dict:
    """Narrate the opening paragraph, checking every sentence before keeping it.

    Same contract as ``narration.narrate_story``: the returned block always carries
    a ``text``, so the document is never left with a gap where a model should have
    been, and ``narrated`` says which of the two produced it.
    """
    from src.bulletin.grounding import check_sentence
    from src.bulletin.narration import DEFAULT_OPTIONS

    facts = introduction_facts(edition)
    evidence = facts_text(facts)
    base = _base(edition, model=model, backend=backend, language=language)
    base["facts"] = facts

    prompt = (
        "Measurements for the period:\n\n"
        + evidence
        + "\n\nWrite 2 to 3 sentences describing the shape of what was collected. "
        "Use only the figures above. Name no leading subject."
    )

    try:
        result = client.generate(
            prompt, model=model, system=_SYSTEM, options=dict(options or DEFAULT_OPTIONS)
        )
        raw = (getattr(result, "text", "") or "").strip()
    except Exception as exc:  # noqa: BLE001 - a model failure degrades to the template
        _LOG.warning("bulletin: introduction narration failed", exc_info=True)
        return {
            **base,
            "text": deterministic_introduction(edition),
            "narrated": False,
            "fallback_reason": f"the model call failed: {type(exc).__name__}: {exc}",
            "sentences": [],
        }

    if not raw:
        return {
            **base,
            "text": deterministic_introduction(edition),
            "narrated": False,
            "fallback_reason": "the model returned nothing",
            "sentences": [],
        }

    kept: list[str] = []
    sentences: list[dict] = []
    for sentence in [s.strip() for s in _SENTENCE_SPLIT.split(raw) if s.strip()]:
        verdict = check_sentence(sentence, evidence, language=language)
        sentences.append(
            {
                "text": sentence,
                "kept": verdict["supported"],
                "checks_applied": verdict["checks_applied"],
                "unsupported": verdict["unsupported"],
                "reason": None
                if verdict["supported"]
                else "dropped: " + "; ".join(verdict["unsupported"]),
            }
        )
        if verdict["supported"]:
            kept.append(sentence)

    if not kept:
        return {
            **base,
            "text": deterministic_introduction(edition),
            "narrated": False,
            "fallback_reason": (
                "every generated sentence carried a figure that is not among the "
                "edition's own"
            ),
            "sentences": sentences,
            "raw": raw,
        }

    dropped = [s for s in sentences if not s["kept"]]
    return {
        **base,
        "text": " ".join(kept),
        "narrated": True,
        "sentences": sentences,
        "sentences_kept": len(kept),
        "sentences_dropped": len(dropped),
        "partial": bool(dropped),
        "method": (
            "one constrained call over the edition's own masthead and period figures, "
            "temperature 0; every sentence checked against those same figures before it "
            "is kept, and a paragraph whose sentences all fail falls back to a "
            "deterministic template composed from the same numbers"
        ),
        "caveat": (
            "AI-derived — unreliable. This paragraph was written by a local model and "
            "kept only because every figure in it is one of the edition's own. That "
            "check catches invented figures; it does not catch real figures arranged "
            "into a false impression. It names no leading subject, because choosing one "
            "is the composite judgement this document does not make."
        ),
    }


def deterministic_block(edition: dict, reason: str) -> dict:
    """The introduction with no model reached at all, in the same shape.

    Same-shape rather than absent: a renderer that has to branch on whether the key
    exists will one day forget, and an introduction that silently disappears is the
    document opening on its first section with nothing to say why.
    """
    return {
        "unit": "introduction",
        "text": deterministic_introduction(edition),
        "narrated": False,
        "fallback_reason": reason,
        "sentences": [],
        "prompt_version": INTRODUCTION_PROMPT_VERSION,
        "method": (
            "no model was reached; the opening is composed from the edition's own "
            "counts by a fixed template"
        ),
        "caveat": (
            "No model output is present in this paragraph. It states the same figures "
            "the document does, in a fixed form."
        ),
    }
