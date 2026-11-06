"""The geography axis: choropleths by country and by admin-1 region (v0.6.0 B3c, S06-01 S4, Q816 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RANKED COUNTS, NEVER A VERDICT. Every area carries a COUNT of places, with the number of places it was counted among (``n``); the map is a
picture of the table beside it and the table is canonical. No score, no threshold, no coverage bar, and no colour scale that says «good» or
«bad»: the colour is the count (or the share of the area's own places, which the page offers beside it because a large area is darker only
because it is large).

THE MEASURES, each a count of places with metadata (``kind = 'poi'``) in the area:

* ``places``    -- the places themselves.
* ``brand``     -- places carrying ``brand`` or ``brand:wikidata`` (B3b's recorded key set; an operator is not a brand).
* ``checked``   -- places carrying a ``check_date`` (non-empty).
* ``edited_1y`` -- places whose last edit is within one year back from the vintage (the newest change file applied, else the extract's
  date -- never today's clock), as B3b's freshness surface counts it.
* ``changed``   -- places that had an ordinary tag change in the window THIS machine observed (``osm_tag_changes``, object-level events
  left out). COUNTRY LEVEL ONLY: a change row carries the country the object was in, not its region, so no region can be named here
  without guessing; the page says so rather than drawing an empty map.

The vintage of every map is its country's own: the extract's date and the newest daily change file applied (``OsmCountry.extract_vintage``
and ``diff_timestamp``), returned beside every area so the page states it on every map.

Admin-1 values come from the split counted once per country (``completeness.count_admin1``), which a recount refreshes; this module only
READS them. A split counted before these measures existed has no values for them and reads as ``not-counted-for-this`` (recount), never as
zero.

READ-ONLY, makes no request, never raises: an unreadable lane is ``status: "unreadable"`` without the error's words.
"""

from __future__ import annotations

import logging
from typing import Any

from src.monitoring.secret_scrub import log_failure
from src.osm.profile import _filled, _years_before
from src.osm.trends import _day, _iso, _obj, _window

_LOG = logging.getLogger(__name__)

MEASURES = ("places", "brand", "checked", "edited_1y", "changed")
#: The measures a region can carry (a change row has no region).
REGION_MEASURES = ("places", "brand", "checked", "edited_1y")

METHOD = (
    "Each area is a count of this country's places with metadata (objects kept as 'poi' by the OpenStreetMap lane): all of them; those "
    "carrying brand or brand:wikidata; those carrying a check_date; those last edited within a year back from the vintage; and, for whole "
    "countries only, those that had a tag changed in the window of daily change files observed on this machine. The vintage is the "
    "extract's date and the newest change file applied, stated for each country. The map is a picture of the ranked table beside it."
)
CAVEAT = (
    "A larger or denser area has more places of every kind, so a count mostly shows size; the share of the area's own places is offered "
    "beside it. A missing tag means OpenStreetMap does not record it, not that the place has none. A country the lane does not hold is not "
    "on this map, and that is a choice of what was downloaded, not a finding."
)


def brand_filled():
    """``brand`` or ``brand:wikidata`` has a non-empty value (B3b's recorded key set)."""
    return _filled("brand") | _filled("brand:wikidata")


def check_date_filled():
    """``check_date`` has a non-empty value."""
    return _filled("check_date")


def edited_within_year(reference):
    """The place's last edit falls within one year back from ``reference`` (a datetime), never after it."""
    from src.osm.lane_models import osm_objects_table as t

    rd = reference.date()
    day = _day(t.c.timestamp)
    return t.c.timestamp.is_not(None) & (day <= rd.isoformat()) & (day > _years_before(rd, 1).isoformat())


def countries_view() -> dict[str, Any]:
    """Every country the lane holds, with its counts for each measure and its vintage; never raises."""
    try:
        return _countries()
    except Exception as exc:  # noqa: BLE001 - the page names it; the error's words (paths) stay in the log
        log_failure(_LOG, "the OpenStreetMap geography could not be read", exc, level=logging.WARNING)
        return {"status": "unreadable", "detail": "the OpenStreetMap geography could not be read"}


def _edited_within_year(days: list[list], reference) -> int:
    """Places whose current version is dated within a year back from ``reference``, never after it: the day histogram cut by :func:`edited_within_year`'s own comparisons."""
    rd = reference.date()
    newest, oldest = rd.isoformat(), _years_before(rd, 1).isoformat()
    return sum(int(n) for day, n in days if oldest < day <= newest)


def _countries() -> dict[str, Any]:
    from sqlalchemy import inspect, select

    from src.osm.lane_models import OsmCountry, OsmTagChange
    from src.osm.lane_models import osm_objects_table as t
    from src.osm.places_summary import part_for
    from src.versioned import store

    if not store.lane_exists("osm"):
        return {"status": "lane-never-run"}
    areas: list[dict[str, Any]] = []
    not_cut: list[str] = []
    with store.lane_session("osm") as s:
        have = set(inspect(s.get_bind()).get_table_names())
        for c in s.query(OsmCountry).order_by(OsmCountry.alpha3):
            if c.status != "complete":
                not_cut.append(c.alpha3)
                continue
            ref = c.diff_timestamp or c.extract_vintage
            poi = (t.c.country_alpha3 == c.alpha3) & (t.c.kind == "poi")   # the changed measure below joins on it
            data, how = part_for(s, c.alpha3, "geography", c, have)
            counts = data["counts"]
            values: dict[str, int | None] = {"places": int(counts.get("n", 0)), "brand": int(counts.get("brand_any", 0)), "checked": int(counts.get("checked", 0))}
            reasons: dict[str, str] = {}
            if ref is None:
                values["edited_1y"] = None
                reasons["edited_1y"] = "no-reference"
            else:
                values["edited_1y"] = _edited_within_year(data["days"], ref)
            w = _window(s, c.alpha3, have)
            since = None
            if w["state"] == "ok":
                since = w["tracked"]["since"]
                tc = OsmTagChange.__table__
                # Places, as the other measures count them: a change row is written for every kept class (roads, buildings...), so the row
                # is joined to its object's own row, which must be a place of this country (a deleted object's earlier rows fall out with it).
                values["changed"] = int(
                    s.execute(
                        select(_obj(tc))
                        .select_from(tc.join(t, (t.c.osm_type == tc.c.osm_type) & (t.c.osm_id == tc.c.osm_id)))
                        .where(tc.c.country_alpha3 == c.alpha3, tc.c.object_event.is_(None), tc.c.diff_timestamp.is_not(None), poi)
                    ).scalar()
                    or 0
                )
            else:
                values["changed"] = None
                reasons["changed"] = w["state"]
            areas.append(
                {
                    "alpha3": c.alpha3,
                    "alpha2": c.alpha2,
                    "name": c.name,
                    "n": values["places"],
                    "values": values,
                    "reasons": reasons,
                    "vintage": {"extract": _iso(c.extract_vintage), "last_diff": _iso(c.diff_timestamp), "reference": _iso(ref)},
                    "observed_since": since,
                    "places_summary": {"source": how["source"], **{k: v for k, v in how.items() if k != "source"}},
                }
            )
    return {"status": "ok", "measures": list(MEASURES), "areas": areas, "not_cut": not_cut, "method": METHOD, "caveat": CAVEAT}
