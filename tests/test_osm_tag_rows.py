"""The daily apply's tag-level change rows (v0.6.0 B2, S06-01 S2, Q813 = a, R428).

Expected values are written out by hand from the fixture extract's stored tags (``scripts/make_osm_fixture.py``) and from each change
file below, never computed by the code under test. Every refusal has a test that fails when the refusal is removed.
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from src.osm import apply as A
from src.osm import ingest
from src.osm.lane_models import OsmDiffRun, OsmTagChange
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, Mirror, _extract, _osc, _stamp

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
DIFF101 = _stamp(101)


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


def _run(osm_lane_dir, body_or_bytes, seq=101):
    data = body_or_bytes if isinstance(body_or_bytes, bytes) else _osc(body_or_bytes)
    rep = A.update_country("ZZ", Mirror(seq, {seq: data}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "applied", rep.reason
    return rep.diffs[0]["counts"]


def _rows():
    with store.lane_session("osm") as s:
        return [
            (r.osm_type, r.osm_id, r.key, r.change, r.old_value, r.new_value, r.diff_timestamp, r.object_version, r.country_alpha3, r.object_event)
            for r in s.query(OsmTagChange).order_by(OsmTagChange.id)
        ]


def _tags(d: dict) -> str:
    return "".join(f'<tag k="{k}" v="{v}"/>' for k, v in d.items())


# The cafe, node 5, as the fixture stores it (version 3).
CAFE = {
    "name": "Fixture Cafe", "opening_hours": "Mo-Fr 08:00-18:00", "website": "https://cafe.invalid", "phone": "+000 0000 0001",
    "email": "cafe@example.invalid", "cuisine": "coffee_shop", "wheelchair": "yes", "amenity": "cafe", "outdoor_seating": "yes",
    "name:fr": "Cafe du Test", "payment:cash": "yes",
}

D = DIFF101  # the file's own time; the objects in DAY1 say 01:00-03:00, which must never be what a row carries


def test_the_fixture_day_writes_exactly_these_rows_stamped_with_the_files_own_time(cut, osm_lane_dir):
    counts = _run(osm_lane_dir, DAY1)
    assert _rows() == [
        # created: node 30, way 40, relation 110 (the order the file applies them: nodes, ways, then relations is the file's order here)
        ("n", 30, "amenity", "added", None, "bench", D, 1, "ZZZ", "created"),
        ("w", 40, "highway", "added", None, "residential", D, 1, "ZZZ", "created"),
        ("w", 40, "name", "added", None, "New Road", D, 1, "ZZZ", "created"),
        # node 5 modified: one key changed, eight dropped by the file's shorter tag list
        ("n", 5, "cuisine", "removed", "coffee_shop", None, D, 4, "ZZZ", None),
        ("n", 5, "email", "removed", "cafe@example.invalid", None, D, 4, "ZZZ", None),
        ("n", 5, "name:fr", "removed", "Cafe du Test", None, D, 4, "ZZZ", None),
        ("n", 5, "opening_hours", "modified", "Mo-Fr 08:00-18:00", "Mo-Su 07:00-19:00", D, 4, "ZZZ", None),
        ("n", 5, "outdoor_seating", "removed", "yes", None, D, 4, "ZZZ", None),
        ("n", 5, "payment:cash", "removed", "yes", None, D, 4, "ZZZ", None),
        ("n", 5, "phone", "removed", "+000 0000 0001", None, D, 4, "ZZZ", None),
        ("n", 5, "website", "removed", "https://cafe.invalid", None, D, 4, "ZZZ", None),
        ("n", 5, "wheelchair", "removed", "yes", None, D, 4, "ZZZ", None),
        # way 12 modified, its shape kept (the vertices could not all be found): the tags are still the file's
        ("w", 12, "maxspeed", "removed", "30", None, D, 4, "ZZZ", None),
        ("w", 12, "name", "modified", "Fixture Road", "Renamed Road", D, 4, "ZZZ", None),
        ("w", 12, "surface", "removed", "asphalt", None, D, 4, "ZZZ", None),
        # node 7 deleted: every key it held, with an empty value kept as a value
        ("n", 7, "amenity", "removed", "pharmacy", None, D, 4, "ZZZ", "deleted"),
        ("n", 7, "name", "removed", "Fixture Pharmacy", None, D, 4, "ZZZ", "deleted"),
        ("n", 7, "opening_hours", "removed", "", None, D, 4, "ZZZ", "deleted"),
        ("r", 110, "name", "added", None, "New Estate", D, 1, "ZZZ", "created"),
        ("r", 110, "tourism", "added", None, "attraction", D, 1, "ZZZ", "created"),
    ]
    # Objects that wrote NOTHING, and why each is counted elsewhere: 31 outside the border, 32 and 34 untagged, 33 another class, way 41 not
    # placed, relation 111 not placed, node 8 older than stored, node 6 moved out of the country (the world did not change).
    assert counts["tag_rows"] == 20
    assert (counts["tags_unchanged"], counts["tags_unknown_before"], counts["version_absent"]) == (0, 0, 0)
    assert (counts["other_class"], counts["outside_country"], counts["ways_not_placed"], counts["relations_not_placed"]) == (1, 1, 1, 1)
    assert (counts["older_than_stored"], counts["left_country"]) == (1, 1)


def test_the_rows_and_the_run_are_one_transaction_and_the_run_counts_them(cut, osm_lane_dir):
    _run(osm_lane_dir, DAY1)
    with store.lane_session("osm") as s:
        counts_json = s.query(OsmDiffRun).one().counts_json
        assert s.query(OsmTagChange).count() == 20
    assert json.loads(counts_json)["tag_rows"] == 20


def test_an_empty_diff_a_diff_of_unkept_classes_and_a_geometry_only_modify_write_no_row_and_say_why(cut, osm_lane_dir):
    # the negative-space fixture of the brief (S2 acceptance)
    assert _run(osm_lane_dir, "")["tag_rows"] == 0
    other_class_and_outside = (
        '<create><node id="60" version="1" timestamp="2025-01-12T01:00:00Z" lat="0.15" lon="0.15"><tag k="foo" v="bar"/></node>'
        '<node id="61" version="1" timestamp="2025-01-12T01:00:00Z" lat="0.5" lon="0.5"><tag k="shop" v="bakery"/></node></create>'
    )
    counts = _run(osm_lane_dir, other_class_and_outside, seq=102)
    assert (counts["other_class"], counts["outside_country"], counts["tag_rows"]) == (1, 1, 0)
    # the cafe moved a little and kept every tag; the road's file says new vertices it cannot place and keeps every tag
    geometry_only = (
        f'<modify><node id="5" version="4" timestamp="2025-01-13T01:00:00Z" lat="0.151" lon="0.151">{_tags(CAFE)}</node>'
        '<way id="12" version="4" timestamp="2025-01-13T01:00:00Z"><nd ref="20"/><nd ref="21"/>'
        '<tag k="name" v="Fixture Road"/><tag k="highway" v="residential"/><tag k="surface" v="asphalt"/><tag k="maxspeed" v="30"/></way></modify>'
    )
    counts = _run(osm_lane_dir, geometry_only, seq=103)
    assert counts["updated"] == 2 and counts["tag_rows"] == 0 and counts["tags_unchanged"] == 2, "counted, not silent"
    assert _rows() == []


def test_a_modify_of_an_object_the_lane_did_not_hold_writes_no_row_because_its_old_tags_are_unknown(cut, osm_lane_dir):
    # An unheld node gains a kept class: every key would read "added", which is a claim about a past the lane never saw.
    body = '<modify><node id="70" version="5" timestamp="2025-01-12T01:00:00Z" lat="0.15" lon="0.15"><tag k="amenity" v="bench"/></node></modify>'
    counts = _run(osm_lane_dir, body)
    assert counts["inserted"] == 1, "the object enters the lane"
    assert counts["tags_unknown_before"] == 1 and counts["tag_rows"] == 0
    assert _rows() == []


def test_a_missing_version_is_stored_absent_and_counted_never_made_up(cut, osm_lane_dir):
    body = (
        '<modify><node id="5" timestamp="2025-01-12T01:00:00Z" lat="0.15" lon="0.15">'
        f'{_tags({**CAFE, "phone": "+000 0000 9999"})}</node></modify>'
    )
    counts = _run(osm_lane_dir, body)
    assert _rows() == [("n", 5, "phone", "modified", "+000 0000 0001", "+000 0000 9999", D, None, "ZZZ", None)]
    assert counts["version_absent"] == 1


def test_a_stored_object_that_stops_qualifying_writes_its_real_key_changes_as_left_class_and_a_deleted_one_every_key(cut, osm_lane_dir):
    day = (
        '<delete><way id="12" version="5" timestamp="2025-01-12T01:00:00Z"/></delete>'
        '<modify><way id="13" version="4" timestamp="2025-01-12T01:00:00Z"><nd ref="22"/><nd ref="23"/><nd ref="24"/><nd ref="25"/><nd ref="22"/>'
        '<tag k="foo" v="x"/></way>'
        '<relation id="101" version="4" timestamp="2025-01-12T01:00:00Z"><member type="way" ref="13" role="outer"/>'
        '<tag k="type" v="site"/><tag k="tourism" v="attraction"/><tag k="name" v="Fixture Estate"/></relation></modify>'
    )
    counts = _run(osm_lane_dir, day)
    assert (counts["deleted"], counts["left_class"], counts["left_country"]) == (3, 1, 1)
    assert _rows() == [
        ("w", 12, "highway", "removed", "residential", None, D, 5, "ZZZ", "deleted"),
        ("w", 12, "maxspeed", "removed", "30", None, D, 5, "ZZZ", "deleted"),
        ("w", 12, "name", "removed", "Fixture Road", None, D, 5, "ZZZ", "deleted"),
        ("w", 12, "surface", "removed", "asphalt", None, D, 5, "ZZZ", "deleted"),
        ("w", 13, "addr:city", "removed", "Fixtureville", None, D, 4, "ZZZ", "left_class"),
        ("w", 13, "addr:housenumber", "removed", "1", None, D, 4, "ZZZ", "left_class"),
        ("w", 13, "addr:postcode", "removed", "00000", None, D, 4, "ZZZ", "left_class"),
        ("w", 13, "addr:street", "removed", "Fixture Road", None, D, 4, "ZZZ", "left_class"),
        ("w", 13, "building", "removed", "yes", None, D, 4, "ZZZ", "left_class"),
        ("w", 13, "building:levels", "removed", "2", None, D, 4, "ZZZ", "left_class"),
        ("w", 13, "foo", "added", None, "x", D, 4, "ZZZ", "left_class"),
    ]
    # relation 101 left the country (its only member is gone): that is a border fact, so no row and not "unchanged" either
    assert not any(r[0] == "r" for r in _rows()) and counts["tags_unchanged"] == 0


def test_rows_are_written_in_batches_without_losing_or_repeating_one(cut, osm_lane_dir, monkeypatch):
    monkeypatch.setattr(A, "TAG_ROW_BATCH", 2)
    counts = _run(osm_lane_dir, DAY1)
    assert counts["tag_rows"] == 20 and len(_rows()) == 20
    assert len({(r[0], r[1], r[2]) for r in _rows()}) == 20


def test_a_file_that_fails_after_its_rows_were_written_leaves_none_of_them(cut, osm_lane_dir, monkeypatch):
    monkeypatch.setattr(A, "TAG_ROW_BATCH", 1)  # rows are already in the transaction when the last step fails

    def boom(*a, **k):
        raise RuntimeError("the substrate refused")

    monkeypatch.setattr(A, "_record_applied", boom)
    rep = A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "failed"
    assert _rows() == [], "a file is applied wholly or not at all"


def test_an_older_lane_file_gets_the_two_new_columns_and_keeps_its_rows(tmp_path):
    from src.versioned.store import add_missing_columns

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE osm_tag_changes (id INTEGER PRIMARY KEY, osm_type VARCHAR(1) NOT NULL, osm_id BIGINT NOT NULL, key TEXT NOT NULL, "
                "change VARCHAR(8) NOT NULL, old_value TEXT, new_value TEXT, diff_timestamp DATETIME, object_version INTEGER, recorded_at DATETIME NOT NULL)"
            )
        )
        conn.execute(sa.text("INSERT INTO osm_tag_changes (osm_type, osm_id, key, change, recorded_at) VALUES ('n', 1, 'a', 'added', '2025-01-01 00:00:00')"))
    added = add_missing_columns(engine)
    assert "osm_tag_changes.country_alpha3" in added and "osm_tag_changes.object_event" in added
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT country_alpha3, object_event FROM osm_tag_changes")).all() == [(None, None)], "no backfill: old rows say NULL"
    engine.dispose()
