"""Consented, freshness-gated hazard snapshot for the scheduler background pass.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. :mod:`src.hazards.store` is deliberately network-free — it only
READS/WRITES the local snapshot the severity-tiered alert layer (:mod:`src.analytics.alerts`)
consumes, and a briefing producer must NEVER touch the network. So the snapshot was only
ever populated by an explicit ``POST /api/signals/hazards/snapshot``; in a normal continuous
collect run nothing refreshed it and the hazard alert tier stayed empty.

This module is the SCHEDULER-side pass — the ONE place allowed to fetch — that keeps the
snapshot fresh, mirroring the markets/law auto-track passes: freshness-gated (a recent
snapshot is a no-op, so USGS/GDACS are polled politely), best-effort, and airplane-safe by
construction (the kill switch short-circuits BEFORE any socket). The actual fetch rides the
shared guarded fetcher (kill switch / robots / proxy honoured). A producer never fetches;
this does.
"""

from __future__ import annotations

import logging
from datetime import datetime

_LOG = logging.getLogger(__name__)

# Poll the open hazard feeds at most this often from the background pass (a snapshot
# newer than this is left untouched). Well inside the alert layer's 48h staleness cutoff,
# so the tier never goes stale, yet the feeds are not hammered every pass.
DEFAULT_REFRESH_INTERVAL_HOURS = 6.0


def auto_snapshot_due(
    fetcher,
    *,
    refresh_interval_hours: float = DEFAULT_REFRESH_INTERVAL_HOURS,
    now: datetime | None = None,
    fetch_fn=None,
    session=None,
) -> dict:
    """Refresh the LOCAL hazard snapshot if it is stale — the scheduler background pass.

    Freshness-gated: a snapshot younger than ``refresh_interval_hours`` is a no-op
    (``{"skipped": "fresh"}``). Airplane-safe BY CONSTRUCTION: if the kill switch is engaged
    this returns ``{"skipped_offline": True}`` WITHOUT calling the fetcher (no socket is
    attempted) — the same explicit short-circuit the stats-subscriptions pass uses. Online,
    it fetches the open USGS/GDACS feeds through the shared guarded ``fetcher`` (kill switch
    / robots / proxy honoured) and saves. A refresh that returns nothing (all feeds failed)
    never overwrites a good snapshot with an empty one. Best-effort; counts only; never
    raises. ``fetch_fn`` is a test seam: a zero-arg callable returning ``(records, failures)``.

    ``session`` (2026-07-24 field-feedback A6, ruled): when given, every freshly-saved
    snapshot is ALSO ingested as corpus Articles (``src.hazards.ingest``) — zero network
    (the records are already local), best-effort (an ingest hiccup never breaks the
    scrape pass this rides). ``session=None`` (the default) keeps this function's
    original snapshot-only behaviour, unchanged, for callers/tests that don't need it.
    """
    from src.hazards.store import load_snapshot, save_snapshot
    from src.ingest import kill_switch_active

    snap = load_snapshot(now=now)
    age = snap.get("age_hours")
    if snap.get("available") and age is not None and age < float(refresh_interval_hours):
        return {"skipped": "fresh", "age_hours": age}

    if kill_switch_active():
        # Offline: do NOT attempt any fetch (no socket); keep the last-known snapshot.
        return {"skipped_offline": True}

    try:
        if fetch_fn is not None:
            records, failures = fetch_fn()
        else:
            from src.api.hazards import fetch_hazards

            records, failures = fetch_hazards(source="all", fetcher=fetcher)
    except Exception as exc:  # noqa: BLE001 - a bad relay must not break the collect pass
        _LOG.warning("hazard snapshot fetch failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}

    if not records:
        return {
            "snapshotted": 0,
            "failures": failures,
            "note": "no records (offline or all feeds failed) -- previous snapshot kept",
        }
    saved = save_snapshot(records, now=now)
    out = {"snapshotted": len(saved["records"]), "failures": failures}
    if session is not None:
        try:
            from src.hazards.ingest import ingest_hazard_records

            out["ingested"] = ingest_hazard_records(session, saved["records"])
        except Exception:  # noqa: BLE001 - ingest must never break the collect pass
            _LOG.warning("hazard corpus ingest failed", exc_info=True)
    return out
