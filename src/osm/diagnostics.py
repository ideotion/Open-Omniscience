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

from src.monitoring.path_tokens import tokenise_paths
from src.monitoring.secret_scrub import record_text

#: Runs shown per country, newest first. WHAT IT PROTECTS: the member's size and a reader's patience: a week of daily files shows the shape
#: of a cost (a steady day against a spike); the older ones are in the aggregate (``cost``) and counted in ``runs_not_shown``.
RUNS_KEPT = 7
#: Gaps shown per country, newest first. WHAT IT PROTECTS: the same; the total is always ``gaps_total``.
GAPS_KEPT = 10
#: What the bundle gives the member at most (the slot row states the number; this default only serves a direct call).
DEFAULT_MAX_BYTES = 20_000
#: The longest the text of an error the member itself met may be.
_ERROR_TEXT_MAX = 160


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _stat(values: list[float]) -> dict[str, Any] | None:
    """``n``, the total and the largest of the MEASURED values; None when none was measured (never a zero standing for it)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {"n": len(vals), "total": round(sum(vals), 3), "max": round(max(vals), 3)}


def _machine() -> dict[str, Any]:
    """Which kind of machine the figures were measured on. The full hardware record is the manifest's (``run.hardware``)."""
    return {"os": platform.system() or None, "arch": platform.machine() or None, "cpus": os.cpu_count(), "full_record": "manifest.json run.hardware"}


def _country(s: Any, c: Any) -> dict[str, Any]:
    from src.osm.apply import FEED_PREFIX, _position
    from src.osm.lane_models import OsmDiffRun
    from src.versioned.feed import cursor_row
    from src.versioned.models import VersionedGap

    pos, pos_ts = _position(c)
    feed = f"{FEED_PREFIX}{c.alpha3}"
    runs = list(s.query(OsmDiffRun).filter_by(alpha3=c.alpha3).order_by(OsmDiffRun.applied_at.desc(), OsmDiffRun.id.desc()))
    gaps = list(s.query(VersionedGap).filter_by(feed=feed).order_by(VersionedGap.detected_at.desc(), VersionedGap.id.desc()))
    cur = cursor_row(s, feed)
    out: dict[str, Any] = {
        "alpha3": c.alpha3,
        "status": c.status,
        "extract": {"sequence": c.extract_sequence, "vintage": _iso(c.extract_vintage)},
        "position": {
            "from": "change file" if c.diff_sequence is not None else ("extract" if pos is not None else None),
            "sequence": pos,
            "timestamp": _iso(pos_ts),
        },
        "cursor_token": None if cur is None else cur.token,
        "diffs_recorded": len(runs),
        "last_applied_at": _iso(runs[0].applied_at) if runs else None,
        "gaps_total": len(gaps),
        "rebaselines": sum(1 for g in gaps if g.reason == "retention"),
        "hand_recuts_seen": sum(1 for g in gaps if g.reason == "budget"),
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
    if runs:
        out["cost"] = {
            "bytes_fetched": _stat([r.bytes_fetched for r in runs]),
            "fetch_seconds": _stat([r.fetch_seconds for r in runs]),
            "apply_seconds": _stat([r.apply_seconds for r in runs]),
            "method": "over every change file recorded for this country: n files measured, their total and the largest",
        }
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


def diagnostics_member(max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Every cut country's change-file record, the newest runs and gaps first, cut to fit ``max_bytes`` with each cut named.

    Over the budget the OLDEST shown run of the country holding the most goes first, then its oldest gap, then (rows down to their
    position and cost) the country longest without a file; ``dropped_to_fit`` and ``countries_not_shown`` count what went. ``cost`` is
    computed over ALL recorded runs before any cut, so it never changes by one.

    THE BUDGET (:data:`DEFAULT_MAX_BYTES`, MEASURED 2026-11-04 on the build container, Linux x86-64): the fixed part is 389 bytes; one
    country at its widest (7 runs with 7-digit byte counts and 10 retention gaps with 9-digit tokens) is 3,889, so 20,000 holds five
    such countries (19,834) whole, and a sixth costs the oldest runs of the heaviest first. A country the files have not touched costs
    a code (6 bytes). 20,000 is therefore not a guess about a typical install: it is five fully-populated countries, the cut does the
    rest, and ``test_the_member_is_cut_to_its_budget...`` holds a 60-run country to it.
    """
    try:
        from src.osm.lane_models import OsmCountry
        from src.versioned import store

        budget = int(max_bytes)
        out: dict[str, Any] = {
            "method": (
                "the lane's osm_countries rows, its osm_diff_runs (one per change file applied, measured where the work ran) and the "
                "substrate feed's cursor and gaps; a retention gap is a re-baseline, a budget gap a hand re-cut"
            ),
            "measured_on": _machine(),
            "countries": [],
            "dropped_to_fit": {"runs": 0, "gaps": 0},
        }
        if not store.lane_exists("osm"):
            out["lane"] = "absent"
            out["reason"] = "no OpenStreetMap country has been cut on this install"
            return out
        with store.lane_session("osm") as s:
            rows = [_country(s, c) for c in s.query(OsmCountry).order_by(OsmCountry.alpha3)]
        # A country no change file or gap has touched has nothing to report beyond its position, so it is listed by code and the rows are
        # the countries the daily files have actually done something to, newest first.
        active = [r for r in rows if r["diffs_recorded"] or r["gaps_total"]]
        active.sort(key=lambda r: (r["last_applied_at"] or "", r["gaps"][0]["detected_at"] if r["gaps"] else ""), reverse=True)
        out["countries"] = active
        out["countries_without_updates"] = [r["alpha3"] for r in rows if r not in active]
        out["countries_not_shown"] = 0
        out["lane"] = "present"
        while _size(out) > budget:
            heaviest = max(out["countries"], key=lambda r: _size([r["runs"], r["gaps"]]), default=None)
            if heaviest is None:
                return {"omitted": "max_bytes is below the member's fixed part", "needs_at_least_bytes": _size(out)}
            if heaviest["runs"]:
                heaviest["runs"].pop()
                heaviest["runs_not_shown"] += 1
                out["dropped_to_fit"]["runs"] += 1
            elif heaviest["gaps"]:
                heaviest["gaps"].pop()
                heaviest["gaps_not_shown"] += 1
                out["dropped_to_fit"]["gaps"] += 1
            else:
                # Every row is down to its position and cost: the country longest without a change file goes, and the member says so.
                out["countries"].pop()
                out["countries_not_shown"] += 1
        return out
    except Exception as exc:  # noqa: BLE001 - a bundle member must never raise
        # The class and the engine's words with every held passphrase taken out, its paths tokenised, then cut.
        return {"error": tokenise_paths(record_text(exc, typed=True))[:_ERROR_TEXT_MAX]}
