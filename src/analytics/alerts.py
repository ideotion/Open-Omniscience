"""Severity-tiered LOCAL alert layer (info / watch / urgent) — no network, no fabrication.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A single, transparent aggregation of the alert-shaped signals the app ALREADY has,
computed entirely from LOCAL data (never a network call, never a notification):

  * open-hazard records from the LOCAL cached snapshot (:mod:`src.hazards.store`) —
    tiered by the PROVIDER's own alert level (GDACS Green/Orange/Red → info/watch/
    urgent), which is the only place "urgent" ever comes from;
  * local WATCHES that recently fired (:mod:`src.analytics.watches`) — a "watch" tier
    because a fired watch is YOUR own saved condition crossing YOUR own threshold;
  * recent space-time CONVERGENCES (:mod:`src.analytics.convergence`) — an "info" tier
    because a convergence is a co-occurrence prompt to read, never proof of anything.

HONESTY (the non-negotiables, enforced by construction):
  * NO fabricated urgency. The engine never invents a tier: "urgent" is ONLY a
    provider-declared red hazard alert; "watch" is a provider orange alert OR your own
    fired watch; "info" is a provider green alert, a relayed observation, or a corpus
    convergence. The tier is a rule over REAL counts, not a computed score.
  * NO composite score — every figure is a count; the caveat + method travel with it.
  * NO network — hazards come from the local snapshot (which discloses its own age);
    "silence is not safety" rides the result.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

# Display / precedence order (least → most severe). "urgent" is the highest, and it is
# ONLY ever a provider-declared red hazard alert — we never promote a count into it.
TIERS: tuple[str, ...] = ("info", "watch", "urgent")
_PROVIDER_TIERS = frozenset(TIERS)

ALERT_METHOD = (
    "A transparent rule over real, locally-cached signals — no network call. Hazard "
    "records (cached from the open USGS/GDACS feeds; severity is the PROVIDER's own alert "
    "level) are tiered by that level: GDACS red → urgent, orange → watch, green/other → "
    "info. A local watch that fired is a 'watch' (your own saved threshold). A recent "
    "space-time convergence in your corpus is 'info'. Counts only — no fabricated "
    "urgency, no score."
)

ALERT_CAVEAT = (
    "This layer never invents urgency. 'Urgent' appears ONLY when a hazard provider "
    "(GDACS) itself declared a RED alert; 'watch' appears for a provider ORANGE alert or "
    "a watch YOU saved that crossed YOUR own threshold; 'info' is a provider GREEN alert, "
    "a relayed observation, or a recent space-time convergence in your corpus — a "
    "co-occurrence prompt, never proof of causation. Hazard records are a cached relay of "
    "what a watched feed reported (it may be stale, and it shows what a source reported, "
    "not everything that is happening) — silence is not safety. Counts only, no score."
)


def _hazard_tier(severity: str | None) -> str:
    """Map a hazard record's severity to a tier.

    GDACS records already carry info/watch/urgent (the provider's Green/Orange/Red scale
    in :mod:`src.hazards.parse`). Anything else — a USGS magnitude band, an unknown level —
    is a relayed OBSERVATION with no provider-declared urgency, so it is "info": we NEVER
    promote a magnitude into an urgency tier the provider did not declare.
    """
    s = (severity or "").strip().lower()
    return s if s in _PROVIDER_TIERS else "info"


def compute_alerts(
    session,
    *,
    now: datetime | None = None,
    within_hours: int = 48,
    convergence_lookback_days: int = 45,
    convergence_window_days: int = 7,
    convergence_limit: int = 5,
    hazard_max_age_hours: int = 48,
    snapshot: dict | None = None,
) -> dict:
    """Aggregate the local alert signals into info/watch/urgent tiers.

    ``snapshot`` (a :func:`src.hazards.store.load_snapshot` result) may be injected for
    tests; otherwise it is loaded from disk. All three inputs degrade LOUDLY: a failure in
    any one is logged and simply contributes nothing — the alert layer never blanks and
    never fabricates. Returns a structured dict (no score anywhere).
    """
    now = now or datetime.now(UTC)

    tiers: dict[str, dict] = {
        t: {"count": 0, "hazards": [], "watches": [], "convergences": [], "article_ids": set()}
        for t in TIERS
    }

    # 1) Hazards — from the LOCAL snapshot only (never the network).
    if snapshot is None:
        try:
            from src.hazards.store import load_snapshot

            snapshot = load_snapshot(max_age_hours=hazard_max_age_hours, now=now)
        except Exception:  # noqa: BLE001 - a snapshot problem must never break the alert
            _LOG.warning("hazards snapshot load failed", exc_info=True)
            snapshot = {"records": [], "saved_at": None, "age_hours": None, "stale": True, "available": False}
    # Batch-resolve the internal Article id per hazard event (one query, never
    # N+1) — 2026-07-24 field-feedback A6: hazards ingested as corpus Articles
    # can now deep-link to the local reader, like watches/convergences already do.
    hazard_article_by_url: dict[str, int] = {}
    records = snapshot.get("records", []) or []
    try:
        from src.database.models import Article
        from src.hazards.ingest import hazard_canonical_url

        urls = [
            hazard_canonical_url(str(r.get("source")), str(r.get("id")))
            for r in records
            if isinstance(r, dict) and r.get("source") and r.get("id")
        ]
        if urls:
            rows = (
                session.query(Article.canonical_url, Article.id)
                .filter(Article.canonical_url.in_(urls))
                .all()
            )
            hazard_article_by_url = {u: aid for u, aid in rows}
    except Exception:  # noqa: BLE001 - the article link is a bonus, never load-bearing
        hazard_article_by_url = {}

    for rec in records:
        if not isinstance(rec, dict):
            continue
        tier = _hazard_tier(rec.get("severity"))
        article_id = None
        if rec.get("source") and rec.get("id"):
            from src.hazards.ingest import hazard_canonical_url

            # str() defensively -- the snapshot body is an unvalidated posted dict
            # (HazardSnapshotBody.records: list[dict]), so a non-string source/id
            # must never crash this whole loop/producer (a skeptic-caught defect:
            # this call used to pass the raw values straight through, and this
            # function is NOT wrapped in a surrounding try/except unlike the
            # batch id-resolution block above it).
            article_id = hazard_article_by_url.get(
                hazard_canonical_url(str(rec["source"]), str(rec["id"]))
            )
        tiers[tier]["hazards"].append(
            {
                "title": rec.get("title"),
                "type": rec.get("type"),
                "place": rec.get("place"),
                "severity": rec.get("severity"),
                "source": rec.get("source"),
                "time": rec.get("time"),
                "url": rec.get("url"),
                # Item 4 (field-feedback A6, ruled): magnitude/lat/lon were being
                # dropped here even though the snapshot carries them -- restored,
                # never fabricated (absent stays None, e.g. GDACS non-quakes).
                "magnitude": rec.get("magnitude"),
                "lat": rec.get("lat"),
                "lon": rec.get("lon"),
                "article_id": article_id,
            }
        )
        if article_id is not None:
            tiers[tier]["article_ids"].add(article_id)

    # 2) Fired watches — a "watch" tier (your own saved threshold crossed).
    fired: list[dict] = []
    try:
        from src.analytics.watches import recent_fired_watches

        fired = recent_fired_watches(session, within_hours=within_hours)
    except Exception:  # noqa: BLE001 - a watch problem must never break the alert
        _LOG.warning("alert layer: fired-watches read failed", exc_info=True)
        fired = []
    for w in fired:
        tiers["watch"]["watches"].append(
            {
                "id": w.get("id"),
                "name": w.get("name"),
                "query": w.get("query"),
                "n_articles": w.get("n_articles"),
                "matched_at": w.get("matched_at"),
            }
        )
        tiers["watch"]["article_ids"].update(int(a) for a in (w.get("article_ids") or []))

    # 3) Recent space-time convergences — an "info" tier (a co-occurrence prompt).
    #    NOTE (bounded, conscious tradeoff): this repeats the scan the
    #    space_time_convergence Home producer already runs each briefing refresh, so a
    #    refresh pays it twice. It is a bounded read of the small (no-content) place/date
    #    tables over a RECENT lookback, on the background refresh thread — acceptable.
    #    The POLLED path no longer pays it per request: /api/signals/alerts is served
    #    through the background-refreshed memo cache in src.analytics.poll_cache (field
    #    test 2026-07-08, Item 8), so this scan runs on the background thread only.
    convergences: list[dict] = []
    try:
        from src.analytics.convergence import find_convergences

        found = find_convergences(
            session,
            window_days=convergence_window_days,
            lookback_days=convergence_lookback_days,
            limit=convergence_limit,
        )
        convergences = found.get("clusters", []) or []
    except Exception:  # noqa: BLE001 - a scan problem must never break the alert
        _LOG.warning("alert layer: convergence read failed", exc_info=True)
        convergences = []
    for c in convergences:
        tiers["info"]["convergences"].append(
            {
                "place": c.get("place"),
                "place_country": c.get("place_country"),
                "distinct_sources": c.get("distinct_sources"),
                "n_articles": c.get("n_articles"),
                "window_start": c.get("window_start"),
                "window_end": c.get("window_end"),
            }
        )
        tiers["info"]["article_ids"].update(int(a) for a in (c.get("article_ids") or []))

    for t in TIERS:
        tiers[t]["count"] = (
            len(tiers[t]["hazards"]) + len(tiers[t]["watches"]) + len(tiers[t]["convergences"])
        )
        tiers[t]["article_ids"] = sorted(tiers[t]["article_ids"])

    highest = None
    for t in reversed(TIERS):  # urgent, watch, info
        if tiers[t]["count"] > 0:
            highest = t
            break

    return {
        "tiers": tiers,
        "highest_tier": highest,
        "total": sum(tiers[t]["count"] for t in TIERS),
        "hazards_as_of": snapshot.get("saved_at"),
        "hazards_stale": bool(snapshot.get("stale", True)),
        "hazards_available": bool(snapshot.get("available", False)),
        "hazards_age_hours": snapshot.get("age_hours"),
        "sources_used": {
            "hazards": sum(len(tiers[t]["hazards"]) for t in TIERS),
            "watches": len(fired),
            "convergences": len(convergences),
        },
        "method": ALERT_METHOD,
        "caveat": ALERT_CAVEAT,
    }
