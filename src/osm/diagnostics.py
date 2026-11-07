"""The OSM lane's record of its daily change files, as one diagnostics-bundle member (v0.6.0 B1, S06-01 S5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The same slot contract as ``monitoring.boots.diagnostics_member`` (``(max_bytes) -> dict``, never raises, keeps the newest, names what it
cut). For each cut country: where its objects stand (the extract's own position, then the last change file applied), the number of change
files recorded, the substrate feed's cursor and its gaps (a ``retention`` gap is a re-baseline: the extract was cut again because the
mirror no longer held the files in between; a ``budget`` gap is the operator cutting again by hand), and what the files COST, measured where
the work happened: bytes fetched, seconds to fetch and to apply, on which kind of machine.

A figure this build did not measure is ``null`` with its reason, never ``0``: a country with no applied file has no cost, which is a
different fact from a free one. Counts, times, sizes, labels and the fixed words of the code only: no object, no tag, no path, no URL, no
text of an exception.

The slot row (``src/api/diagnostics_slots.py``) and the plan table are the diagnostics owner's; this module is the producer.
"""

from __future__ import annotations

import json
import os
import platform
from typing import Any

#: Runs shown per country, newest first. WHAT IT PROTECTS: the member's size and a reader's patience: a week of daily files shows the shape
#: of a cost (a steady day against a spike); the older ones are in the aggregate (``cost``) and counted in ``runs_not_shown``.
RUNS_KEPT = 7
#: Gaps shown per country, newest first. WHAT IT PROTECTS: the same; the total is always ``gaps_total``.
GAPS_KEPT = 10
#: What the bundle gives the member at most (the slot row states the number; this default only serves a direct call).
DEFAULT_MAX_BYTES = 20_000
#: What an unmeasured or unreadable figure says instead of a number.
_OLD_LANE = "this table is not in the lane (it was cut by an older build); re-cutting the country creates it"


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _stat(values: list[float]) -> dict[str, Any] | None:
    """``n``, the total and the largest of the MEASURED values; None (the caller says why) when none was measured, never a zero."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {"n": len(vals), "total": round(sum(vals), 3), "max": round(max(vals), 3)}


def _machine() -> dict[str, Any]:
    """Which kind of machine the figures were measured on. The full hardware record is the manifest's (``run.hardware``)."""
    cpus = os.cpu_count()
    out: dict[str, Any] = {"os": platform.system() or None, "arch": platform.machine() or None, "cpus": cpus, "full_record": "manifest.json run.hardware"}
    missing = {k: "this machine did not report it" for k in ("os", "arch", "cpus") if out[k] is None}
    if missing:
        out["unreported"] = missing
    return out


def _tables(s: Any) -> set[str]:
    """The tables this lane has. A lane cut before a table existed does not have it: ``lane_engine`` never creates one."""
    from sqlalchemy import inspect

    return set(inspect(s.get_bind()).get_table_names())


