"""Row 292 (R776): the place gazetteer states the last applied daily OSM file's date beside the extract's.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The build reads ``osm_objects`` as they stand, after any daily change files, so dating the artifact by the extract alone put a
place created by a daily file into a gazetteer dated before it existed. The build now takes each country's data date from R775's
one reading (``country_data_date``) and records it; the artifact's ``as_of`` and each entry's vintage carry both dates; a country
whose files were applied without a recorded date says "not-read"; with nothing applied the artifact is what it was, byte for byte.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.catalog import cities
from src.entities import gazetteer_build as G
from tests import _osm_lane_helpers
from tests.test_gazetteer_build import WD_FIXTURE, _run, _seed

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = Path(__file__).resolve().parents[1]


def _position(*, seq, stamp) -> None:
    from src.osm.lane_models import OsmCountry
    from src.versioned.store import lane_session

    with lane_session("osm") as s:
        c = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        c.extract_vintage = datetime(2026, 10, 1, tzinfo=UTC)
        c.diff_sequence, c.diff_timestamp = seq, stamp


def _build(tmp_path):
    rc, data, out = _run(tmp_path, "--wikidata-fixture", str(WD_FIXTURE))
    assert rc == 0, data
    return out


def test_nothing_applied_writes_the_artifact_as_before(osm_lane_dir):
    _seed()
    _position(seq=None, stamp=None)
    out = _build(osm_lane_dir)
    text = out.read_text("utf-8")
    doc = yaml.safe_load(text)
    assert doc["as_of"] == "2026-10-01"
    assert doc["countries"] == [{"alpha2": "ZZ", "alpha3": "ZZZ", "extract_vintage": "2026-10-01"}]
    assert "last_diff" not in text and "not-read" not in text
    # the same input renders the same bytes, and a country record with no last_diff renders as it always did
    assert (
        G.render_yaml(
            [],
            countries=[{"alpha2": "ZZ", "alpha3": "ZZZ", "vintage": "2026-10-01"}],
            wikidata={"joined": False},
            built=datetime(2026, 10, 6).date(),
        ).count("last_diff")
        == 0
    )
    assert {c.vintage for c in cities.load_cities(out)} == {"2026-10-01"}


def test_applied_files_put_both_dates_in_the_artifact_and_on_each_entry(osm_lane_dir):
    _seed()
    _position(seq=101, stamp=datetime(2026, 11, 19, 21, 0, tzinfo=UTC))
    out = _build(osm_lane_dir)
    doc = yaml.safe_load(out.read_text("utf-8"))
    assert doc["countries"] == [
        {
            "alpha2": "ZZ",
            "alpha3": "ZZZ",
            "extract_vintage": "2026-10-01",
            "last_diff": "2026-11-19",
        }
    ]
    assert doc["as_of"] == "2026-10-01+2026-11-19"
    vintages = {c.vintage for c in cities.load_cities(out)}
    assert vintages == {"2026-10-01+2026-11-19"}, vintages
    assert all(len(v) <= 32 for v in vintages), "the place column is String(32)"


def test_files_applied_without_a_recorded_date_say_not_read_never_the_extract_alone(osm_lane_dir):
    _seed()
    _position(seq=101, stamp=None)
    out = _build(osm_lane_dir)
    doc = yaml.safe_load(out.read_text("utf-8"))
    assert doc["countries"][0]["last_diff"] == "not-read"
    assert doc["as_of"] == "2026-10-01+not-read"
    assert {c.vintage for c in cities.load_cities(out)} == {"2026-10-01+not-read"}


def test_each_entry_is_dated_by_its_own_country(tmp_path):
    """Two countries, one updated: an entry of the other keeps its own extract date, never the updated one's."""
    doc = {
        "as_of": "2026-09-01+2026-11-19",
        "countries": [
            {"alpha2": "AA", "alpha3": "AAA", "extract_vintage": "2026-09-01"},
            {
                "alpha2": "BB",
                "alpha3": "BBB",
                "extract_vintage": "2026-10-01",
                "last_diff": "2026-11-19",
            },
        ],
        "cities": [
            {"name": "Ay", "lat": 1, "lon": 1, "country": "AA", "osm": "node/1"},
            {"name": "Bee", "lat": 2, "lon": 2, "country": "BB", "osm": "node/2"},
            {"name": "Sea", "lat": 3, "lon": 3, "country": "CC", "osm": "node/3"},
        ],
    }
    p = tmp_path / "places.yml"
    p.write_text(yaml.safe_dump(doc), "utf-8")
    got = {c.name: c.vintage for c in cities.load_cities(p)}
    assert got == {
        "Ay": "2026-09-01",
        "Bee": "2026-10-01+2026-11-19",
        "Sea": "2026-09-01+2026-11-19",
    }


def test_a_gazetteer_built_before_r776_keeps_its_recorded_date(tmp_path):
    doc = {
        "as_of": "2026-10-01",
        "countries": [{"alpha2": "AA", "alpha3": "AAA", "extract_vintage": "2026-10-01"}],
        "cities": [{"name": "Ay", "lat": 1, "lon": 1, "country": "AA", "osm": "node/1"}],
    }
    p = tmp_path / "places.yml"
    p.write_text(yaml.safe_dump(doc), "utf-8")
    assert [c.vintage for c in cities.load_cities(p)] == ["2026-10-01"]


def test_the_place_card_runs_as_real_code_under_node():
    out = subprocess.run(
        ["node", str(ROOT / "tests" / "gazetteer_date_row292_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert out.returncode == 0 and "all assertions passed" in out.stdout, out.stdout + out.stderr
