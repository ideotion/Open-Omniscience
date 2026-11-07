"""Trend surfaces 4 to 6: brand footprint, contact channels and data freshness (v0.6.0 B3b, S06-01 S3, Q815 = a, Q814 = b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

COUNTS WITH A METHOD AND AN n, NEVER A VERDICT, NEVER A COMPOSITE. Each surface has three parts, from three different sources, never added:

* ``snapshot`` -- what the country's places (``osm_objects``, kind ``poi``) look like NOW: the extract with every daily change file applied,
  at the vintage stated beside it (the extract's date, the newest change file applied, and the date the ages below are measured from).
* ``changes`` -- what the daily change files changed, per day, over the window THIS machine observed (``osm_tag_changes``, B2), with the
  days that have a file listed (a day with a file and no row is a measured zero; a day with no file is not observed, which is not a zero).
* ``prior`` -- the full-history planet's past for the same country, by month (``osm_history_changes``), a different table; ``available:
  false`` with the reason when it was not read. No other source stands in (Q814 (c) was not chosen).

THE KEY SETS (S06-01 S3 «may not decide which keys count as brand / chain beyond the keys S05-04 ingested; record the set»). Recorded here, shown
on the page, and read by every query below from these constants:

* BRAND (surface 4): ``brand`` and ``brand:wikidata`` -- Q810's own list, both curated columns. ``operator`` and ``operator:wikidata`` are read
  beside them but are the organisation that RUNS a place, not the chain it belongs to, so they are counted apart and never merged into a
  brand. ``brand:wikipedia`` and ``operator:type`` are stored but not counted: nothing here needs them. NO threshold makes a brand a «chain»:
  the ranking is the number of places carrying exactly that text, and the reader sees the number.
* CHANNELS (surface 5): site, phone and e-mail are analytic 1's definition exactly (the tag or its ``contact:*`` twin, an empty value is
  absent), so a figure here equals the same figure in the completeness table. SOCIAL is the ``contact:<service>`` form of facebook,
  instagram, twitter, youtube, tiktok, linkedin, telegram and whatsapp (the family column keeps the suffix); the old bare spelling
  (``facebook=*``) sits in the blob and is not read, which the method says. Each social service is counted on its own; «any social» is the one
  OR of them that the mix needs, and no figure adds the channels.
* FRESHNESS (surface 6): the age of an object's last edit is ``osm_objects.timestamp`` (the version's own time, never the time it was read here);
  ``check_date`` is the mapper's own «verified on» tag, read as ``YYYY-MM-DD``, ``YYYY-MM`` or ``YYYY`` -- a partial date is dated at the START
  of its period, so it reads older, never fresher -- and a value that is none of those is counted as unreadable, not dropped. Ages are measured
  from the vintage (the newest change file applied, else the extract's date), NEVER from today's clock, so the same lane reads the same on any
  day. «Last edit» is the object's last version in the lane: an edit that touched only the shape or members changes it too, though it leaves no
  tag row below.

READ-ONLY, makes no request, never raises: an unreadable lane is ``status: "unreadable"`` without the error's words. A table the lane lacks
(cut by an older build) is a named reason, never a zero.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from src.monitoring.secret_scrub import log_failure
from src.osm.tags import column_name
from src.osm.trends import (
    _OLD_LANE,
    CAVEAT_PRIOR,
    METHOD_PRIOR,
    _adoption_rows,
    _day,
    _group_series,
    _iso,
    _obj,
    _prior_cut,
    _series,
    _window,
)

_LOG = logging.getLogger(__name__)

SURFACES = ("brands", "channels", "freshness")

#: Surface 4. ``(name, the tag keys read as it)``; the first two are the brand, the last two the operator, and they are never merged.
BRAND_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("brand", ("brand",)),
    ("brand:wikidata", ("brand:wikidata",)),
    ("operator", ("operator",)),
    ("operator:wikidata", ("operator:wikidata",)),
)

#: Surface 5. The social services read, as the suffix of ``contact:<service>``.
SOCIAL_SERVICES = ("facebook", "instagram", "twitter", "youtube", "tiktok", "linkedin", "telegram", "whatsapp")
SOCIAL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = tuple((s, (f"contact:{s}",)) for s in SOCIAL_SERVICES)

#: Surface 6. The ages' cut points, in whole years back from the reference date.
AGE_YEARS = (1, 2, 5)

DEFAULT_LIMIT = 100
MAX_LIMIT = 2000

METHOD_BRANDS = (
    "Among this country's places with metadata (objects kept as 'poi' by the OSM lane), the count whose brand, brand:wikidata, operator or "
    "operator:wikidata tag has a non-empty value, each counted on its own, and the brands ranked by the number of places that carry exactly that "
    "text. An operator is the organisation that runs a place, not the chain it belongs to, and is never merged into a brand. brand:wikipedia and "
    "operator:type are stored but not counted. No threshold makes a brand a chain: the ranking is the count."
)
CAVEAT_BRANDS = (
    "A brand is a text a mapper typed: 'McDonald's' and 'McDonalds' are two rows, and nothing here says which are chains. A missing brand means "
    "OpenStreetMap does not record it, not that the place has none. The figures describe the extract with every change file applied, at the vintage shown."
)
METHOD_CHANNELS = (
    "Among this country's places with metadata (objects kept as 'poi' by the OSM lane), the count carrying each contact channel. Site, phone and "
    "e-mail are counted as in the completeness table: the tag or its contact:* twin, an empty value is absent. Social is the contact:<service> tag "
    "of facebook, instagram, twitter, youtube, tiktok, linkedin, telegram or whatsapp, each service counted on its own; the older bare spelling "
    "(facebook=*) is not read. The mix counts the places carrying none, one, two, three or all four of site, phone, e-mail and any social. "
    "Nothing adds the channels."
)
CAVEAT_CHANNELS = (
    "A missing channel means OpenStreetMap does not record it, not that the place has none, and a service that moved to a new name is counted under "
    "the name mappers still use. The figures describe the extract with every change file applied, at the vintage shown."
)
METHOD_FRESHNESS = (
    "Among this country's places with metadata (objects kept as 'poi' by the OSM lane): how long before the vintage shown each place was last "
    "edited, from the timestamp of its current version; and how many carry a check_date, the mapper's own «verified on» date, aged the same way. "
    "A partial check_date (a year, or a year and month) is dated at the start of its period, so it reads older, never fresher. Ages count whole "
    "years back from the vintage, never from today's clock. A check_date that is not a date is counted as unreadable."
)
CAVEAT_FRESHNESS = (
    "The age of an edit says when a mapper last touched the record, not when the place was last true: a place can be correct for years with no "
    "edit, and a recent edit can be a small tidy. A check_date is what a mapper wrote; most places carry none, and that is not a verdict on them. "
    "The figures describe the extract with every change file applied, at the vintage shown."
)
METHOD_CHANGES_BRANDS = (
    "Per day of the change files applied here: the places the lane already held that gained or lost each of brand, brand:wikidata, operator and "
    "operator:wikidata, once per place per tag. A tag counts when it has a non-empty value. A place that both gains and loses the same tag on one "
    "day counts as neither. Places created, deleted or dropped from the kept classes that day are counted under openings and closures."
)
METHOD_CHANGES_CHANNELS = (
    "Per day of the change files applied here: the places the lane already held that gained or lost each social service (the contact:<service> "
    "tag), once per place per service. A place that both gains and loses the same service on one day counts as neither. Site, phone and e-mail "
    "changes are the adoption tab's, under trends, and are not repeated here."
)
METHOD_CHANGES_FRESHNESS = (
    "Per day of the change files applied here: the places the lane already held that had a tag changed (edited), and, of those, the places whose "
    "check_date was set or changed to a non-empty value (checked). Once per place per day. Places created, deleted or dropped from the kept classes "
    "that day are counted under openings and closures."
)
CAVEAT_CHANGES = (
    "These are changes, not totals, and a mapper tidying a record looks the same as a business changing. A change file lists only the tags that "
    "changed, so an edit to a place's shape or members leaves no tag row. A day without a change file is not observed, and is not a zero. The "
    "planet's earlier years are shown apart and never added."
)

_METHODS = {
    "brands": (METHOD_BRANDS, CAVEAT_BRANDS, METHOD_CHANGES_BRANDS),
    "channels": (METHOD_CHANNELS, CAVEAT_CHANNELS, METHOD_CHANGES_CHANNELS),
    "freshness": (METHOD_FRESHNESS, CAVEAT_FRESHNESS, METHOD_CHANGES_FRESHNESS),
}


def profile(alpha3: str, surface: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """One surface (4 to 6) for one country. Never raises."""
    if surface not in SURFACES:
        return {"status": "unknown-surface", "country": alpha3, "surface": surface}
    try:
        return _build(alpha3, surface, max(1, min(int(limit), MAX_LIMIT)))
    except Exception as exc:  # noqa: BLE001 - one country's failure must not blank the page
        log_failure(_LOG, f"the {alpha3} OpenStreetMap {surface} could not be read", exc, level=logging.WARNING)
        return {"status": "unreadable", "country": alpha3, "surface": surface, "detail": "this OpenStreetMap surface could not be read"}


# --------------------------------------------------------------------------- #
#  Small expressions                                                           #
# --------------------------------------------------------------------------- #


def _filled(key: str):
    """The column of a curated tag is present and not empty."""
    from sqlalchemy import and_

    from src.osm.lane_models import osm_objects_table

    col = osm_objects_table.c[column_name(key)]
    return and_(col.is_not(None), col != "")


def _sum_if(cond):
    from sqlalchemy import case, func

    return func.sum(case((cond, 1), else_=0))


def _contact_filled(suffix: str):
    """``contact:<suffix>`` has a non-empty value, read from the family column."""
    from sqlalchemy import and_, func

    from src.osm.lane_models import osm_objects_table

    val = func.json_extract(osm_objects_table.c.contact, f'$."{suffix}"')
    return and_(osm_objects_table.c.contact.is_not(None), val.is_not(None), val != "")


def _years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 February
        return d.replace(year=d.year - years, day=28)


def _cutoffs(ref: date) -> list[str]:
    """The ISO dates a year, two years and five years before the reference."""
    return [_years_before(ref, y).isoformat() for y in AGE_YEARS]


_CHECK_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def parse_check_date(value: str) -> date | None:
    """A ``check_date`` as the first day of the period it names, or None when it is not ``YYYY[-MM[-DD]]``."""
    m = _CHECK_DATE.match(value.strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _age_bucket(day: date, ref: date, cuts: list[date]) -> str:
    """``after`` (later than the reference), or ``within_1y`` / ``y1_2`` / ``y2_5`` / ``over_5y``: half-open, the newer edge excluded."""
    if day > ref:
        return "after"
    c1, c2, c5 = cuts
    if day > c1:
        return "within_1y"
    if day > c2:
        return "y1_2"
    if day > c5:
        return "y2_5"
    return "over_5y"


AGE_BUCKETS = ("within_1y", "y1_2", "y2_5", "over_5y")


def _share(n_part: int, n: int) -> float | None:
    return (n_part / n) if n else None


# --------------------------------------------------------------------------- #
#  Snapshots                                                                   #
# --------------------------------------------------------------------------- #


def _ranked_from(rows: list[list], key: str, limit: int) -> dict[str, Any]:
    """The values of one curated tag ranked by the number of places carrying exactly that text; ``total`` is the distinct values, ``rows`` the first ``limit``.

    ``rows`` arrive most first, then by the text (``places_summary._values``), so the ranking is a slice.
    """
    return {"key": key, "total": len(rows), "shown": min(limit, len(rows)), "rows": [{"value": v, "places": int(n)} for v, n in rows[:limit]]}


def _source(info: dict[str, Any]) -> dict[str, Any]:
    """Where the snapshot's counts came from: the stored summary of the current places, or computed from them on this read (and why)."""
    return {"source": info["source"], "summary": {k: v for k, v in info.items() if k != "source"}}


