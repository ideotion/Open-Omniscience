"""The card system in the bulletin — grouped by type, with each card's own corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask, 2026-08-11: "another section per card type, but describing a card
content is not sufficient, producing a bulletin should automate AI content
extraction from each card's corpus".

This is the deterministic half — phase 1 in the maintainer's own two-phase design.
Thirty-nine producers surface the app's signal layer and none of them appeared in
the bulletin. Each card already carries exactly what a document needs: a measured
signal, the method that produced it, the caveat that bounds it, an n, and — for the
set-based cards — the EXACT article ids it was built from. Those ids are what phase
2 will hand a local model; here they become the articles a reader can see.

ONE HONESTY PROBLEM, STATED RATHER THAN HIDDEN. Every other section in this
edition is anchored to the period's closed window, which is what makes it
reproducible: ask again next month and you get the same numbers. Card producers
take no period — ``run_all_bounded(session)`` has no ``end`` — so they compute
against whatever "now" is when the edition is generated, each with its own window.
That is not a defect to paper over with a period label the numbers do not have. The
section declares that its cards are AS OBSERVED AT GENERATION, and the edition JSON
is what makes them reproducible: the record holds the cards, so re-rendering shows
the same ones even though re-computing would not. That is already how ``stories``
works.

THE BUDGET IS A ``break``, NOT A TIMEOUT. ``run_all_bounded``'s own docstring
records why: an all-diagnostics run once sat 69 minutes inside a member that called
it, because a statement deadline raised, the per-producer isolation caught it, and
the loop moved on to do it again — once per producer. A deadline that the isolation
can intercept is not a budget. The truncation it returns is reported here rather
than absorbed, so a document built from 20 of 39 producers says so.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.bulletin.articles import ARTICLE_CAVEAT, article_rows
from src.bulletin.period import Period

_LOG = logging.getLogger(__name__)

# Wall-clock the producers may take. Generous: a bulletin is generated once, not
# polled, and the alternative to a slow card is no card.
DEFAULT_BUDGET_S = 240.0
DEFAULT_CARDS_PER_TYPE = 3
DEFAULT_ARTICLES_PER_CARD = 4

_CAVEAT = (
    "Cards are AS OBSERVED WHEN THIS EDITION WAS GENERATED, not for the period above. "
    "Each producer uses its own window and states it in its own method, so these are "
    "the only figures in this document that are not anchored to the period — asking "
    "again tomorrow would give different cards. What makes them reproducible is the "
    "record: this edition holds them, so re-rendering it shows exactly these. Every "
    "card carries the measurement that surfaced it, never a blended score, and a card "
    "is a prompt to look rather than a finding: absence of a card is not absence of "
    "the thing it would have surfaced."
)


def _signal_line(signal: dict) -> str:
    """A card's measured quantities as ``label value`` pairs, unblended.

    A card's signal is a dict of separate measurements on purpose — the schema
    forbids a composite — so it is printed as separate measurements.
    """
    if not isinstance(signal, dict):
        return ""
    parts = []
    for k, v in signal.items():
        if v is None or isinstance(v, (list, dict)):
            continue
        parts.append(f"{str(k).replace('_', ' ')} {v}")
    return " · ".join(parts)


def _signal_pairs(signal: dict) -> list[list[str]]:
    """The same measurements, UNJOINED: ``[label, value]`` per pair.

    The label is chrome (fixed, keyable, translatable); the value is data. Composing
    them into one string — what ``_signal_line`` does — welds the two together, and a
    welded "distinct sources 3" can never match a catalog key, so the labels could not
    be translated at all and the composed line sat in the coverage denominator forever.

    Kept ALONGSIDE ``signal_line`` rather than replacing it: editions already on disk
    carry only the composed form, and a renderer must still be able to print those.
    """
    if not isinstance(signal, dict):
        return []
    out: list[list[str]] = []
    for k, v in signal.items():
        if v is None or isinstance(v, (list, dict)):
            continue
        out.append([str(k).replace("_", " "), str(v)])
    return out


def cards_by_type(
    session,
    period: Period,
    *,
    budget_s: float = DEFAULT_BUDGET_S,
    per_type: int = DEFAULT_CARDS_PER_TYPE,
    articles_per_card: int = DEFAULT_ARTICLES_PER_CARD,
    excerpt_chars: int | None = None,
) -> dict:
    """Every producer's cards, grouped by card type, each with its own articles."""
    from src.briefing.registry import run_all_bounded

    deadline = time.monotonic() + float(budget_s)
    try:
        cards, stats = run_all_bounded(session, deadline=deadline)
    except Exception as exc:  # noqa: BLE001 - the record survives the card layer
        _LOG.warning("bulletin: the card layer failed", exc_info=True)
        return {
            "section": "cards",
            "error": f"{type(exc).__name__}: {exc}",
            "caveat": _CAVEAT,
        }

    grouped: dict[str, list[Any]] = {}
    for c in cards:
        grouped.setdefault(str(c.type), []).append(c)

    types: list[dict] = []
    for card_type in sorted(grouped):
        picked = grouped[card_type][: int(per_type)]
        rendered: list[dict] = []
        for c in picked:
            ids = list(c.article_ids or [])
            row: dict[str, Any] = {
                "title": c.title,
                "summary": c.summary,
                "bucket": c.bucket,
                "signal": dict(c.signal or {}),
                "signal_line": _signal_line(c.signal or {}),
                "signal_pairs": _signal_pairs(c.signal or {}),
                "method": c.method,
                "caveat": c.caveat,
                "n": c.n,
                "observed_at": c.created_at,
                # The full set is what phase 2 would read; the DESCRIBED subset is
                # what the document shows. Both counts travel, so a reader can see
                # that a card built from 115 articles is showing four of them.
                "corpus_articles": len(ids),
                "article_rows": article_rows(
                    session,
                    ids,
                    limit=int(articles_per_card),
                    **({"excerpt_chars": int(excerpt_chars)} if excerpt_chars is not None else {}),
                )
                if ids
                else [],
            }
            if c.trigger:
                row["trigger"] = c.trigger
            rendered.append(row)
        types.append(
            {
                "type": card_type,
                "cards_found": len(grouped[card_type]),
                "cards_shown": len(rendered),
                "cards": rendered,
            }
        )

    return {
        "section": "cards",
        "types": types,
        "cards_found": len(cards),
        "card_types": len(grouped),
        "producers_run": stats.get("producers_run"),
        "producers_total": stats.get("producers_total"),
        # Reported, never absorbed: a document built from half the producers must say
        # so, or a short feed reads as a quiet period.
        "truncated": bool(stats.get("truncated")),
        "per_type": int(per_type),
        "window": {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "days": period.days,
            # The one section in the edition whose figures are NOT the period's.
            "matches_period": False,
        },
        "method": (
            "every enabled card producer, run once at generation time under a wall-clock "
            "budget that stops starting new ones rather than interrupting one; grouped by "
            "card type, each card carrying the measurement that surfaced it, its own "
            "method and caveat, its n, and the articles it was built from where the card "
            "identifies a set. Producers a card producer disabled in Settings are not run."
        ),
        "caveat": _CAVEAT + " " + ARTICLE_CAVEAT,
    }


def build(session, period: Period, ctx: dict) -> dict:
    return cards_by_type(
        session,
        period,
        budget_s=float(ctx.get("cards_budget_s", DEFAULT_BUDGET_S)),
        per_type=int(ctx.get("cards_per_type", DEFAULT_CARDS_PER_TYPE)),
        articles_per_card=int(ctx.get("cards_articles", DEFAULT_ARTICLES_PER_CARD)),
    )
