"""leads_quality diagnostic (Leads-calibration S6.1, 2026-07-18).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Exports the CURRENT Home Leads feed (the same ``run_all`` pass Home renders) as a
bounded, real-facts report -- producer type, key, bucket, title, n, the independent-
source count, the card's own disclosed ``signal`` fields verbatim, and the Leads-2.0
major-floor fact -- so the maintainer can re-run this on the live corpus and send it
back, exactly like the keyword-log measurement loop. Read-only: no new measurement,
no score, no fabricated metric; every row is a card's own disclosed facts.
"""

from __future__ import annotations

SCHEMA = "oo-leads-quality-1"

LEADS_QUALITY_METHOD = (
    "Every card the CURRENT Home Leads pass (briefing.registry.run_all) produces, "
    "with its own disclosed signal fields verbatim, its independent-source count "
    "(distinct non-empty evidence sources), and the Leads-2.0 major-floor fact. No "
    "new measurement is taken and no field is invented — this reads exactly what "
    "the feed already discloses. Re-run after a producer/calibration change and diff "
    "against a prior export to see precisely what moved."
)

LEADS_QUALITY_CAVEAT = (
    "A snapshot of the CURRENT feed at the moment this ran, not a historical record "
    "(dismissed cards and cross-refresh history are not carried here). Counts only; "
    "no composite score anywhere in this export."
)


def leads_quality_report(session) -> dict:
    """The bounded, real-facts export described in the module docstring."""
    from src.briefing.leads import _distinct_sources, is_major
    from src.briefing.registry import run_all

    cards = run_all(session)
    rows = []
    for c in cards:
        rows.append(
            {
                "type": c.type,
                "key": c.key,
                "bucket": c.bucket,
                "title": c.title,
                "n": c.n,
                "distinct_sources": _distinct_sources(c),
                "article_ids_count": len(c.article_ids or []),
                "signal": c.signal,
                "major": is_major(c),
            }
        )
    return {
        "schema": SCHEMA,
        "count": len(rows),
        "cards": rows,
        "method": LEADS_QUALITY_METHOD,
        "caveat": LEADS_QUALITY_CAVEAT,
    }