def _snapshot_brands(s, alpha3: str, limit: int, country, have: set[str]) -> dict[str, Any]:
    from src.osm.places_summary import part_for

    data, info = part_for(s, alpha3, "brands", country, have)
    c = data["counts"]
    n = int(c.get("n", 0))
    return {
        "n": n,
        "tags": [
            {"key": name, "present": c.get(f"present:{name}", 0), "share": _share(c.get(f"present:{name}", 0), n), "group": "brand" if name.startswith("brand") else "operator"}
            for name, _ in BRAND_GROUPS
        ],
        "limit": limit,
        "rankings": [_ranked_from(data["values"].get(key, []), key, limit) for key in ("brand", "brand:wikidata")],
        **_source(info),
    }


def _snapshot_channels(s, alpha3: str, country, have: set[str]) -> dict[str, Any]:
    from src.osm.places_summary import part_for

    data, info = part_for(s, alpha3, "channels", country, have)
    c = data["counts"]
    n = int(c.get("n", 0))
    names = ["website", "phone", "email", "social"]
    channels = [{"key": k, "present": c.get(k, 0), "share": _share(c.get(k, 0), n)} for k in names]
    services = [{"key": sv, "present": c.get(f"social:{sv}", 0), "share": _share(c.get(f"social:{sv}", 0), n)} for sv in SOCIAL_SERVICES]
    mix = [{"channels": i, "places": c.get(f"mix:{i}", 0), "share": _share(c.get(f"mix:{i}", 0), n)} for i in range(len(names) + 1)]
    return {"n": n, "channels": channels, "social": services, "mix": mix, **_source(info)}


