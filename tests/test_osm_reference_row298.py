"""Row 298: "edited within a year" is never measured from the extract's date once daily files were applied undated.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three producers took their reference as ``diff_timestamp or extract_vintage``. When daily change files were applied but their date
was not read (R775's ``date_not_read``), that fell back to the extract's date, so the lane's data, newer than the extract by an
unknown span, was aged from a date older than itself, and the profile even reported that date as the reference. The reference now
comes from ``country_data_date`` through ``country_reference``: in that state there is none, and each surface says why
(``date-not-read``) instead of computing anything.
"""

from __future__ import annotations

import json
import pathlib

from src.osm import geography as GEO
from src.osm.completeness import admin1_state, count_admin1
from src.osm.lane_models import OsmCountry, country_reference
from src.versioned import store
from tests import _osm_lane_helpers
from tests import test_osm_geography as _geo
from tests.test_osm_geography import _area, _outlines, _regions, _seed, _seed_points
from tests.test_osm_profile import _snap

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
cut = _geo.cut
ROOT = pathlib.Path(__file__).resolve().parents[1]
NEW = "Not available: daily change files were applied and their data date was not read, so there is no date to measure the ages from."


def _undated(seq=2):
    """Daily files applied through sequence ``seq``, their own date not recorded."""
    with store.lane_session("osm") as s:
        c = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        c.diff_sequence, c.diff_timestamp = seq, None


def test_the_one_reading_gives_no_reference_when_the_date_was_not_read(cut):
    with store.lane_session("osm") as s:
        c = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        assert country_reference(c) == (c.extract_vintage, None), (
            "nothing applied: the extract's own date, as before"
        )
        c.diff_sequence, c.diff_timestamp = 2, None
        assert country_reference(c) == (None, "date-not-read")
        c.extract_vintage = None
        assert country_reference(c) == (None, "date-not-read"), (
            "applied undated says so even when the extract has no date either"
        )
        c.diff_sequence = None
        assert country_reference(c) == (None, "no-reference")


def test_geography_computes_no_edited_figure_against_the_extract(cut):
    _seed()
    assert _area(GEO.countries_view())["values"]["edited_1y"] == 1, (
        "the fixture counts one place against the extract's date"
    )
    _undated()
    a = _area(GEO.countries_view())
    assert a["values"]["edited_1y"] is None and a["reasons"]["edited_1y"] == "date-not-read"
    assert a["vintage"]["reference"] is None and a["vintage"]["updates"] == "date_not_read"
    assert a["values"]["places"] == 5, "the other measures do not need a date"


def test_freshness_ages_nothing_and_reports_no_reference_date(cut):
    _seed()
    _undated()
    got = _snap("freshness")
    snap = got["snapshot"]
    assert (
        snap["last_edit"]["available"] is False and snap["last_edit"]["reason"] == "date-not-read"
    )
    assert "buckets" not in snap["last_edit"]
    assert (
        snap["check_date"]["available"] is False and snap["check_date"]["reason"] == "date-not-read"
    )
    assert got["vintage"]["reference"] is None, "the extract's date was reported as the reference"


def test_admin1_stores_no_edited_figure_for_its_regions(cut, tmp_path):
    _seed()
    _seed_points()
    _undated()
    path = _outlines(tmp_path)
    count_admin1("ZZZ", path=path)
    regs = _regions(admin1_state("ZZZ", path=path))
    assert all("edited_1y" not in (r["measures"] or {}) for r in regs.values()), (
        "a region was aged from the extract's date"
    )
    assert regs["ZZ-W"]["measures"]["brand"] == 2, "the other measures are still counted"


def test_the_map_says_why_in_every_language():
    js = (ROOT / "src" / "static" / "app-map.js").read_text(encoding="utf-8")
    assert js.count('"date-not-read"') >= 2 and js.count(NEW) == 2, (
        "the geography/admin1 reason and the freshness line"
    )
    assert '(lane.data_date || {}).updates === "date_not_read"' in js
    for p in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        assert json.loads(p.read_text(encoding="utf-8")).get(NEW), p.name


def test_a_split_counted_before_the_fix_shows_no_edited_figure_once_the_date_is_unread(
    cut, tmp_path
):
    """A split stored while the date was unread (by the old code) keeps a matching basis, so it reads as current: its edited_1y is not shown."""
    from src.osm.lane_models import OsmAdmin1Split

    _seed()
    _seed_points()
    _undated()
    path = _outlines(tmp_path)
    count_admin1("ZZZ", path=path)
    with store.lane_session(
        "osm"
    ) as s:  # what the old code stored: an edited_1y aged from the extract's date
        row = s.query(OsmAdmin1Split).filter_by(alpha3="ZZZ").one()
        stored = json.loads(row.regions_json)
        stored["ZZ-W"]["measures"]["edited_1y"] = 1
        row.regions_json = json.dumps(stored)
    st = admin1_state("ZZZ", path=path)
    assert st["status"] == "complete"
    regs = _regions(st)
    assert "edited_1y" not in regs["ZZ-W"]["measures"] and regs["ZZ-W"]["measures"]["brand"] == 2
