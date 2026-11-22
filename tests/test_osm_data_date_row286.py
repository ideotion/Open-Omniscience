"""Row 286 (R775): the date of the last daily change file applied, beside the extract's date, on every OSM surface.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

d2 is ``OsmCountry.diff_timestamp``: the daily apply writes it only after a file applied in full and only when that file was
the next one owed (``src/osm/apply.py``), so it is the data time of the last file in an unbroken sequence from the extract,
never the apply time. ``country_data_date`` is the ONE reading every surface takes it from; these tests pin that each surface
(the lane list behind the picker and the map's OSM line, the completeness facts, the search index state, the object card and
the place card, the view's legend, the geography and trends vintages) carries the same answer in the three states.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.osm import ingest
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"

EXTRACT = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
LAST = datetime(2026, 11, 19, 21, 0, tzinfo=UTC)


def _set(*, seq, stamp) -> None:
    from src.osm.lane_models import OsmCountry
    from src.versioned import store

    with store.lane_session("osm") as s:
        c = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        c.extract_vintage, c.diff_sequence, c.diff_timestamp = EXTRACT, seq, stamp


def _every_surface() -> list[dict]:
    """The data date as each OSM surface's producer hands it to the page."""
    from src.osm import completeness as C
    from src.osm import places as P
    from src.osm import view as V
    from src.osm.lane_models import OsmCountry
    from src.versioned import store

    lane = next(c for c in C.countries() if c["alpha3"] == "ZZZ")
    facts = C.tag_completeness("ZZZ")
    index = next(c for c in P.index_state() if c["alpha3"] == "ZZZ")
    card = P.object_card("node/5")
    with store.lane_session("osm") as s:
        (legend,) = V._vintage(s.query(OsmCountry).filter_by(alpha3="ZZZ").all())
    as_legend = {
        "extract": legend["extract_date"],
        "last_diff": legend["last_diff"],
        "diff_sequence": legend["diff_sequence"],
        "updates": legend["updates"],
    }
    return [lane["data_date"], facts["data_date"], index["data_date"], card["data_date"], as_legend]


def test_no_file_applied_says_none_and_no_second_date(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _set(seq=None, stamp=None)
    want = {
        "extract": EXTRACT.isoformat(),
        "last_diff": None,
        "diff_sequence": None,
        "updates": "none",
    }
    assert all(d == want for d in _every_surface()), _every_surface()


def test_files_applied_carry_the_last_files_own_timestamp(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _set(seq=4321, stamp=LAST)
    want = {
        "extract": EXTRACT.isoformat(),
        "last_diff": LAST.isoformat(),
        "diff_sequence": 4321,
        "updates": "dated",
    }
    assert all(d == want for d in _every_surface()), _every_surface()


def test_a_timestamp_not_read_is_said_and_nothing_stands_in(osm_lane_dir):
    """R775: no apply time, no guess. Files applied with no recorded timestamp read as applied, date not read."""
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _set(seq=4321, stamp=None)
    want = {
        "extract": EXTRACT.isoformat(),
        "last_diff": None,
        "diff_sequence": 4321,
        "updates": "date_not_read",
    }
    assert all(d == want for d in _every_surface()), _every_surface()


def test_the_place_card_carries_the_object_cards_answer(osm_lane_dir, monkeypatch):
    from src.entities import places as EP

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _set(seq=4321, stamp=LAST)

    class _Place:
        geometry_ref = "osm.db:node/8"

    facts = EP._osm_facts(_Place())
    assert (
        facts["data_date"]["last_diff"] == LAST.isoformat()
        and facts["data_date"]["updates"] == "dated"
    )


def test_geography_and_trends_read_the_same_source(osm_lane_dir):
    """The two vintages that already named the last diff now take it, and the not-read state, from the same reading."""
    from src.osm.lane_models import OsmCountry, country_data_date
    from src.versioned import store

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    _set(seq=4321, stamp=None)
    for path in ("src/osm/geography.py", "src/osm/profile.py"):
        src = (ROOT / path).read_text(encoding="utf-8")
        assert (
            "country_data_date(" in src
            and "_iso(c.diff_timestamp)" not in src
            and "_iso(country.diff_timestamp)" not in src
        ), path
    with store.lane_session("osm") as s:
        d = country_data_date(s.query(OsmCountry).filter_by(alpha3="ZZZ").one())
    assert d["updates"] == "date_not_read" and d["last_diff"] is None


@pytest.mark.parametrize("name", ["_osmPickLaneCell", "loadOsmVintage", "_renderOsmCompleteness"])
def test_the_map_surfaces_use_the_one_wording(name):
    from tests.js_source_helper import function_source

    body = function_source((STATIC / "app-map.js").read_text(encoding="utf-8"), name)
    assert "ooOsmUpdatesHtml(" in body or "_osmVintageHead(" in body, name


def test_the_cards_use_the_one_wording():
    src = (STATIC / "app-analysis.js").read_text(encoding="utf-8")
    assert src.count("_osmCardDate(") == 3, "the helper, the object card and the place card"
    assert 'tf("OpenStreetMap data of {date}", {date: ooIsoDate(d.' not in src, (
        "a card still states the extract's date as the data's"
    )


def test_the_strings_run_as_real_code_under_node():
    out = subprocess.run(
        ["node", str(ROOT / "tests" / "osm_data_date_row286_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0 and "all assertions passed" in out.stdout, out.stdout + out.stderr
