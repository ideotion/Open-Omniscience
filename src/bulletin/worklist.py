"""Phase 2 as a plan you can read before you spend an hour on it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer's own design, 2026-08-11: "a solution to incorporating AI work in
bulletins could be done in 2 phases: 1 produce all AI-less content from what the
local database currently contains, then 2 detailed list all content and work that
the local AI would have to tackle to enhance the bulletin, as an option (appearing
after phase 1 has been produced)."

So phase 2 is not a toggle. It is a WORKLIST: given the phase-1 edition, exactly
what a local model would be asked to do, over which corpora, and how many calls
that is. The operator reads it and decides. On the CPU-only machines this app is
built for, a sweep over every card corpus is an hour of a saturated fan; a checkbox
that hides that is not consent.

PURE. It reads the edition dict and returns a plan — no DB, no model, no network,
nothing started. That is what lets the UI offer it the instant phase 1 lands, and
what makes the plan testable without a backend.

NO FABRICATED ETA. The call count is exact, because it is a count of things in the
record. A DURATION is offered only when the caller passes a per-call figure MEASURED
on this machine — nothing persists one today, so the honest default is to say the
count, name the instrument that would produce the number, and stop. A plan that
guessed "about ten minutes" on hardware it has never met would be the fabricated
figure this project refuses everywhere else.
"""

from __future__ import annotations

from typing import Any

# One model call per unit, for every kind below: a story is narrated once, a card's
# corpus is read once, an article is translated once. Stated as a constant rather
# than folded into the arithmetic so a future two-pass task cannot silently make the
# call count wrong.
CALLS_PER_UNIT = 1


def _stories_work(edition: dict) -> dict | None:
    """Narrating the deterministic story clusters — the one job Layer B already does."""
    stories = (edition.get("stories") or {}).get("stories") or []
    if not stories:
        return None
    already = sum(1 for s in stories if (s.get("narration") or {}).get("narrated"))
    todo = [s for s in stories if not (s.get("narration") or {}).get("narrated")]
    if not todo:
        return None
    return {
        "kind": "narrate_stories",
        "what": "One grounded paragraph per story cluster",
        "units": len(todo),
        "calls": len(todo) * CALLS_PER_UNIT,
        "corpora": [
            {
                "label": ", ".join((s.get("shared_terms") or [])[:4]) or "story",
                "articles": int(s.get("articles") or len(s.get("article_ids") or [])),
            }
            for s in todo
        ],
        "already_done": already,
        "adds": (
            "A sentence under each story, kept only if every figure and name in it "
            "appears in the articles the model was shown."
        ),
        "if_skipped": (
            "Each story keeps the deterministic sentence composed from its own counts. "
            "Nothing the record states is lost."
        ),
    }


def _cards_work(edition: dict) -> dict | None:
    """Reading each card's own corpus — the maintainer's "even if it takes time" job.

    A card whose selection is a query or a whole-corpus distribution has no fixed
    article set (``corpus_articles`` 0), so there is nothing for a model to read and
    it is not counted. Counting it would inflate the plan with work that cannot run.
    """
    section = next(
        (s for s in edition.get("sections") or [] if s.get("section") == "cards"), None
    )
    if not section:
        return None
    corpora = []
    for entry in section.get("types") or []:
        for card in entry.get("cards") or []:
            n = int(card.get("corpus_articles") or 0)
            if n <= 0:
                continue
            corpora.append(
                {
                    "label": f"{entry.get('type')}: {card.get('title')}",
                    "articles": n,
                }
            )
    if not corpora:
        return None
    return {
        "kind": "extract_from_card_corpora",
        "what": "Read each card's own articles and say what they contain",
        "units": len(corpora),
        "calls": len(corpora) * CALLS_PER_UNIT,
        "corpora": corpora,
        "articles_total": sum(c["articles"] for c in corpora),
        "adds": (
            "Per card, what its articles actually say — beyond the measurement that "
            "surfaced it. Stored as AI-derived candidates, marked unreliable, never "
            "folded into a figure."
        ),
        "if_skipped": (
            "Each card keeps its measured signal, its method, its caveat and its "
            "articles. The reader reads the articles themselves."
        ),
    }