def _age_counts(days: list[list], rd: date) -> tuple[dict[str, int], int]:
    """The last-edit histogram cut into the age buckets from the reference date, by the same day-text comparisons the SQL made; and the places counted."""
    c1, c2, c5 = (c.isoformat() for c in (_years_before(rd, y) for y in AGE_YEARS))
    r = rd.isoformat()
    buckets = dict.fromkeys(("after", *AGE_BUCKETS), 0)
    stamped = 0
    for day, n in days:
        stamped += n
        if day > r:
            buckets["after"] += n   # an edit dated after the vintage: named, never counted as recent
        elif day > c1:
            buckets["within_1y"] += n
        elif day > c2:
            buckets["y1_2"] += n
        elif day > c5:
            buckets["y2_5"] += n
        else:
            buckets["over_5y"] += n
    return buckets, stamped


def _snapshot_freshness(s, alpha3: str, ref: datetime | None, country, have: set[str]) -> dict[str, Any]:
    from src.osm.places_summary import part_for

    data, info = part_for(s, alpha3, "freshness", country, have)
    n = int(data["counts"].get("n", 0))
    carrying = int(data["counts"].get("check_date", 0))
    out: dict[str, Any] = {"n": n, "check_date": {"present": carrying, "share": _share(carrying, n)}, "age_years": list(AGE_YEARS), **_source(info)}
    if ref is None:
        reason = {"available": False, "reason": "no-reference", "detail": "neither the extract nor a change file states a date to measure the ages from"}
        out["last_edit"] = reason
        out["check_date"].update(reason)
        return out
    rd = ref.date()
    cuts = [_years_before(rd, y) for y in AGE_YEARS]
    buckets, stamped = _age_counts(data["days"], rd)
    out["last_edit"] = {"available": True, "buckets": [{"bucket": k, "places": buckets[k], "share": _share(buckets[k], n)} for k in (*AGE_BUCKETS, "after")],
                        "no_timestamp": n - stamped}
    # check_date: the stored text of each distinct value (a few thousand at most), aged in Python.
    counts = dict.fromkeys((*AGE_BUCKETS, "after"), 0)
    unreadable = 0
    for value, k in data["values"].get("check_date", []):
        d = parse_check_date(value)
        if d is None:
            unreadable += int(k)
        else:
            counts[_age_bucket(d, rd, cuts)] += int(k)
    out["check_date"].update(
        {
            "available": True,
            "buckets": [{"bucket": k, "places": counts[k], "share": _share(counts[k], n)} for k in (*AGE_BUCKETS, "after")],
            "unreadable": unreadable,
        }
    )
    return out