def _country(s: Any, c: Any, have: set[str]) -> dict[str, Any]:
    from src.osm.apply import FEED_PREFIX, _position
    from src.osm.lane_models import OsmDiffRun
    from src.versioned.feed import cursor_row
    from src.versioned.models import VersionedCursor, VersionedGap

    pos, pos_ts = _position(c)
    feed = f"{FEED_PREFIX}{c.alpha3}"
    has_runs = OsmDiffRun.__tablename__ in have
    has_gaps = VersionedGap.__tablename__ in have
    has_cursor = VersionedCursor.__tablename__ in have
    runs = list(s.query(OsmDiffRun).filter_by(alpha3=c.alpha3).order_by(OsmDiffRun.applied_at.desc(), OsmDiffRun.id.desc())) if has_runs else []
    gaps = list(s.query(VersionedGap).filter_by(feed=feed).order_by(VersionedGap.detected_at.desc(), VersionedGap.id.desc())) if has_gaps else []
    cur = cursor_row(s, feed) if has_cursor else None
    if c.diff_sequence is not None:
        source, source_reason = "change file", None
    elif pos is not None:
        source, source_reason = "extract", None
    else:
        source, source_reason = None, "this country carries no recorded position (cut before positions were stored)"
    out: dict[str, Any] = {
        "alpha3": c.alpha3,
        "status": c.status,
        "extract": {"sequence": c.extract_sequence, "vintage": _iso(c.extract_vintage)},
        "position": {"from": source, "sequence": pos, "timestamp": _iso(pos_ts)},
        "diffs_recorded": len(runs) if has_runs else None,
        "last_applied_at": _iso(runs[0].applied_at) if runs else None,
        "gaps_total": len(gaps) if has_gaps else None,
        "rebaselines": sum(1 for g in gaps if g.reason == "retention") if has_gaps else None,
        "hand_recuts_seen": sum(1 for g in gaps if g.reason == "budget") if has_gaps else None,
        "gaps": [
            {
                "reason": g.reason,
                "from_token": g.from_token,
                "to_token": g.to_token,
                "from_time": _iso(g.from_time),
                "to_time": _iso(g.to_time),
                "detected_at": _iso(g.detected_at),
                "closed": g.closed_at is not None,
            }
            for g in gaps[:GAPS_KEPT]
        ],
        "gaps_not_shown": max(0, len(gaps) - GAPS_KEPT),
    }
    if source_reason:
        out["position"]["reason"] = source_reason
    elif pos_ts is None:
        out["position"]["reason"] = "this position carries no timestamp (cut before timestamps were stored)"
    if c.extract_sequence is None or c.extract_vintage is None:
        out["extract"]["reason"] = "this country was cut before the extract's sequence and date were stored"
    if not has_cursor:
        out["cursor_token"], out["cursor_reason"] = None, _OLD_LANE
    elif cur is None:
        out["cursor_token"], out["cursor_reason"] = None, "the daily feed has not run for this country, so it has no cursor"
    else:
        out["cursor_token"] = cur.token
        if cur.token is None:
            out["cursor_reason"] = "the feed's cursor carries no token"
    if not has_gaps:
        out["gaps_reason"] = _OLD_LANE
    if not has_runs:
        out["cost"], out["cost_reason"] = None, _OLD_LANE
        out["runs"], out["runs_not_shown"] = [], 0
    elif runs:
        cost = {
            "bytes_fetched": _stat([r.bytes_fetched for r in runs]),
            "fetch_seconds": _stat([r.fetch_seconds for r in runs]),
            "apply_seconds": _stat([r.apply_seconds for r in runs]),
            "method": "over every change file recorded for this country: n files measured, their total and the largest",
        }
        unmeasured = sorted(k for k in ("bytes_fetched", "fetch_seconds", "apply_seconds") if cost[k] is None)
        if unmeasured:
            cost["unmeasured"] = dict.fromkeys(unmeasured, "no recorded change file carries this measurement")
        out["cost"] = cost
        out["runs"] = [
            {
                "sequence": r.sequence,
                "diff_timestamp": _iso(r.diff_timestamp),
                "applied_at": _iso(r.applied_at),
                "bytes_fetched": r.bytes_fetched,
                "fetch_seconds": r.fetch_seconds,
                "apply_seconds": r.apply_seconds,
            }
            for r in runs[:RUNS_KEPT]
        ]
        out["runs_not_shown"] = max(0, len(runs) - RUNS_KEPT)
    else:
        out["cost"] = None
        out["cost_reason"] = "no change file has been applied to this country yet, so no cost was measured"
        out["runs"] = []
        out["runs_not_shown"] = 0
    return out


def _cut_to_fit(out: dict[str, Any], budget: int) -> bool:
    """Cut ``out`` in place until it fits ``budget``; False when nothing left to cut still does not fit.

    Sizes are measured ONCE per item and subtracted as items go (the first version re-serialised everything per pop: 15 s for 200
    countries); the count fields grow by a digit now and then, so a fit by that arithmetic is re-measured exactly before it is believed.
    """
    countries = out["countries"]
    est = _size(out)
    weight = {id(r): _size([r["runs"], r["gaps"]]) for r in countries}
    while True:
        if est <= budget:
            est = _size(out)
            if est <= budget:
                return True
        heaviest = max(countries, key=lambda r: weight[id(r)], default=None)
        if heaviest is not None and heaviest["runs"]:
            lost = _size(heaviest["runs"].pop()) + 1
            weight[id(heaviest)] -= lost
            heaviest["runs_not_shown"] += 1
            out["dropped_to_fit"]["runs"] += 1
        elif heaviest is not None and heaviest["gaps"]:
            lost = _size(heaviest["gaps"].pop()) + 1
            weight[id(heaviest)] -= lost
            heaviest["gaps_not_shown"] += 1
            out["dropped_to_fit"]["gaps"] += 1
        elif countries:
            # Every row is down to its position and cost: the country longest without a change file goes, and the member says so.
            lost = _size(countries.pop()) + 1
            out["countries_not_shown"] += 1
        elif out["countries_without_updates"]:
            lost = _size(out["countries_without_updates"].pop()) + 1
            out["countries_without_updates_not_shown"] += 1
        else:
            return False
        est -= lost