def _translation_work(edition: dict, target_lang: str | None) -> dict | None:
    """Translating the articles the document names, when they are not in the target.

    Only articles the document actually NAMES are counted. Offering to translate the
    period's other 72,000 would be a plan for a different document.
    """
    if not target_lang:
        return None
    target = str(target_lang).lower()
    seen: dict[int, dict] = {}

    def _collect(rows: list[dict]) -> None:
        for a in rows or []:
            aid = a.get("id")
            if aid is None or aid in seen:
                continue
            asserted = (a.get("asserted") or {}).get("language")
            deduced = (a.get("deduced") or {}).get("detected_language")
            lang = (asserted or deduced or "").lower()
            # An article with NO language on either side is not assumed to need
            # translating and not assumed to be fine: it is listed separately, because
            # "we do not know" is not "it is already in your language".
            seen[aid] = {
                "id": aid,
                "title": a.get("title"),
                "language": lang or None,
                "needs": bool(lang) and not lang.startswith(target),
            }

    for section in edition.get("sections") or []:
        for entry in section.get("types") or []:
            for card in entry.get("cards") or []:
                _collect(card.get("article_rows") or [])
    for story in (edition.get("stories") or {}).get("stories") or []:
        _collect(story.get("article_rows") or [])

    todo = [a for a in seen.values() if a["needs"]]
    unknown = [a for a in seen.values() if a["language"] is None]
    if not todo and not unknown:
        return None
    return {
        "kind": "translate_named_articles",
        "what": f"Translate the articles this document names into {target_lang}",
        "units": len(todo),
        "calls": len(todo) * CALLS_PER_UNIT,
        "target_language": target_lang,
        "articles": todo[:50],
        "already_in_target": len(seen) - len(todo) - len(unknown),
        "language_unknown": len(unknown),
        "adds": (
            "A translation beside each named article, marked AI-derived. The original "
            "stays; a translation never replaces what the publisher wrote."
        ),
        "if_skipped": (
            "The articles stay in the language they were published in, which is what "
            "the corpus holds."
        ),
    }


def ai_worklist(
    edition: dict,
    *,
    target_lang: str | None = None,
    per_call_s: float | None = None,
    concurrency: int = 1,
) -> dict:
    """What a local model would be asked to do for this edition, and how much of it.

    ``per_call_s`` must be a figure MEASURED on this machine (Settings → Advanced →
    Diagnostics → LLM latency bench). Without it the plan reports calls and refuses
    to report a duration.
    """
    jobs = [
        j
        for j in (
            _stories_work(edition),
            _cards_work(edition),
            _translation_work(edition, target_lang),
        )
        if j
    ]
    calls = sum(int(j["calls"]) for j in jobs)

    duration: dict[str, Any]
    if per_call_s and calls:
        lanes = max(1, int(concurrency))
        seconds = (calls * float(per_call_s)) / lanes
        duration = {
            "known": True,
            "seconds": round(seconds, 1),
            "per_call_s": float(per_call_s),
            "concurrency": lanes,
            "method": (
                f"{calls} calls x {per_call_s}s measured per call, divided by "
                f"{lanes} lane(s). A measurement of this machine, not an estimate of it."
            ),
        }
    else:
        duration = {
            "known": False,
            "seconds": None,
            "reason": (
                "No per-call latency has been measured on this machine, so no duration "
                "is offered. Settings → Advanced → Diagnostics → the LLM latency bench "
                "produces one; nothing persists it yet, so it has to be supplied."
            ),
        }

    return {
        "section": "ai_worklist",
        "phase": 2,
        "ran": False,
        "jobs": jobs,
        "calls_total": calls,
        "duration": duration,
        "method": (
            "counted from the phase-1 record: one call per story to narrate, one per "
            "card corpus to read, one per named article to translate. Cards whose "
            "selection is a query rather than a fixed article set carry no corpus and "
            "are not counted, because there is nothing for a model to read."
        ),
        "caveat": (
            "A PLAN, not a result — nothing here has run, and phase 1 above is a "
            "complete document without any of it. Everything this would add is stored "
            "as AI-derived and marked unreliable: a model's sentence never becomes one "
            "of the figures, and removing the layer leaves the record intact. On a "
            "machine without a dedicated GPU this work is slow and will keep every core "
            "busy for as long as it runs, which is why it is a list you approve rather "
            "than a switch that starts."
        ),
    }