# --------------------------------------------------------------------------- #
#  Changes and the planet's past                                               #
# --------------------------------------------------------------------------- #


def _freshness_rows(s, t, bucket, *where) -> list[tuple[str, str, int]]:
    """``(bucket, "edited" | "checked", places)``: places with a key row, and of those the places whose check_date was set or changed."""
    from sqlalchemy import and_, select

    edited = s.execute(select(bucket, _obj(t)).where(*where).group_by(bucket)).all()
    checked = s.execute(
        select(bucket, _obj(t)).where(*where, and_(t.c.key == "check_date", t.c.change.in_(("added", "modified")), t.c.new_value != "")).group_by(bucket)
    ).all()
    return [*[(b, "edited", int(n)) for b, n in edited], *[(b, "checked", int(n)) for b, n in checked]]


_FRESH_FIELDS = ("edited", "checked")


def _freshness_series(rows, buckets: list[str]) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = {b: dict.fromkeys(_FRESH_FIELDS, 0) for b in buckets}
    total = 0
    for b, what, n in rows:
        if b in by and what in by[b]:
            by[b][what] = n
            total += n
    return {"fields": list(_FRESH_FIELDS), "series": _series(by, buckets), "n": total}


def _groups_for(surface: str):
    return BRAND_GROUPS if surface == "brands" else SOCIAL_GROUPS


