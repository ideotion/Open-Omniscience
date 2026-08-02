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
    "urgency, no score. WITHIN a tier, hazards are ORDERED by the provider's own "
    "declared facts (its alert level, then its measured magnitude, then recency), and "
    "the ones at or above the stated magnitude floor are marked 'major' so the compact "
    "strip can show them first. That is an ordering over measurements, never an urgency "
    "claim: the tier itself is unchanged, and every event stays in this payload, on the "
    "World map and behind 'Open corpus'. One event relayed by BOTH providers is shown "
    "once, with both providers named — a deduced grouping (same hazard type, within "
    "0.5° and 2 hours), never a merge of the stored records."
)

ALERT_CAVEAT = (
    "This layer never invents urgency. 'Urgent' appears ONLY when a hazard provider "
    "(GDACS) itself declared a RED alert; 'watch' appears for a provider ORANGE alert or "
    "a watch YOU saved that crossed YOUR own threshold; 'info' is a provider GREEN alert, "
    "a relayed observation, or a recent space-time convergence in your corpus — a "
    "co-occurrence prompt, never proof of causation. Hazard records are a cached relay of "
    "what a watched feed reported (it may be stale, and it shows what a source reported, "
    "not everything that is happening) — silence is not safety. Counts only, no score. "
    "A magnitude BAND is the provider's own measurement of size, not a statement about "
    "consequences: a large quake far from people can matter less than a smaller one "
    "beneath a city, which is exactly why a magnitude is never promoted into an urgency "
    "tier. Grouping two providers' reports of one event is a deduction from coordinates "
    "and time, not a provider statement."
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


# --------------------------------------------------------------------------- #
#  The DISPLAY layer (2026-08-01 field impressions, rulings 1-3).
#
#  The maintainer's report: "a 6.8 magnitude earthquake in Japan … is distilled
#  amongst other less relevant, smaller earthquakes". Every USGS quake lands in
#  "info" (correctly — the provider declared no urgency), and the tier was then
#  rendered in raw snapshot order, so the largest event sat wherever the feed
#  happened to put it.
#
#  What changes is ORDERING and what the strip SHOWS FIRST — never the tier.
#  `_hazard_tier` above is untouched: a magnitude still never becomes urgency.
#  A magnitude BAND is a provider-declared measurement, and ordering by one is
#  the same honest-ordering doctrine the Leads order_key already uses. Every
#  event stays in the payload, on the map, and behind "Open corpus" — the floor
#  decides what is shown FIRST, never what exists.
# --------------------------------------------------------------------------- #

#: USGS bands (src.hazards.parse._quake_band) at or above "strong" (M>=6).
MAJOR_QUAKE_BANDS: frozenset[str] = frozenset({"strong", "major"})
#: Provider-declared levels that clear the floor by themselves (GDACS orange/red).
MAJOR_PROVIDER_TIERS: frozenset[str] = frozenset({"watch", "urgent"})
#: Default magnitude floor. 6.0 = the USGS "strong" band's own lower bound, so the
#: numeric floor and the band vocabulary agree instead of drifting apart.
DEFAULT_MIN_MAGNITUDE = 6.0
#: How many major hazards the Home strip shows before the "N more" overflow line.
DEFAULT_STRIP_CAP = 5
#: Conservative same-event grouping thresholds (ruling 3).
GROUP_MAX_DEGREES = 0.5
GROUP_MAX_HOURS = 2.0

_TIER_RANK = {"urgent": 3, "watch": 2, "info": 1}

#: Stated SAFE RANGE for the operator-set floor (settings ruling 3: a tunable
#: always shows its range, and an out-of-range value is reported, never silently
#: clamped into a different meaning). Below 4.5 the "major" set stops being a
#: short list at all; above 8 almost nothing on Earth clears it in a given year.
MIN_MAGNITUDE_RANGE = (4.5, 8.0)
STRIP_CAP_RANGE = (1, 20)


def configured_min_magnitude(default: float = DEFAULT_MIN_MAGNITUDE) -> float:
    """The operator's magnitude floor from Settings → Cards, clamped to the stated
    safe range. Any read problem degrades to the documented default — a settings
    failure must never silently widen or narrow what the strip surfaces."""
    try:
        from src.config.app_settings import load_settings

        raw = (load_settings().card_settings or {}).get("severity_alerts", {})
        val = _as_float(raw.get("min_magnitude"))
    except Exception:  # noqa: BLE001 - settings are advisory here, never load-bearing
        return default
    if val is None:
        return default
    lo, hi = MIN_MAGNITUDE_RANGE
    return min(max(val, lo), hi)


def configured_strip_cap(default: int = DEFAULT_STRIP_CAP) -> int:
    """How many hazards the compact strip lists before the overflow line, from
    Settings → Cards and clamped to its stated safe range."""
    try:
        from src.config.app_settings import load_settings

        raw = (load_settings().card_settings or {}).get("severity_alerts", {})
        val = _as_float(raw.get("strip_cap"))
    except Exception:  # noqa: BLE001 - advisory, never load-bearing
        return default
    if val is None:
        return default
    lo, hi = STRIP_CAP_RANGE
    return int(min(max(val, lo), hi))


def _as_float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is not a measurement


def _parse_time(v) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def quake_band(rec: dict) -> str | None:
    """The USGS magnitude BAND carried in ``severity`` for non-GDACS records.

    USGS records store their coarse band (major/strong/moderate/minor/unknown) in the
    same ``severity`` field GDACS uses for its alert level, so a band is exactly "a
    severity that is not a provider tier". Returns None when the record has no band.
    """
    s = (rec.get("severity") or "").strip().lower()
    if not s or s in _PROVIDER_TIERS or s == "unknown":
        return None
    return s


def is_major(rec: dict, min_magnitude: float = DEFAULT_MIN_MAGNITUDE) -> bool:
    """Does this hazard clear the DISPLAY floor?

    True when the provider declared orange/red, OR when the provider's own measured
    magnitude reaches ``min_magnitude``, OR when its band is strong/major. All three
    are provider-declared facts — this is a display floor, never an urgency claim.
    """
    if (rec.get("severity") or "").strip().lower() in MAJOR_PROVIDER_TIERS:
        return True
    mag = _as_float(rec.get("magnitude"))
    if mag is not None and mag >= min_magnitude:
        return True
    return quake_band(rec) in MAJOR_QUAKE_BANDS


def _order_key(rec: dict):
    """Within-tier ordering by PROVIDER-declared facts, most notable first.

    Provider level, then measured magnitude, then recency. A record with no magnitude
    is not ranked as if it had one (GDACS carries none) — it simply sorts after the
    measured ones at the same level, which is an absence, not a low value.
    """
    tier = _TIER_RANK.get((rec.get("severity") or "").strip().lower(), 0)
    mag = _as_float(rec.get("magnitude"))
    when = _parse_time(rec.get("time"))
    return (
        -tier,
        0 if mag is not None else 1,
        -(mag if mag is not None else 0.0),
        -(when.timestamp() if when else 0.0),
    )


def _same_event(a: dict, b: dict) -> bool:
    """Conservative same-event test (ruling 3): same hazard TYPE, within half a
    degree, within two hours. Deliberately narrow — this is a DISPLAY grouping, and
    a wrong merge would hide a real second event. Aftershock clustering is explicitly
    NOT attempted."""
    ta, tb = (a.get("type") or "").strip().lower(), (b.get("type") or "").strip().lower()
    if not ta or ta != tb:
        return False
    la, oa = _as_float(a.get("lat")), _as_float(a.get("lon"))
    lb, ob = _as_float(b.get("lat")), _as_float(b.get("lon"))
    if None in (la, oa, lb, ob):
        return False
    if abs(la - lb) > GROUP_MAX_DEGREES or abs(oa - ob) > GROUP_MAX_DEGREES:  # type: ignore[operator]
        return False
    wa, wb = _parse_time(a.get("time")), _parse_time(b.get("time"))
    if wa is None or wb is None:
        return False
    return abs((wa - wb).total_seconds()) <= GROUP_MAX_HOURS * 3600.0


def group_same_events(hazards: list[dict]) -> list[dict]:
    """Group cross-provider duplicates of one event for DISPLAY only.

    One earthquake is commonly relayed by BOTH USGS and GDACS, and the strip showed it
    twice. The grouped entry keeps the richest provider-declared values (a magnitude
    exists only on the USGS side) and lists every contributing provider, flagged
    ``grouped`` so the UI can label it a DEDUCED grouping. The underlying snapshot
    records and their Articles stay 1:1 per provider event — nothing is merged in
    storage, and no article id is lost.
    """
    out: list[dict] = []
    for rec in hazards:
        for existing in out:
            if _same_event(existing, rec):
                existing["grouped"] = True
                for p in (rec.get("providers") or [rec.get("source")]):
                    if p and p not in existing["providers"]:
                        existing["providers"].append(p)
                if _as_float(existing.get("magnitude")) is None:
                    existing["magnitude"] = rec.get("magnitude")
                if not existing.get("place"):
                    existing["place"] = rec.get("place")
                # A raw snapshot record carries article_id (singular); only an
                # already-merged entry carries article_ids. Read BOTH, or the
                # second provider's local article is silently dropped and the
                # group's "Open corpus" loses half its evidence.
                incoming = list(rec.get("article_ids") or [])
                if rec.get("article_id") is not None:
                    incoming.append(rec["article_id"])
                for aid in incoming:
                    if aid not in existing["article_ids"]:
                        existing["article_ids"].append(aid)
                # keep the strongest provider level of the group
                if _TIER_RANK.get((rec.get("severity") or "").lower(), 0) > _TIER_RANK.get(
                    (existing.get("severity") or "").lower(), 0
                ):
                    existing["severity"] = rec.get("severity")
                break
        else:
            merged = dict(rec)
            merged["providers"] = [rec["source"]] if rec.get("source") else []
            merged["article_ids"] = [rec["article_id"]] if rec.get("article_id") is not None else []
            merged.setdefault("grouped", False)
            out.append(merged)
    return out


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
    min_magnitude: float | None = None,
    group_events: bool = True,
) -> dict:
    """Aggregate the local alert signals into info/watch/urgent tiers.

    ``snapshot`` (a :func:`src.hazards.store.load_snapshot` result) may be injected for
    tests; otherwise it is loaded from disk. All three inputs degrade LOUDLY: a failure in
    any one is logged and simply contributes nothing — the alert layer never blanks and
    never fabricates. Returns a structured dict (no score anywhere).
    """
    now = now or datetime.now(UTC)
    # An explicit argument always wins (tests stay pure); otherwise the operator's
    # own floor from Settings → Cards, clamped to its stated safe range.
    if min_magnitude is None:
        min_magnitude = configured_min_magnitude()

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
                # The provider's own coarse magnitude band, carried so the UI can
                # LABEL it as a band ("M>=6 / strong") and never as urgency.
                "band": quake_band(rec),
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

    # DISPLAY layer (rulings 1-3): group cross-provider duplicates, order by
    # provider-declared facts, and mark which entries clear the display floor.
    # The tier assignment above is already final and is NOT revisited here.
    for t in TIERS:
        hz = tiers[t]["hazards"]
        hz = group_same_events(hz) if group_events else [
            {**h, "providers": [h["source"]] if h.get("source") else [],
             "article_ids": [h["article_id"]] if h.get("article_id") is not None else [],
             "grouped": False}
            for h in hz
        ]
        hz.sort(key=_order_key)
        for h in hz:
            h["major"] = is_major(h, min_magnitude)
        tiers[t]["hazards"] = hz
        tiers[t]["major_count"] = sum(1 for h in hz if h["major"])
        tiers[t]["count"] = (
            len(hz) + len(tiers[t]["watches"]) + len(tiers[t]["convergences"])
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
        # The display floor, echoed so the UI states the same number it filters on
        # (and so a reader can see what "major" meant for this payload).
        "major_min_magnitude": min_magnitude,
        "major_bands": sorted(MAJOR_QUAKE_BANDS),
        "grouped_events": bool(group_events),
        "strip_cap": configured_strip_cap(),
        "method": ALERT_METHOD,
        "caveat": ALERT_CAVEAT,
    }
