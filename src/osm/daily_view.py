"""What the Living sources view says about the OSM lane's daily change files (v0.6.0 B1, S06-01 S5, R427).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Counts and dates, never a verdict: how many cut countries the daily files have reached, how many files were applied, the newest file's own date, and
every RE-BASELINE (the mirror no longer held the files the country needed, so it had to be cut again from a fresh extract) as a dated event with its
country. A hand re-cut (the operator cut the country again instead of updating it) is counted apart: it is the operator's choice, not a retention gap.

READ-ONLY, makes no request. Never raises: an absent lane is ``{"measured": False, "reason": "lane-never-run"}`` and an unreadable one
``{"measured": False, "reason": "unreadable"}``, the shapes the other Living sources blocks already use. A figure whose table the lane lacks (a lane
cut by an older build) is ``None`` with its reason in ``reasons``, never ``0``: a zero reads as "the files reached nothing", which is a different fact.
"""

from __future__ import annotations

import logging
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

#: Re-baseline events listed, newest first. WHAT IT PROTECTS: the payload and a reader's patience; the total is always ``rebaselines_total``.
EVENTS_KEPT = 20

_OLD_LANE = "this table is not in the lane (it was cut by an older build); re-cutting a country creates it"


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def daily_block() -> dict[str, Any]:
    """The ``daily`` block of the OSM source in ``/api/living/overview``."""
    try:
        return _build()
    except Exception as exc:  # noqa: BLE001 - one source's failure must not blank the others
        log_failure(_LOG, "living overview: the OpenStreetMap daily files could not be read", exc, level=logging.WARNING)
        return {"measured": False, "reason": "unreadable", "detail": "the OpenStreetMap daily change files could not be read"}


def _build() -> dict[str, Any]:
    from sqlalchemy import func, inspect

    from src.osm.apply import FEED_PREFIX
    from src.osm.lane_models import OsmCountry, OsmDiffRun
    from src.versioned import store
    from src.versioned.models import VersionedGap

    if not store.lane_exists("osm"):
        return {"measured": False, "reason": "lane-never-run"}
    reasons: dict[str, str] = {}
    with store.lane_session("osm") as s:
        have = set(inspect(s.get_bind()).get_table_names())
        countries = list(s.query(OsmCountry.alpha3, OsmCountry.diff_sequence, OsmCountry.diff_timestamp))
        out: dict[str, Any] = {
            "measured": True,
            "countries_cut": len(countries),
            "countries_updated": sum(1 for c in countries if c.diff_sequence is not None),
            "newest_file_at": _iso(max((c.diff_timestamp for c in countries if c.diff_timestamp is not None), default=None)),
        }
        if OsmDiffRun.__tablename__ in have:
            out["files_applied"] = int(s.query(func.count(OsmDiffRun.id)).scalar() or 0)
            out["last_applied_at"] = _iso(s.query(func.max(OsmDiffRun.applied_at)).scalar())
        else:
            out["files_applied"], out["last_applied_at"] = None, None
            reasons["files_applied"] = reasons["last_applied_at"] = _OLD_LANE
        if VersionedGap.__tablename__ in have:
            gaps = list(
                s.query(VersionedGap)
                .filter(VersionedGap.feed.like(f"{FEED_PREFIX}%"))
                .order_by(VersionedGap.detected_at.desc(), VersionedGap.id.desc())
            )
            retention = [g for g in gaps if g.reason == "retention"]
            out["rebaselines_total"] = len(retention)
            out["hand_recuts"] = sum(1 for g in gaps if g.reason == "budget")
            out["rebaselines"] = [
                {
                    "alpha3": g.feed[len(FEED_PREFIX):],
                    "detected_at": _iso(g.detected_at),
                    "from_time": _iso(g.from_time),
                    "to_time": _iso(g.to_time),
                }
                for g in retention[:EVENTS_KEPT]
            ]
            out["rebaselines_not_shown"] = max(0, len(retention) - EVENTS_KEPT)
        else:
            out["rebaselines_total"], out["hand_recuts"], out["rebaselines"], out["rebaselines_not_shown"] = None, None, [], 0
            reasons["rebaselines_total"] = reasons["hand_recuts"] = _OLD_LANE
    if reasons:
        out["reasons"] = reasons
    out["method"] = (
        "the lane's osm_countries rows, its osm_diff_runs (one per change file applied) and the substrate feed's gaps: a retention gap is a "
        "re-baseline, a budget gap a hand re-cut; times are UTC"
    )
    return out