def _changes(s, alpha3: str, surface: str, w: dict[str, Any]) -> dict[str, Any]:
    """The tracked window's per-day series for one surface."""
    from src.osm.lane_models import OsmTagChange

    tc = OsmTagChange.__table__
    own = tc.c.country_alpha3 == alpha3
    stamped = tc.c.diff_timestamp.is_not(None)
    plain = tc.c.object_event.is_(None)
    day = _day(tc.c.diff_timestamp)
    if surface == "freshness":
        rows = _freshness_rows(s, tc, day, own, stamped, plain)
        buckets = sorted(set(w["days"]) | {r[0] for r in rows})
        series = _freshness_series(rows, buckets)
    else:
        groups = _groups_for(surface)
        rows = _adoption_rows(s, tc, day, own, stamped, plain, groups=groups)
        buckets = sorted(set(w["days"]) | {r[0] for r in rows})
        series = _group_series(rows, buckets, groups)
    return {"status": "ok", "tracked": w["tracked"], **series, "method": _METHODS[surface][2], "caveat": CAVEAT_CHANGES}


def _prior(s, alpha3: str, surface: str, have: set[str]) -> dict[str, Any]:
    """The planet's past for one surface, by month: the stored monthly summary when current, else computed from the history rows (``source``)."""
    import json

    from src.osm.prior_summary import rows_for

    cut, why = _prior_cut(s, alpha3, have)
    if cut is None:
        return why or {"available": False}
    rows, how = rows_for(s, alpha3, surface, cut, have)
    if surface == "freshness":
        fresh = rows.get("fresh", [])
        series = _freshness_series(fresh, sorted({r[0] for r in fresh}))
    else:
        groups = _groups_for(surface)
        adoption = rows.get("adoption", [])
        series = _group_series(adoption, sorted({r[0] for r in adoption}), groups)
    return {
        "available": True,
        "bucket": "month",
        "span": json.loads(cut.span_json) if cut.span_json else None,
        "vintage": _iso(cut.history_vintage),
        "source": how["source"],
        "summary": {k: v for k, v in how.items() if k != "source"},
        **series,
        "method": METHOD_PRIOR,
        "caveat": CAVEAT_PRIOR,
    }


# --------------------------------------------------------------------------- #
#  The page's answer                                                           #
# --------------------------------------------------------------------------- #


def _build(alpha3: str, surface: str, limit: int) -> dict[str, Any]:
    from sqlalchemy import inspect

    from src.osm.lane_models import OsmCountry
    from src.versioned import store

    if not store.lane_exists("osm"):
        return {"status": "lane-never-run", "country": alpha3, "surface": surface}
    method, caveat, _changes_method = _METHODS[surface]
    with store.lane_session("osm") as s:
        have = set(inspect(s.get_bind()).get_table_names())
        country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if country is None or country.status != "complete":
            return {"status": "not-cut", "country": alpha3, "surface": surface}
        ref = country.diff_timestamp or country.extract_vintage
        vintage = {"extract": _iso(country.extract_vintage), "last_diff": _iso(country.diff_timestamp), "reference": _iso(ref)}
        if surface == "brands":
            snap = _snapshot_brands(s, alpha3, limit, country, have)
        elif surface == "channels":
            snap = _snapshot_channels(s, alpha3, country, have)
        else:
            snap = _snapshot_freshness(s, alpha3, ref, country, have)
        w = _window(s, alpha3, have)
        if w["state"] == "ok":
            changes = _changes(s, alpha3, surface, w)
        elif w["state"] == "old-lane":
            changes = {"status": "old-lane", "reason": _OLD_LANE, "missing": w["missing"]}
        else:
            changes = {"status": "no-daily-files"}
        prior = _prior(s, alpha3, surface, have)
    return {
        "status": "ok",
        "country": alpha3,
        "surface": surface,
        "vintage": vintage,
        "snapshot": {**snap, "method": method, "caveat": caveat},
        "changes": changes,
        "prior": prior,
    }
