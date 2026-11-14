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


def _row(c) -> dict:
    """One card's row. ``c`` is a Card, or a cached card dict wrapped so the same leads.py helpers read it."""
    from src.briefing.leads import _distinct_outlets, is_major

    return {
        "type": c.type,
        "key": c.key,
        "bucket": c.bucket,
        "title": c.title,
        "n": c.n,
        "distinct_outlets": _distinct_outlets(c),
        "article_ids_count": len(c.article_ids or []),
        "signal": c.signal,
        "major": is_major(c),
    }


def _fresh_home_feed(session) -> dict | None:
    """Home's cached feed when it describes the corpus as it is now, else ``None``.

    Fresh means the same test Home itself applies before serving the cache: the corpus has not grown
    past the stale threshold since the feed was computed. A feed that a refresh stopped early, or one
    a refresh kept because it could not finish, is still served by Home and is used here too; its
    markers travel into the report so the reader sees it was partial."""
    from src.briefing.service import _is_cache_stale, _read_cache

    payload = _read_cache()
    if not payload or not isinstance(payload.get("cards"), list):
        return None
    if _is_cache_stale(session, payload):
        return None
    return payload


def _report_from_home_feed(payload: dict) -> dict:
    from types import SimpleNamespace

    rows = []
    for d in payload["cards"]:
        if not isinstance(d, dict):
            continue
        c = SimpleNamespace(
            type=d.get("type"), key=d.get("key"), bucket=d.get("bucket"), title=d.get("title"),
            n=d.get("n"), article_ids=d.get("article_ids"), signal=d.get("signal"),
            evidence=d.get("evidence") or [],
        )
        rows.append(_row(c))
    generated_at = payload.get("generated_at")
    note = (
        f"Read from Home's cached feed, computed at {generated_at}, instead of running every card "
        "producer again: the corpus has not grown enough since then for Home to call that feed stale. "
        "These are the cards Home is showing now, which include the one lane-only producer's card "
        "(osm_tag_completeness) that a fresh run of this report leaves out. For a fresh producer pass, "
        "call /api/diagnostics/leads-quality on its own."
    )
    partial = payload.get("incomplete_reason") or payload.get("kept_reason")
    caveat = LEADS_QUALITY_CAVEAT
    if partial:
        caveat += (
            " PARTIAL: Home's last refresh did not finish every producer, so cards from the "
            f"producers it did not reach are absent here ({partial})."
        )
    out = {
        "schema": SCHEMA,
        "count": len(rows),
        "cards": rows,
        "source": "home-cache",
        "feed_generated_at": generated_at,
        "source_note": note,
        "bundle_note": note,
        "producers_run": None,
        "producers_total": None,
        "truncated": bool(partial),
        "method": LEADS_QUALITY_METHOD,
        "caveat": caveat,
    }
    if payload.get("stopped_producers"):
        out["stopped_producers"] = payload["stopped_producers"]
    return out


def leads_quality_report(session, *, budget_s: float | None = None, prefer_home_cache: bool = False) -> dict:
    """The bounded, real-facts export described in the module docstring.

    ``budget_s`` caps how long the underlying producer pass may run. It exists because
    this member hung an all-diagnostics run for 69 minutes on a ~1M-article corpus: the
    pass is the whole Home Leads feed, its cost scales with the corpus, and the
    statement deadline wrapped around it could not bound it (see
    :func:`~src.briefing.registry.run_all_bounded`). A truncated pass is reported AS
    truncated, with the count -- a partial feed labelled partial is a usable
    measurement, an unbounded one is a hung export.

    ``prefer_home_cache`` (the all-diagnostics member, row 18 of the 2026-11-14 list): when Home's
    cached feed is fresh, report from it instead of running every producer again. The same bundle
    runs the producers in card-audit and in the bulletin, and this pass alone measured 86 s on a
    200k-article corpus. The report says which source it used (``source``), and in plain words
    why; with no fresh feed it runs the producers as before (``source: "producer-pass"``).
    """
    import time

    from src.briefing.registry import run_all_bounded

    if prefer_home_cache:
        try:
            payload = _fresh_home_feed(session)
        except Exception:  # noqa: BLE001 - an unreadable cache falls back to the producer pass
            payload = None
        if payload is not None:
            return _report_from_home_feed(payload)

    cards, stats = run_all_bounded(
        session,
        deadline=(time.monotonic() + budget_s) if budget_s else None,
    )
    rows = [_row(c) for c in cards]
    caveat = LEADS_QUALITY_CAVEAT
    if stats["truncated"]:
        # Said in the payload, not only in a log: a reader comparing two exports must be
        # able to see that this one covers fewer producers, or the diff reads as cards
        # having disappeared from the feed.
        caveat += (
            f" TRUNCATED: the producer pass was stopped after {stats['producers_run']} of "
            f"{stats['producers_total']} producers by a {budget_s:.0f}s budget, so cards "
            "from the producers that did not run are ABSENT here — that is a limit of "
            "this export, not a change in the feed."
        )
    return {
        "schema": SCHEMA,
        "count": len(rows),
        "cards": rows,
        "source": "producer-pass",
        "producers_run": stats["producers_run"],
        "producers_total": stats["producers_total"],
        "truncated": stats["truncated"],
        "method": LEADS_QUALITY_METHOD,
        "caveat": caveat,
    }
