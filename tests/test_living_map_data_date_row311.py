"""Row 311 (R790): Living sources states the date of the map data from the cut countries' own data dates.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Maps column always said the date of the map data was "not recorded", though the lane reads each extract's own date at the cut and
the last applied daily file's own date at every update. The daily block now gives the newest and the oldest data date over the cut
countries, from R775's one reading (``country_data_date``): the last file's own date where files were applied, the extract's where none
was. A country whose files were applied without their date being read is named apart and enters neither. Expected values are written
out from the fixtures' own times, never computed by the block.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime

from src.osm import daily_view as V
from src.osm.lane_models import OsmCountry
from src.versioned import store
from tests import _osm_lane_helpers
from tests import test_osm_daily_view as _dv

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
cut = _dv.cut
ROOT = pathlib.Path(__file__).resolve().parents[1]


def _country(alpha3, *, extract, seq=None, stamp=None):
    with store.lane_session("osm") as s:
        s.add(
            OsmCountry(
                alpha2=alpha3[:2],
                alpha3=alpha3,
                status="complete",
                extract_vintage=extract,
                diff_sequence=seq,
                diff_timestamp=stamp,
            )
        )


def test_nothing_applied_gives_the_extracts_own_date_as_newest_and_oldest(cut):
    with store.lane_session("osm") as s:
        extract = s.query(OsmCountry.extract_vintage).filter_by(alpha3="ZZZ").scalar()
    got = V.daily_block()
    want = extract.replace(tzinfo=extract.tzinfo or UTC).isoformat()
    assert got["newest_data_at"] == want and got["oldest_data_at"] == want
    assert got["date_not_read"] == [] and got["data_undated"] == 0


def test_newest_and_oldest_are_each_countrys_own_data_date_never_the_apply_time(cut):
    _country("AAA", extract=datetime(2026, 9, 1, tzinfo=UTC))
    _country(
        "BBB",
        extract=datetime(2026, 9, 2, tzinfo=UTC),
        seq=7,
        stamp=datetime(2026, 11, 19, 21, 0, tzinfo=UTC),
    )
    got = V.daily_block()
    assert got["newest_data_at"] == "2026-11-19T21:00:00+00:00", "BBB's last daily file's own date"
    assert got["oldest_data_at"] < "2026-09-02", got["oldest_data_at"]


def test_a_country_applied_without_a_read_date_is_named_apart_and_in_neither_date(cut):
    _country("AAA", extract=datetime(2026, 9, 1, tzinfo=UTC))
    # CCC: an extract far newer and far older than the rest would move either end if it were (wrongly) read as its data date.
    _country("CCC", extract=datetime(2000, 1, 1, tzinfo=UTC), seq=9, stamp=None)
    got = V.daily_block()
    assert got["date_not_read"] == ["CCC"]
    assert got["oldest_data_at"] > "2000-01-02", (
        "the extract date of an updated, undated country entered the oldest"
    )
    assert got["countries_updated"] == 1


def test_a_country_whose_extract_states_no_date_is_counted_apart(cut):
    _country("DDD", extract=None)
    got = V.daily_block()
    assert got["data_undated"] == 1 and got["date_not_read"] == []
    assert got["newest_data_at"] is not None, "the dated countries still give their dates"


def test_the_new_wording_ships_in_every_language_and_never_says_current_as_of():
    keys = [
        "Newest map data",
        "Oldest map data",
        "Data date not read",
        "Extract states no date",
        "Downloaded files not yet cut",
    ]
    js = (ROOT / "src" / "static" / "app-living.js").read_text(encoding="utf-8")
    for k in keys:
        assert f't("{k}")' in js, k
    for p in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        assert all(d.get(k) for k in keys), p.name
        assert "current as of" not in json.dumps({k: d[k] for k in keys}).lower()
