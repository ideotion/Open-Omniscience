"""Trend surfaces 2 and 3: metadata adoption over time, and openings and closures (v0.6.0 B3a, S06-01 S3, Q815 = a, Q814 = b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

COUNTS WITH A METHOD AND AN n, NEVER A VERDICT, NEVER A COMPOSITE. Two surfaces, read from the rows the daily apply writes
(``osm_tag_changes``, B2) and, SEPARATELY, from the full-history planet's past (``osm_history_changes``, S05-04), never summed:

* SURFACE 2, adoption: per day, how many places the lane already held GAINED and how many LOST each of the four metadata types of
  analytic 1 (opening hours, website, e-mail, phone; the ``contact:*`` twin counts as its key, as in analytic 1, and an empty value is
  absent). A place counts once per day per type, and the changes to a place the file CREATED, DELETED or took out of the kept classes
  are not here (they are surface 3's). A place that both gains and loses the same type on one day (a tag moved to its ``contact:*`` twin)
  counts as neither. A change file lists only the keys that changed, so a place that already held one form and adds the other still reads
  as a gain; the caveat says so.
* SURFACE 3, openings and closures: per day, the places that APPEARED in the lane (``created``), DISAPPEARED (``deleted``), or stopped
  qualifying (``left_class``), and three signals read from changes to places the lane already held: a ``disused:*`` key added,
  ``shop`` set to ``vacant``, ``opening_hours`` set to ``closed`` or ``off``. A deletion in OpenStreetMap is not proof that a place closed
  (it can be a clean-up), and no signal here is called a closure: the counts are named for what the file did.

THE TWO CLOCKS, NEVER BLENDED. ``tracked`` is the window this machine observed: from the first daily change file applied here to the
newest, by those files' OWN dates, with the days that have a file listed (a day with a file and no row is a measured zero; a day with no
file is not a zero, it is not observed) and every stretch that was NOT observed (a re-baseline, a hand re-cut) named. ``prior`` is the
planet's history for the same country, in months, from a different table; when no history cut was read it says ``available: false`` with
the reason, and no figure from any other source stands in (Q814 (c) was not chosen).

READ-ONLY, makes no request, never raises: an unreadable lane is ``status: "unreadable"`` without the error's words. A table the lane
lacks (cut by an older build) is a named reason, never a zero.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

#: The metadata types, in analytic 1's order: ``(key, contact:* twin or None)``. ONE definition, read from analytic 1.
def _keys() -> tuple[tuple[str, str | None], ...]:
    from src.osm.completeness import KEYS

    return KEYS


#: The three closure-side signals, read from key changes to places the lane already held.
SIGNALS = ("disused", "vacant", "closed")
CLOSED_VALUES = ("closed", "off")

METHOD_ADOPTION = (
    "Per day of the change files applied here: the places the lane already held that gained or lost each tag, once per place per tag. "
    "A tag counts when it, or its contact:* twin, has a non-empty value, so setting opening hours to closed counts as gaining them. "
    "A place that both gains and loses the same tag on one day (a tag moved to its contact:* twin) counts as neither. "
    "Places created, deleted or dropped from the kept classes that day are counted under openings and closures."
)
CAVEAT_ADOPTION = (
    "These are changes, not totals, and a mapper tidying a record looks the same as a business changing. A change file lists only the tags "
    "that changed, so a place that already held one form of a tag and adds the other reads as gaining it. A day without a change file "
    "is not observed, and is not a zero. The planet's earlier years are shown apart and never added."
)
METHOD_OPENINGS = (
    "Per day of the change files applied here: places that appeared in or disappeared from the lane, places whose tags stopped qualifying, "
    "and, among places already held, a disused:* key added, shop set to vacant, opening hours set to closed or off. Once per place per day."
)
CAVEAT_OPENINGS = (
    "OpenStreetMap records what mappers entered: a deletion can be a clean-up, an appearance a place that was always there. None of these "
    "counts says a business opened or closed. A day without a change file is not observed, and is not a zero."
)
METHOD_PRIOR = (
    "Read from the full-history planet for this country's objects, by month, with the same rules. The version that created, deleted or "
    "restored an object is counted only as an appearance or a disappearance, and an object's first version is ignored. It covers the years "
    "before the window this machine observed, comes from a different table, and is never added to it."
)
CAVEAT_PRIOR = (
    "These are changes between a place's recorded versions, not totals, and a mapper tidying a record looks the same as a business changing. "
    "A month in which nobody edited a place has no row, which is not a zero. A deletion can be a clean-up and an appearance a place that was "
    "always there: none of these counts says a business opened or closed."
)

_OLD_LANE = "this table is not in the lane (it was cut by an older build); re-cutting a country creates it"


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def trends(alpha3: str) -> dict[str, Any]:
    """Surfaces 2 and 3 for one country. Never raises."""
    try:
        return _build(alpha3)
    except Exception as exc:  # noqa: BLE001 - one country's failure must not blank the page
        log_failure(_LOG, f"the {alpha3} OpenStreetMap trends could not be read", exc, level=logging.WARNING)
        return {"status": "unreadable", "country": alpha3, "detail": "the OpenStreetMap trends could not be read"}


def _day(col):
    from sqlalchemy import func

    return func.substr(col, 1, 10)


def _month(col):
    from sqlalchemy import func

    return func.substr(col, 1, 7)


def _obj(t):
    from sqlalchemy import String, cast, func

    return func.count(func.distinct(t.c.osm_type + cast(t.c.osm_id, String)))


def _adoption_parts(t):
    """``(base-key expression, direction expression, the keys read)`` over a table with ``key``, ``change``, ``old_value``, ``new_value``."""
    from sqlalchemy import and_, case, or_

    keys = _keys()
    twins = [(f"contact:{tw}", k) for k, tw in keys if tw]
    base = case(*[(t.c.key == twin, k) for twin, k in twins], else_=t.c.key)
    gained = or_(
        and_(t.c.change == "added", t.c.new_value != ""),
        and_(t.c.change == "modified", t.c.old_value == "", t.c.new_value != ""),
    )
    lost = or_(
        and_(t.c.change == "removed", t.c.old_value != ""),
        and_(t.c.change == "modified", t.c.old_value != "", t.c.new_value == ""),
    )
    direction = case((gained, "gained"), (lost, "lost"))
    return base, direction, [k for k, _ in keys] + [twin for twin, _ in twins]


def _adoption_rows(s, t, bucket, *where):
    """``(bucket, base key, direction, places)`` rows. A place that both gains and loses the same tag in one bucket is a net zero
    (a tag moved to its ``contact:*`` twin) and counts as neither."""
    from sqlalchemy import String, cast, func, select

    base, direction, keys = _adoption_parts(t)
    per_place = (
        select(
            bucket.label("b"),
            base.label("k"),
            (t.c.osm_type + cast(t.c.osm_id, String)).label("o"),
            func.min(direction).label("lo"),
            func.max(direction).label("hi"),
        )
        .where(t.c.key.in_(keys), direction.is_not(None), *where)
        .group_by(bucket, base, t.c.osm_type + cast(t.c.osm_id, String))
        .subquery()
    )
    return s.execute(
        select(per_place.c.b, per_place.c.k, per_place.c.lo, func.count()).where(per_place.c.lo == per_place.c.hi).group_by(per_place.c.b, per_place.c.k, per_place.c.lo)
    ).all()


def _signal(t):
    """The closure-side signal a KEY change carries, or NULL."""
    from sqlalchemy import and_, case, func

    entered = t.c.change.in_(("added", "modified"))
    return case(
        (and_(func.substr(t.c.key, 1, 8) == "disused:", t.c.change == "added", t.c.new_value != ""), "disused"),   # exact: LIKE is case-blind in SQLite
        (and_(t.c.key == "shop", entered, t.c.new_value == "vacant"), "vacant"),
        (and_(t.c.key == "opening_hours", entered, t.c.new_value.in_(CLOSED_VALUES)), "closed"),
    )


def _series(bucket_rows: dict[str, dict[str, Any]], buckets: list[str]) -> list[dict[str, Any]]:
    return [{"bucket": b, **bucket_rows.get(b, {})} for b in buckets]


def _adoption_series(rows, buckets: list[str]) -> dict[str, Any]:
    names = [k for k, _ in _keys()]
    by: dict[str, dict[str, Any]] = {b: {"gained": dict.fromkeys(names, 0), "lost": dict.fromkeys(names, 0)} for b in buckets}
    total = 0
    for bucket, base, direction, n in rows:
        if bucket in by and base in names and direction in ("gained", "lost"):
            by[bucket][direction][base] = int(n)
            total += int(n)
    return {"keys": [{"key": k, "twin": f"contact:{tw}" if tw else None} for k, tw in _keys()], "series": _series(by, buckets), "n": total}


_OPENING_FIELDS = ("created", "deleted", "left_class", *SIGNALS)
_PRIOR_OPENING_FIELDS = ("created", "deleted", *SIGNALS)


def _openings_series(rows, buckets: list[str], fields: tuple[str, ...] = _OPENING_FIELDS) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = {b: dict.fromkeys(fields, 0) for b in buckets}
    total = 0
    for bucket, what, n in rows:
        if bucket in by and what in fields:
            by[bucket][what] = int(n)
            total += int(n)
    return {"fields": list(fields), "series": _series(by, buckets), "n": total}


def _build(alpha3: str) -> dict[str, Any]:
    from sqlalchemy import func, inspect, select

    from src.osm.apply import FEED_PREFIX
    from src.osm.lane_models import OsmCountry, OsmDiffRun, OsmTagChange
    from src.versioned import store
    from src.versioned.models import VersionedGap

    if not store.lane_exists("osm"):
        return {"status": "lane-never-run", "country": alpha3}
    tc = OsmTagChange.__table__
    with store.lane_session("osm") as s:
        have = set(inspect(s.get_bind()).get_table_names())
        country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if country is None or country.status != "complete":
            return {"status": "not-cut", "country": alpha3}
        missing = [m.__tablename__ for m in (OsmDiffRun, OsmTagChange) if m.__tablename__ not in have]
        if missing:
            return {"status": "old-lane", "country": alpha3, "reason": _OLD_LANE, "missing": missing}
        runs = [r[0] for r in s.execute(select(OsmDiffRun.diff_timestamp).where(OsmDiffRun.alpha3 == alpha3, OsmDiffRun.diff_timestamp.is_not(None))) if r[0] is not None]
        if not runs:
            return {"status": "no-daily-files", "country": alpha3, "prior": _prior(s, alpha3, have)}
        days = sorted({r.date().isoformat() for r in runs})
        tracked: dict[str, Any] = {
            "since": _iso(min(runs)),
            "through": _iso(max(runs)),
            "files": len(runs),
            "days": days,
            "unobserved": [],
        }
        if VersionedGap.__tablename__ in have:
            for g in s.query(VersionedGap).filter(VersionedGap.feed == f"{FEED_PREFIX}{alpha3}").order_by(VersionedGap.detected_at):
                tracked["unobserved"].append(
                    {
                        "kind": "rebaseline" if g.reason == "retention" else "hand_recut" if g.reason == "budget" else "other",
                        "from_time": _iso(g.from_time),
                        "to_time": _iso(g.to_time),
                        "detected_at": _iso(g.detected_at),
                    }
                )
        else:
            tracked["unobserved"] = None
            tracked["unobserved_reason"] = _OLD_LANE
        own = tc.c.country_alpha3 == alpha3
        stamped = tc.c.diff_timestamp.is_not(None)
        day = _day(tc.c.diff_timestamp)
        adoption_rows = _adoption_rows(s, tc, day, own, stamped, tc.c.object_event.is_(None))
        event_rows = s.execute(
            select(day, tc.c.object_event, _obj(tc)).where(own, stamped, tc.c.object_event.is_not(None)).group_by(day, tc.c.object_event)
        ).all()
        sig = _signal(tc)
        signal_rows = s.execute(
            select(day, sig, _obj(tc)).where(own, stamped, tc.c.object_event.is_(None), sig.is_not(None)).group_by(day, sig)
        ).all()
        # A row on a day that has no file in osm_diff_runs cannot happen from this build's writes, but it is shown, not dropped.
        buckets = sorted(set(days) | {r[0] for r in adoption_rows} | {r[0] for r in event_rows} | {r[0] for r in signal_rows})
        rows_total = int(s.execute(select(func.count()).select_from(tc).where(own)).scalar() or 0)
        prior = _prior(s, alpha3, have)
    return {
        "status": "ok",
        "country": alpha3,
        "tracked": tracked,
        "tag_rows": rows_total,
        "adoption": {**_adoption_series(adoption_rows, buckets), "method": METHOD_ADOPTION, "caveat": CAVEAT_ADOPTION},
        "openings": {**_openings_series([*event_rows, *signal_rows], buckets), "method": METHOD_OPENINGS, "caveat": CAVEAT_OPENINGS},
        "prior": prior,
    }


def _prior(s, alpha3: str, have: set[str]) -> dict[str, Any]:
    """The planet's past for this country, by month, from ``osm_history_changes``; ``available: False`` with the reason when it was not read."""
    from sqlalchemy import select

    from src.osm.lane_models import OsmHistoryChange, OsmHistoryCut

    if OsmHistoryCut.__tablename__ not in have or OsmHistoryChange.__tablename__ not in have:
        return {"available": False, "reason": "no-history-table", "detail": _OLD_LANE}
    cut = s.query(OsmHistoryCut).filter_by(alpha3=alpha3).one_or_none()
    if cut is None:
        return {"available": False, "reason": "no-history-cut", "detail": "the full-history planet has not been read for this country"}
    if cut.status != "complete":
        return {"available": False, "reason": "history-cut-unfinished", "detail": "the full-history read for this country did not finish"}
    from sqlalchemy import exists

    h = OsmHistoryChange.__table__
    own = h.c.country_alpha3 == alpha3
    month = _month(h.c.version_timestamp)
    stamped = h.c.version_timestamp.is_not(None)
    not_first = (h.c.object_version.is_(None)) | (h.c.object_version != 1)
    key_level = h.c.key.is_not(None)
    # The key rows of a version that created, deleted or restored the object are that event's own, counted under openings and closures:
    # history.py writes a per-key row for every key of such a version, and they are not adoption or closure signals.
    e = h.alias("e")
    event_version = exists().where(
        e.c.osm_type == h.c.osm_type,
        e.c.osm_id == h.c.osm_id,
        # null-safe: a history file without version metadata has NULL versions, and the same version is then told by its timestamp
        e.c.object_version.is_not_distinct_from(h.c.object_version),
        e.c.version_timestamp.is_not_distinct_from(h.c.version_timestamp),
        e.c.key.is_(None),
    )
    adoption_rows = _adoption_rows(s, h, month, own, stamped, not_first, key_level, ~event_version)
    sig = _signal(h)
    signal_rows = s.execute(
        select(month, sig, _obj(h)).where(own, stamped, key_level, not_first, ~event_version, sig.is_not(None)).group_by(month, sig)
    ).all()
    # Object-level rows: created / deleted (restored is its own fact and not a closure or an opening here).
    event_rows = s.execute(
        select(month, h.c.change, _obj(h))
        .where(own, h.c.key.is_(None), h.c.change.in_(("created", "deleted")), stamped)
        .group_by(month, h.c.change)
    ).all()
    buckets = sorted({r[0] for r in adoption_rows} | {r[0] for r in signal_rows} | {r[0] for r in event_rows})
    return {
        "available": True,
        "bucket": "month",
        "span": json.loads(cut.span_json) if cut.span_json else None,
        "vintage": _iso(cut.history_vintage),
        "adoption": {**_adoption_series(adoption_rows, buckets), "caveat": CAVEAT_PRIOR},
        # No "left_class": the history has no such fact, and a column of zeros would read as a measurement.
        "openings": {**_openings_series([*event_rows, *signal_rows], buckets, _PRIOR_OPENING_FIELDS), "caveat": CAVEAT_PRIOR},
        "method": METHOD_PRIOR,
    }