def _build() -> dict[str, Any]:
    from src.osm.lane_models import OsmCountry
    from src.versioned import store

    out: dict[str, Any] = {
        "method": (
            "the lane's osm_countries rows, its osm_diff_runs (one per change file applied, measured where the work ran) and the "
            "substrate feed's cursor and gaps; a retention gap is a re-baseline, a budget gap a hand re-cut"
        ),
        "measured_on": _machine(),
        "countries": [],
        "countries_without_updates": [],
        "countries_without_updates_not_shown": 0,
        "countries_not_shown": 0,
        "dropped_to_fit": {"runs": 0, "gaps": 0},
    }
    if not store.lane_exists("osm"):
        out["lane"] = "absent"
        out["reason"] = "no OpenStreetMap country has been cut on this install"
        return out
    with store.lane_session("osm") as s:
        have = _tables(s)
        rows = [_country(s, c, have) for c in s.query(OsmCountry).order_by(OsmCountry.alpha3)]
    # A country no change file or gap has touched has nothing to report beyond its position, so it is listed by code and the rows are
    # the countries the daily files have actually done something to, newest first (a gap's time counts as much as a file's).
    # A table the lane lacks (``None``) leaves the question unanswered, so that country stays listed with its position rather than being
    # called untouched.
    active = [r for r in rows if r["diffs_recorded"] or r["gaps_total"] or r["diffs_recorded"] is None or r["gaps_total"] is None]
    active.sort(key=lambda r: max(r["last_applied_at"] or "", r["gaps"][0]["detected_at"] if r["gaps"] else ""), reverse=True)
    shown = {r["alpha3"] for r in active}
    out["countries"] = active
    out["countries_without_updates"] = [r["alpha3"] for r in rows if r["alpha3"] not in shown]
    out["lane"] = "present"
    return out


def diagnostics_member(max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Every cut country's change-file record, the newest runs and gaps first, cut to fit ``max_bytes`` with each cut named.

    Over the budget the OLDEST shown run of the country holding the most goes first, then its oldest gap, then (rows down to their
    position and cost) the country longest without a file, then the list of codes; ``dropped_to_fit``, ``countries_not_shown`` and
    ``countries_without_updates_not_shown`` count what went. ``cost`` is computed over ALL recorded runs before any cut, so it never
    changes by one. A budget below the fixed part gets ``{"omitted", "over_budget": true, ...}`` (a few dozen bytes, which may itself
    exceed a budget that small: ``over_budget`` says so rather than leaving a reader to measure).

    WHERE A NULL'S REASON LIVES: ``cost_reason`` / ``cursor_reason`` / ``gaps_reason`` (``diffs_recorded``, ``gaps_total``, ``last_applied_at``
    are null under the same table-missing reason), ``position.reason``, ``extract.reason``, ``cost.unmeasured`` (a whole measurement no run
    carries) and ``unreported`` (the machine). A single run's null measurement is left out of that measurement's ``n`` in ``cost``, so
    ``n`` below ``diffs_recorded`` IS the statement that some runs did not measure it; a gap's null time or token is the substrate's own
    (the file the gap spans was not known), shown as recorded.

    THE BUDGET (:data:`DEFAULT_MAX_BYTES`, MEASURED 2026-11-05 through the real member on the build container, Linux x86-64): the fixed part is
    about 0.4 KB; a country at its widest (99 files recorded, 7 shown with 7-digit byte counts, 10 retention gaps with 9-digit tokens, no
    cursor row) is about 4.0 KB, so SIX of them are 24,398 bytes whole and 20,000 cuts the 26 oldest runs of the heaviest to 19,953; a
    country the files have not touched costs a code (6 bytes). 20,000 is therefore not a guess about a typical install: it is the size at
    which a sixth fully-populated country starts to cost the oldest runs, and ``test_the_member_is_cut_to_its_budget...`` holds a
    60-run country to it. The slot row states the number the bundle gives it.
    """
    try:
        budget = int(max_bytes)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"error": type(exc).__name__, "reason": "max_bytes is not a whole number"}
    try:
        out = _build()
        if _cut_to_fit(out, budget):
            return out
        return {
            "omitted": "max_bytes is below the member's fixed part",
            "over_budget": True,
            "lane": out.get("lane"),
            "needs_at_least_bytes": _size(out),
            "dropped_to_fit": out["dropped_to_fit"],
            "countries_not_shown": out["countries_not_shown"],
            "countries_without_updates_not_shown": out["countries_without_updates_not_shown"],
        }
    except Exception as exc:  # noqa: BLE001 - a bundle member must never raise
        # The class and fixed words only: an engine's or a column type's own words can quote a stored value, and none is worth that.
        return {"error": type(exc).__name__, "reason": "the member could not read the lane; the error's own words are withheld"}
