"""The daily change files: apply them to a country, and re-baseline when they cannot be had (S06-01 S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No network anywhere: the mirror is a class that hands back bytes built here (the same rule as ``versioned.adapters.base``), and one
test runs a whole update with the airplane socket guard armed and counts zero name resolutions. The fixture is 0.4 row O's synthetic
extract, stamped with a replication sequence and time the way a Geofabrik extract is (``scripts/make_osm_fixture.py``'s ``replication``).

The expected values are written out by hand from the fixture's objects and from each change file below, never computed by the
code under test. Every refusal has a test that fails when the refusal is removed.
"""

from __future__ import annotations

import gzip
import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.osm import apply as A
from src.osm import ingest
from src.osm import replication as R
from src.osm.geometry import decode_coords, decode_rings, encode_rings
from src.osm.lane_models import OsmCountry, OsmDiffRun, OsmObject, OsmTagChange, country_basis
from src.versioned import store
from src.versioned.feed import cursor_row, open_gaps
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import generator

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

T0 = datetime(2025, 1, 10, tzinfo=UTC)  # the extract's own time
SEQ0 = 100


def _stamp(seq: int) -> datetime:
    return T0 + timedelta(days=seq - SEQ0)


def _state_text(seq: int, when: datetime) -> str:
    # The Java properties spelling: a colon is escaped.
    return f"#Fri Jan 10 00:00:00 UTC 2025\nsequenceNumber={seq}\ntimestamp={when.strftime('%Y-%m-%dT%H\\:%M\\:%SZ')}\n"


def _extract(tmp_path: Path, *, name: str = "europe-latest.osm.pbf", seq: int | None = SEQ0, when: datetime = T0) -> Path:
    g = generator()
    data = g.build((int(when.timestamp()), seq)) if seq is not None else g.build()
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _osc(body: str) -> bytes:
    return gzip.compress(f'<?xml version="1.0" encoding="UTF-8"?>\n<osmChange version="0.6">{body}</osmChange>'.encode())


class Mirror:
    """A stand-in for the mirror: states and change files by sequence, and a record of every request."""

    def __init__(self, newest: int, diffs: dict[int, bytes], *, state_time=None) -> None:
        self.newest = newest
        self.diffs = diffs
        self.when = state_time or _stamp
        self.calls: list[tuple] = []
        self.after_each = None

    def fetch_state(self, sequence=None):
        self.calls.append(("state", sequence))
        if sequence is None:
            return _state_text(self.newest, self.when(self.newest))
        if sequence not in self.diffs and sequence > self.newest:
            raise R.DiffNotFound("none")
        return _state_text(sequence, self.when(sequence))

    def fetch_diff(self, sequence, dest):
        self.calls.append(("diff", sequence))
        if sequence not in self.diffs:
            raise R.DiffNotFound("none")
        dest.write_bytes(self.diffs[sequence])
        if self.after_each:
            self.after_each(sequence)
        return len(self.diffs[sequence])


def _rows() -> dict:
    with store.lane_session("osm") as s:
        return {
            (o.osm_type, o.osm_id): SimpleNamespace(**{c.name: getattr(o, c.name) for c in OsmObject.__table__.columns})
            for o in s.query(OsmObject).all()
        }


def _snapshot() -> dict:
    with store.lane_session("osm") as s:
        return {
            (o.osm_type, o.osm_id): {c.name: getattr(o, c.name) for c in OsmObject.__table__.columns if c.name != "id"}
            for o in s.query(OsmObject)
        }


def _country() -> OsmCountry:
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        s.expunge(row)
        return row


@pytest.fixture
def cut(osm_lane_dir):
    """ZZ cut from a stamped extract named like a Geofabrik one; returns its path."""
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


# --- day 1: every clause of the apply is one object ------------------------------------------------------------------------------
DAY1 = _osc(
    """
  <create>
    <node id="30" version="1" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.16"><tag k="amenity" v="bench"/></node>
    <node id="31" version="1" timestamp="2025-01-11T01:00:00Z" lat="0.5" lon="0.5"><tag k="shop" v="bakery"/></node>
    <node id="32" version="1" timestamp="2025-01-11T01:00:00Z" lat="0.17" lon="0.13"/>
    <node id="33" version="1" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15"><tag k="foo" v="bar"/></node>
    <node id="34" version="1" timestamp="2025-01-11T01:00:00Z" lat="0.16" lon="0.14"/>
    <way id="40" version="1" timestamp="2025-01-11T01:00:00Z"><nd ref="30"/><nd ref="34"/><tag k="highway" v="residential"/><tag k="name" v="New Road"/></way>
    <way id="41" version="1" timestamp="2025-01-11T01:00:00Z"><nd ref="9998"/><nd ref="9999"/><tag k="highway" v="service"/></way>
    <relation id="110" version="1" timestamp="2025-01-11T01:00:00Z"><member type="way" ref="40" role="outer"/><tag k="tourism" v="attraction"/><tag k="name" v="New Estate"/></relation>
    <relation id="111" version="1" timestamp="2025-01-11T01:00:00Z"><member type="way" ref="9990" role="outer"/><tag k="tourism" v="attraction"/></relation>
  </create>
  <modify>
    <node id="5" version="4" timestamp="2025-01-11T02:00:00Z" lat="0.15" lon="0.15"><tag k="amenity" v="cafe"/><tag k="name" v="Fixture Cafe"/><tag k="opening_hours" v="Mo-Su 07:00-19:00"/></node>
    <node id="6" version="4" timestamp="2025-01-11T02:00:00Z" lat="0.5" lon="0.5"><tag k="shop" v="bakery"/><tag k="name" v="Fixture Bakery"/></node>
    <node id="8" version="1" timestamp="2024-01-01T00:00:00Z" lat="0.14" lon="0.16"><tag k="place" v="village"/><tag k="name" v="Older"/></node>
    <way id="12" version="4" timestamp="2025-01-11T02:00:00Z"><nd ref="20"/><nd ref="21"/><tag k="highway" v="residential"/><tag k="name" v="Renamed Road"/></way>
  </modify>
  <delete>
    <node id="7" version="4" timestamp="2025-01-11T03:00:00Z" lat="0.18" lon="0.12"/>
  </delete>"""
)

DAY1_EXPECTED_COUNTS = {
    "nodes": 9, "ways": 3, "relations": 2,
    "inserted": 3,  # node 30, way 40, relation 110 (31 is outside, 32 and 34 are untagged, 33 is another class, way 41 cannot be placed)
    "updated": 2,   # node 5, way 12 (tags only)
    "deleted": 2,   # node 7, node 6 (moved out)
    "left_class": 0, "left_country": 1, "other_class": 1, "outside_country": 1, "unreadable_position": 0,
    "ways_not_placed": 1, "geometry_kept": 1, "relations_not_placed": 1, "older_than_stored": 1, "other_country": 0,
}


def test_day_one_applies_every_clause_and_counts_what_it_dropped(cut, osm_lane_dir):
    before = _snapshot()
    src = Mirror(101, {101: DAY1})
    rep = A.update_country("ZZ", src, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert (rep.outcome, rep.from_sequence, rep.to_sequence) == ("applied", SEQ0, 101), rep.reason
    counts = rep.diffs[0]["counts"]
    assert counts == DAY1_EXPECTED_COUNTS
    rows = _rows()
    # node 30 inserted; 31 outside; 32 and 34 untagged; 33 another class
    assert ("n", 30) in rows and rows[("n", 30)].kind == "poi"
    for gone in (31, 32, 33, 34, 7, 6):
        assert ("n", gone) not in rows, gone
    # the cafe: new opening hours, new version and time
    cafe = rows[("n", 5)]
    assert cafe.version == 4 and cafe.timestamp == datetime(2025, 1, 11, 2, tzinfo=UTC)
    assert cafe.t_opening_hours == "Mo-Su 07:00-19:00" and cafe.t_name == "Fixture Cafe"
    # an OLDER version never overwrites: the village keeps its name and version 3
    assert rows[("n", 8)].t_name == "Fixtureville" and rows[("n", 8)].version == 3
    # the road: new tags, OLD shape (its vertices were not all findable)
    road = rows[("w", 12)]
    assert road.t_name == "Renamed Road" and road.version == 4
    assert (road.geom, road.lat, road.lon, road.node_count) == (before[("w", 12)]["geom"], before[("w", 12)]["lat"], before[("w", 12)]["lon"], before[("w", 12)]["node_count"])
    # way 40: placed from the file's own nodes 30 (0.15, 0.16) and 34 (0.16, 0.14): mean (0.155, 0.15)
    new_way = rows[("w", 40)]
    assert decode_coords(new_way.geom) == [(0.15, 0.16), (0.16, 0.14)]
    assert (new_way.lat, new_way.lon, new_way.node_count) == (0.155, 0.15, 2)
    assert ("w", 41) not in rows, "a way whose vertices cannot be found is never placed from guesses"
    # relation 110 is placed by way 40, which this same file created (relations are applied after every way)
    assert ("r", 110) in rows and json.loads(rows[("r", 110)].members) == [["w", 40, "outer"]]
    assert ("r", 111) not in rows
    # untouched rows are byte-identical
    after = _snapshot()
    for key in (("n", 8), ("w", 13), ("r", 100), ("r", 101)):
        assert after[key] == before[key], key


def test_the_position_the_cursor_the_run_and_the_basis_all_move_together_in_one_transaction(cut, osm_lane_dir):
    row0 = _country()
    assert (row0.extract_sequence, row0.diff_sequence) == (SEQ0, None)
    assert country_basis(row0) == row0.finished_at.isoformat(), "before any update the basis is exactly what it always was"
    A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    row = _country()
    assert (row.diff_sequence, row.diff_timestamp) == (101, _stamp(101))
    assert country_basis(row) == f"{row.finished_at.isoformat()}+diff101"
    with store.lane_session("osm") as s:
        runs = s.query(OsmDiffRun).all()
        assert [(r.alpha3, r.sequence, r.diff_timestamp) for r in runs] == [("ZZZ", 101, _stamp(101))]
        assert runs[0].bytes_fetched == len(DAY1) and runs[0].fetch_seconds is not None and runs[0].apply_seconds is not None
        assert json.loads(runs[0].counts_json)["deleted"] == 2
        cur = cursor_row(s, A.feed_name("ZZZ"))
        assert cur is not None and cur.token == "101"
        assert open_gaps(s, A.feed_name("ZZZ")) == [], "an ordinary day leaves no gap"
        assert s.query(OsmTagChange).count() == 0, "S2 writes the tag rows, this does not"


def test_an_update_resolves_ZERO_names_and_leaves_no_work_file(cut, osm_lane_dir, monkeypatch):
    from src.ingest import clear_kill_switch
    from src.ingest.airplane import install_airplane_socket_guard

    clear_kill_switch()
    install_airplane_socket_guard()
    seen: list = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (seen.append(a), real(*a, **k))[1])
    work = osm_lane_dir / "w"
    A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=work)
    assert seen == [], f"the update resolved {len(seen)} name(s)"
    assert not any(work.iterdir()), "the change file is deleted after it is applied"


# --- day 2 and the derived tables ---------------------------------------------------------------------------------------------
DAY2 = _osc(
    """
  <delete><way id="12" version="5" timestamp="2025-01-12T01:00:00Z"/></delete>
  <modify>
    <way id="13" version="4" timestamp="2025-01-12T01:00:00Z"><nd ref="22"/><nd ref="23"/><nd ref="24"/><nd ref="25"/><nd ref="22"/><tag k="foo" v="x"/></way>
    <relation id="101" version="4" timestamp="2025-01-12T01:00:00Z"><member type="way" ref="13" role="outer"/><tag k="type" v="site"/><tag k="tourism" v="attraction"/><tag k="name" v="Fixture Estate"/></relation>
  </modify>"""
)


def test_two_days_in_one_run_and_a_retagged_way_leaves_its_class_and_its_relation_leaves_the_country(cut, osm_lane_dir):
    rep = A.update_country("ZZ", Mirror(102, {101: DAY1, 102: DAY2}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert (rep.outcome, rep.to_sequence, [d["sequence"] for d in rep.diffs]) == ("applied", 102, [101, 102])
    c2 = rep.diffs[1]["counts"]
    # way 12 deleted; way 13 lost its building tag (left its class); relation 101's only member is gone so it left the country
    assert (c2["deleted"], c2["left_class"], c2["left_country"], c2["updated"], c2["inserted"]) == (3, 1, 1, 0, 0)
    rows = _rows()
    for gone in (("w", 12), ("w", 13), ("r", 101)):
        assert gone not in rows, gone
    assert ("r", 100) in rows, "the country's own border relation is never lost to a rule about members"


def test_the_derived_indexes_read_as_stale_after_a_change_and_current_after_the_rebuild(cut, osm_lane_dir):
    from src.osm import places

    places.build_search_index("ZZZ")
    assert [r["indexed"] for r in places.index_state()] == [True]
    rep = A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    # the run rebuilt both indexes once, from the objects as they now stand
    assert rep.search_index is not None and rep.view_index is not None
    assert [r["indexed"] for r in places.index_state()] == [True]
    with store.lane_session("osm") as s:
        assert s.query(OsmCountry).one().diff_sequence == 101


def test_a_quiet_day_advances_the_position_and_the_indexes_are_rebuilt_to_match_it(cut, osm_lane_dir):
    """Before: a file that changed nothing moved the basis but rebuilt nothing, so search and geocoding dropped the country until someone refreshed."""
    from src.osm import places

    places.build_search_index("ZZZ")
    quiet = _osc("")
    unrelated = _osc('<create><node id="900" version="1" timestamp="2025-01-11T00:00:00Z" lat="0.6" lon="0.6"><tag k="foo" v="1"/></node>'
                     '<way id="901" version="1" timestamp="2025-01-11T00:00:00Z"><nd ref="1"/><tag k="waterway" v="river"/></way></create>')
    before = _snapshot()
    rep = A.update_country("ZZ", Mirror(102, {101: quiet, 102: unrelated}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "applied" and rep.to_sequence == 102
    assert [d["counts"]["inserted"] + d["counts"]["updated"] + d["counts"]["deleted"] for d in rep.diffs] == [0, 0]
    assert _snapshot() == before
    assert rep.search_index is not None and rep.view_index is not None, "the indexes are rebuilt to the new basis"
    assert [r["indexed"] for r in places.index_state()] == [True]


def test_an_empty_mirror_state_is_current_and_writes_nothing(cut, osm_lane_dir):
    rep = A.update_country("ZZ", Mirror(SEQ0, {}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert (rep.outcome, rep.to_sequence) == ("current", SEQ0)
    with store.lane_session("osm") as s:
        assert s.query(OsmDiffRun).count() == 0 and cursor_row(s, A.feed_name("ZZZ")) is None


def test_running_again_after_a_run_asks_for_nothing_it_already_applied(cut, osm_lane_dir):
    m = Mirror(101, {101: DAY1})
    A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    m.calls.clear()
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "current"
    assert [c for c in m.calls if c[0] == "diff"] == [], "no change file is requested twice"


# --- a file that will not apply ---------------------------------------------------------------------------------------------------
def test_a_change_file_that_breaks_half_way_changes_nothing_and_is_named(cut, osm_lane_dir):
    before = _snapshot()
    broken = gzip.compress(
        b'<osmChange version="0.6"><create><node id="30" version="1" lat="0.15" lon="0.16"><tag k="amenity" v="bench"/></node>'
        b'<way id="40" version="1"><nd ref="notanumber"/><tag k="highway" v="residential"/></way></create></osmChange>'
    )
    rep = A.update_country("ZZ", Mirror(101, {101: broken}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "failed" and "change file 101 did not apply" in (rep.reason or "")
    assert _snapshot() == before, "the bench created before the break was rolled back with the rest"
    row = _country()
    assert row.diff_sequence is None
    with store.lane_session("osm") as s:
        assert s.query(OsmDiffRun).count() == 0
        cur = cursor_row(s, A.feed_name("ZZZ"))
        assert cur is not None and cur.token == str(SEQ0), "the cursor stands where the extract left it"


def test_a_file_that_is_not_gzip_is_a_named_failure_too(cut, osm_lane_dir):
    rep = A.update_country("ZZ", Mirror(101, {101: b"not gzip at all"}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "failed" and _country().diff_sequence is None


def test_a_state_file_for_another_sequence_stops_the_run_unread(cut, osm_lane_dir):
    m = Mirror(101, {101: DAY1})
    m.fetch_state = lambda sequence=None: _state_text(777 if sequence is not None else 101, T0)  # type: ignore[method-assign]
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "mirror-unreadable" and _country().diff_sequence is None


# --- retention and the re-baseline -------------------------------------------------------------------------------------------------
def test_past_the_retention_the_update_asks_for_a_rebaseline_before_it_requests_a_single_file(cut, osm_lane_dir):
    far = SEQ0 + 200
    m = Mirror(far, {}, state_time=lambda s: T0 + timedelta(days=100))
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "rebaseline_needed" and "days older than the mirror's newest" in (rep.reason or "")
    assert [c for c in m.calls if c[0] == "diff"] == [], "not one change file was requested"
    assert _country().diff_sequence is None


def test_ninety_days_exactly_is_still_inside_the_retention(cut, osm_lane_dir):
    m = Mirror(101, {101: _osc("")}, state_time=lambda s: T0 + timedelta(days=90))
    assert A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False).outcome == "applied"


def test_a_file_the_mirror_no_longer_holds_ends_in_a_rebaseline_after_the_files_before_it_were_applied(cut, osm_lane_dir):
    m = Mirror(103, {101: DAY1, 102: DAY2})  # 103 is missing: the mirror 404s it
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "rebaseline_needed" and rep.owed_remaining == 1
    assert (rep.to_sequence, _country().diff_sequence) == (102, 102), "what could be applied was"


def test_rebaseline_cuts_the_country_again_and_publishes_the_gap_as_a_retention_gap(cut, osm_lane_dir):
    A.update_country("ZZ", Mirror(102, {101: DAY1, 102: DAY2}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    later = T0 + timedelta(days=200)
    (osm_lane_dir / "fresh").mkdir()
    fresh = _extract(osm_lane_dir / "fresh", seq=SEQ0 + 200, when=later)
    out = A.rebaseline("ZZ", fresh, reason="the first change file owed was past the retention", reader="python")
    assert (out["from_sequence"], out["to_sequence"]) == (102, SEQ0 + 200)
    row = _country()
    assert (row.extract_sequence, row.diff_sequence, row.extract_vintage) == (SEQ0 + 200, None, later)
    with store.lane_session("osm") as s:
        gaps = open_gaps(s, A.feed_name("ZZZ"))
        assert [(g.reason, g.from_token, g.to_token) for g in gaps] == [("retention", "102", "300")]
        assert gaps[0].from_time == _stamp(102) and gaps[0].to_time == later and gaps[0].detected_at is not None
        assert cursor_row(s, A.feed_name("ZZZ")).token == "300"
    # the objects are the fresh cut's: node 30 (created by day 1) is not in the new extract
    assert ("n", 30) not in _rows() and ("w", 12) in _rows()
    # and the next update starts from the new baseline
    m = Mirror(301, {301: _osc("")}, state_time=lambda s: later + timedelta(days=s - 300))
    assert A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False).outcome == "applied"


def test_a_rebaseline_refuses_an_extract_with_no_sequence_or_no_newer_than_the_data(cut, osm_lane_dir):
    A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    snap = _snapshot()
    (osm_lane_dir / "n").mkdir()
    (osm_lane_dir / "o").mkdir()
    no_seq = _extract(osm_lane_dir / "n", seq=None)
    older = _extract(osm_lane_dir / "o", seq=101)  # equal to the position: not newer
    with pytest.raises(A.RebaselineRefused, match="no replication sequence"):
        A.rebaseline("ZZ", no_seq, reason="x", reader="python")
    with pytest.raises(A.RebaselineRefused, match="not newer"):
        A.rebaseline("ZZ", older, reason="x", reader="python")
    assert _snapshot() == snap and _country().diff_sequence == 101, "a refused extract cut nothing"


def test_a_country_cut_again_by_hand_after_an_update_publishes_a_budget_gap_on_the_next_update(cut, osm_lane_dir):
    A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    ingest.ingest_country(cut, "ZZ", reader="python")  # the operator re-cut from the same extract: position is back to 100
    assert _country().diff_sequence is None
    A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    with store.lane_session("osm") as s:
        gaps = open_gaps(s, A.feed_name("ZZZ"))
        assert [(g.reason, g.from_token, g.to_token) for g in gaps] == [("budget", "101", "100")]
        assert cursor_row(s, A.feed_name("ZZZ")).token == "101"


# --- the gates ---------------------------------------------------------------------------------------------------------------------
def test_airplane_mode_stops_the_update_before_one_request_and_says_so_by_name(cut, osm_lane_dir):
    m = Mirror(101, {101: DAY1})
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: True)
    assert rep.outcome == "refused" and rep.reason == R.KILL_SWITCH_TEXT and "airplane mode" in rep.reason
    assert m.calls == [], "the mirror was not asked anything"
    assert _country().diff_sequence is None


def test_airplane_mode_thrown_between_two_files_keeps_the_first_and_stops_the_second(cut, osm_lane_dir):
    flag = {"on": False}
    m = Mirror(102, {101: DAY1, 102: DAY2})
    m.after_each = lambda seq: flag.__setitem__("on", True)
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: flag["on"])
    assert (rep.outcome, rep.reason, rep.to_sequence, rep.owed_remaining) == ("refused", R.KILL_SWITCH_TEXT, 101, 1)
    assert ("diff", 102) not in m.calls


def test_the_real_kill_switch_refuses_the_guarded_source_with_the_named_sentence(osm_lane_dir):
    from src.ingest import activate_kill_switch, clear_kill_switch

    activate_kill_switch()
    try:
        src = R.GuardedDiffSource("europe")
        with pytest.raises(R.DiffRefused) as ei:
            src.fetch_state()
        assert str(ei.value) == R.KILL_SWITCH_TEXT
        with pytest.raises(R.DiffRefused):
            src.fetch_diff(5, osm_lane_dir / "x.osc.gz")
        assert not (osm_lane_dir / "x.osc.gz").exists()
    finally:
        clear_kill_switch()


def test_a_run_budget_stops_without_a_gap_and_the_next_run_continues(cut, osm_lane_dir):
    m = Mirror(102, {101: DAY1, 102: DAY2})
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", max_files=1, kill_switch=lambda: False)
    assert (rep.outcome, rep.to_sequence, rep.owed_remaining) == ("stopped", 101, 1)
    with store.lane_session("osm") as s:
        assert open_gaps(s, A.feed_name("ZZZ")) == [], "a budget stop is not a hole in the stream"
    rep2 = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert (rep2.outcome, rep2.to_sequence, [d["sequence"] for d in rep2.diffs]) == ("applied", 102, [102])


@pytest.mark.parametrize("exc,outcome", [(R.DiffRefused("refused: proxy"), "refused"), (R.DiffUnavailable("HTTP 503"), "unavailable"), (R.ReplicationError("bad"), "mirror-unreadable")])
def test_each_failure_of_the_mirror_has_its_own_outcome_and_applies_nothing(cut, osm_lane_dir, exc, outcome):
    class Broken(Mirror):
        def fetch_state(self, sequence=None):
            raise exc

    rep = A.update_country("ZZ", Broken(101, {}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == outcome and _country().diff_sequence is None


# --- a country that cannot be updated says why --------------------------------------------------------------------------------------
def test_no_lane_and_no_country_and_a_legacy_cut_are_each_named(osm_lane_dir):
    m = Mirror(101, {101: DAY1})
    assert A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False).reason == "no OpenStreetMap country has been cut yet"
    path = _extract(osm_lane_dir)
    ingest.ingest_country(path, "ZZ", reader="python")
    assert A.update_country("FR", m, kill_switch=lambda: False).reason == "this country has no finished cut to update"
    with store.lane_session("osm") as s:
        s.query(OsmCountry).one().border_rings = None
    assert "before its border was kept" in A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False).reason
    assert m.calls == [], "none of these asked the mirror anything"


def test_an_extract_with_no_sequence_or_not_named_like_a_region_cannot_be_updated(osm_lane_dir):
    m = Mirror(101, {101: DAY1})
    ingest.ingest_country(_extract(osm_lane_dir, seq=None), "ZZ", reader="python")
    assert "carries no replication sequence" in A.update_country("ZZ", m, kill_switch=lambda: False).reason
    ingest.ingest_country(_extract(osm_lane_dir, name="mine.osm.pbf"), "ZZ", reader="python")
    assert "not one of the mirror's regions" in A.update_country("ZZ", m, kill_switch=lambda: False).reason
    assert m.calls == []


# --- the pieces ------------------------------------------------------------------------------------------------------------------------
def test_the_cut_keeps_the_border_and_the_header_sequence(cut):
    row = _country()
    assert row.extract_sequence == SEQ0 and row.extract_vintage == T0
    rings = decode_rings(row.border_rings)
    assert len(rings) == 1 and rings[0][0] == rings[0][-1]
    assert sorted(set(rings[0])) == [(0.1, 0.1), (0.1, 0.2), (0.2, 0.1), (0.2, 0.2)]


def test_the_default_fixture_still_has_no_replication_header():
    from tests._osm_lane_helpers import FIXTURE

    assert generator().build() == FIXTURE.read_bytes()


@pytest.mark.parametrize("data", [b"", b"\x01", b"\x01\x05\x00"])
def test_a_damaged_border_blob_is_a_value_error_never_a_short_border(data):
    with pytest.raises(ValueError):
        decode_rings(data)


def test_border_rings_round_trip():
    rings = [[(0.1, 0.1), (0.1, 0.2), (0.2, 0.2), (0.1, 0.1)], [(-1.5, 2.25), (-1.5, 2.5), (-1.25, 2.5), (-1.5, 2.25)]]
    assert decode_rings(encode_rings(rings)) == rings
    blob = encode_rings(rings)
    with pytest.raises(ValueError):
        decode_rings(blob + b"\x00")
    with pytest.raises(ValueError):
        decode_rings(blob[:-1])


def test_parse_state_reads_the_properties_spelling_and_refuses_everything_else():
    st = R.parse_state(_state_text(4123, datetime(2026, 11, 4, 3, 20, tzinfo=UTC)))
    assert (st.sequence, st.timestamp) == (4123, datetime(2026, 11, 4, 3, 20, tzinfo=UTC))
    for bad in ("", "sequenceNumber=abc\ntimestamp=2026-11-04T03\\:20\\:00Z", "sequenceNumber=5", "sequenceNumber=5\ntimestamp=2026-11-04T03:20:00",
                "sequenceNumber=-5\ntimestamp=2026-11-04T03\\:20\\:00Z"):
        with pytest.raises(R.ReplicationError):
            R.parse_state(bad)


@pytest.mark.parametrize("seq,path", [(0, "000/000/000"), (4123, "000/004/123"), (1234567, "001/234/567"), (999_999_999, "999/999/999")])
def test_sequence_path_is_three_groups_of_three_digits(seq, path):
    assert R.sequence_path(seq) == path


@pytest.mark.parametrize("bad", [-1, 1_000_000_000, True, "5", None])
def test_sequence_path_refuses_what_is_not_a_sequence(bad):
    with pytest.raises(R.ReplicationError):
        R.sequence_path(bad)


def test_region_of_reads_only_a_regions_own_file_name():
    assert R.region_of("europe-latest.osm.pbf") == "europe" and R.region_of("north-america-latest.osm.pbf") == "north-america"
    for bad in (None, "", "europe.osm.pbf", "../europe-latest.osm.pbf", "europe/france-latest.osm.pbf", "Europe-latest.osm.pbf", "europe-latest.osm.pbf.bak"):
        assert R.region_of(bad) is None, bad


def test_updates_base_is_built_from_the_download_managers_host_and_refuses_a_path_that_escapes():
    assert R.updates_base("europe") == "https://download.geofabrik.de/europe-updates"
    for bad in ("../x", "europe/france", "", "a b"):
        with pytest.raises(R.ReplicationError):
            R.updates_base(bad)


def test_plan_updates_boundaries():
    t = _stamp
    st = R.ReplicationState
    plan = R.plan_updates
    assert plan(applied_sequence=5, applied_timestamp=t(5), remote=st(5, t(5))).action == "current"
    assert plan(applied_sequence=5, applied_timestamp=t(5), remote=st(4, t(5))).action == "mirror-behind"
    p = plan(applied_sequence=5, applied_timestamp=T0, remote=st(8, T0 + timedelta(days=3)))
    assert (p.action, p.first, p.last) == ("apply", 6, 8)
    assert plan(applied_sequence=5, applied_timestamp=T0, remote=st(6, T0 + timedelta(days=90))).action == "apply"
    assert plan(applied_sequence=5, applied_timestamp=T0, remote=st(6, T0 + timedelta(days=90, seconds=1))).action == "rebaseline"
    unknown = plan(applied_sequence=5, applied_timestamp=None, remote=st(6, T0 + timedelta(days=900)))
    assert unknown.action == "apply" and unknown.days_behind is None, "without a time there is nothing to compare; the fetch finds out"


class _Resp:
    def __init__(self, status=200, body=b"", text=""):
        self.status_code, self._body, self.text = status, body, text
        self.closed = False

    def iter_content(self, n):
        yield self._body[:3]
        yield self._body[3:]

    def close(self):
        self.closed = True


def test_the_guarded_source_builds_its_urls_and_maps_each_answer_to_its_own_failure(osm_lane_dir):
    urls: list[str] = []
    answers = iter([_Resp(200, text="state"), _Resp(200, b"abcdef"), _Resp(404), _Resp(503)])

    class Sess:
        def get(self, url, **kw):
            urls.append(url)
            assert kw["stream"] is True
            return next(answers)

    src = R.GuardedDiffSource("europe", session_factory=lambda url: Sess())
    assert src.fetch_state() == "state"
    assert src.fetch_diff(4123, osm_lane_dir / "d.osc.gz") == 6 and (osm_lane_dir / "d.osc.gz").read_bytes() == b"abcdef"
    with pytest.raises(R.DiffNotFound):
        src.fetch_state(4123)
    with pytest.raises(R.DiffUnavailable, match="503"):
        src.fetch_diff(5, osm_lane_dir / "e.osc.gz")
    assert urls == [
        "https://download.geofabrik.de/europe-updates/state.txt",
        "https://download.geofabrik.de/europe-updates/000/004/123.osc.gz",
        "https://download.geofabrik.de/europe-updates/000/004/123.state.txt",
        "https://download.geofabrik.de/europe-updates/000/000/005.osc.gz",
    ]


def test_the_real_session_carries_the_host_list_so_a_redirect_elsewhere_is_refused(osm_lane_dir):
    sess = R.GuardedDiffSource("europe")._session("https://download.geofabrik.de/europe-updates/state.txt")
    assert tuple(sess.allowed_hosts) == ("download.geofabrik.de",)


def test_a_body_that_stops_half_way_keeps_no_half_file(osm_lane_dir):
    class Cut(_Resp):
        def iter_content(self, n):
            yield b"abc"
            raise OSError("connection reset")

    class Sess:
        def get(self, url, **kw):
            return Cut()

    dest = osm_lane_dir / "h.osc.gz"
    with pytest.raises(R.DiffUnavailable):
        R.GuardedDiffSource("europe", session_factory=lambda u: Sess()).fetch_diff(1, dest)
    assert not dest.exists()


def test_parse_osc_reads_positions_node_refs_and_members_and_refuses_what_it_cannot_read():
    import io

    from src.osm.changes import parse_osc

    doc = (b'<osmChange><create><node id="1" version="1" lat="1.5" lon="-2.5"/>'
           b'<way id="2"><nd ref="1"/><nd ref="3"/></way>'
           b'<relation id="4"><member type="way" ref="2" role="outer"/><member type="node" ref="1" role=""/></relation></create></osmChange>')
    n, w, r = list(parse_osc(io.BytesIO(doc)))
    assert (n.lat, n.lon) == (1.5, -2.5) and w.refs == (1, 3) and r.members == (("w", 2, "outer"), ("n", 1, ""))
    for bad in (b'<osmChange><create><way id="2"><nd ref="x"/></way></create></osmChange>',
                b'<osmChange><create><relation id="4"><member type="thing" ref="2"/></relation></create></osmChange>'):
        with pytest.raises(ValueError):
            list(parse_osc(io.BytesIO(bad)))


# --- the Opus read of the first B1 head (what it found, each pinned) --------------------------------------------------------------
def _insert_foreign_row(alpha3: str, osm_id: int, lat: float, lon: float, tags: dict, version: int = 3) -> None:
    """A row another country's cut holds (the unique key on (type, id) spans every country)."""
    from sqlalchemy import insert

    from src.osm.lane_models import osm_objects_table

    kind, pkey, pval, notable = A.T.classify(tags, is_way=False)
    row = ingest.build_row(
        "n", osm_id, version, None, tags, kind=kind, pkey=pkey, pval=pval, notable=notable, alpha3=alpha3, lat=lat, lon=lon, geom=None,
        node_count=None, members=None,
    )
    with store.lane_session("osm") as s:
        s.execute(insert(osm_objects_table), row)


def test_a_change_to_another_countrys_row_is_left_alone_and_counted(cut, osm_lane_dir):
    """Before: the lookup ignored country_alpha3, so a region-wide file deleted a neighbour's row (outside this border) or took it over (inside)."""
    _insert_foreign_row("YYY", 777, 5.0, 5.0, {"amenity": "cafe"})  # outside ZZ's border
    _insert_foreign_row("YYY", 778, 0.15, 0.15, {"amenity": "cafe"})  # a row whose id the file puts INSIDE ZZ's border
    day = _osc(
        '<modify><node id="777" version="4" timestamp="2025-01-11T00:00:00Z" lat="5" lon="5"><tag k="amenity" v="cafe"/></node>'
        '<node id="778" version="4" timestamp="2025-01-11T00:00:00Z" lat="0.15" lon="0.15"><tag k="amenity" v="cafe"/></node></modify>'
        '<delete><node id="777" version="5" timestamp="2025-01-11T00:00:00Z" lat="5" lon="5"/></delete>'
    )
    before = _snapshot()
    rep = A.update_country("ZZ", Mirror(101, {101: day}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "applied" and rep.diffs[0]["counts"]["other_country"] == 3
    c = rep.diffs[0]["counts"]
    assert (c["inserted"], c["updated"], c["deleted"], c["left_country"]) == (0, 0, 0, 0)
    after = _snapshot()
    assert after == before, "another country's rows are byte-identical, and no row of theirs changed hands"
    assert after[("n", 778)]["country_alpha3"] == "YYY" and ("n", 777) in after


def test_a_relation_is_not_placed_by_another_countrys_member(cut, osm_lane_dir):
    _insert_foreign_row("YYY", 880, 5.0, 5.0, {"amenity": "cafe"})
    day = _osc('<create><relation id="120" version="1" timestamp="2025-01-11T00:00:00Z"><member type="node" ref="880" role=""/>'
               '<tag k="tourism" v="attraction"/></relation></create>')
    rep = A.update_country("ZZ", Mirror(101, {101: day}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.diffs[0]["counts"]["relations_not_placed"] == 1 and ("r", 120) not in _rows()


def test_a_file_that_follows_a_position_the_country_has_left_is_not_applied(cut, osm_lane_dir):
    """Before: the apply never re-read the position, so a re-cut between the fetch and the apply ended with extract 300, diff 101 and the cursor at 101."""
    later = T0 + timedelta(days=200)
    (osm_lane_dir / "fresh").mkdir()
    fresh = _extract(osm_lane_dir / "fresh", seq=SEQ0 + 200, when=later)

    def recut(seq):
        ingest.ingest_country(fresh, "ZZ", reader="python")

    m = Mirror(101, {101: DAY1})
    m.after_each = recut
    rep = A.update_country("ZZ", m, workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "superseded" and rep.diffs == [] and "cut or updated by something else" in (rep.reason or "")
    row = _country()
    assert (row.extract_sequence, row.diff_sequence) == (SEQ0 + 200, None)
    with store.lane_session("osm") as s:
        assert s.query(OsmDiffRun).count() == 0
    assert ("n", 30) not in _rows(), "day 1 was not laid over the newer baseline"


def test_a_delete_older_than_the_stored_row_does_not_remove_it(cut, osm_lane_dir):
    """Before: the version check ran for create and modify only, so an older delete removed a newer row."""
    day = _osc('<delete><node id="5" version="1" timestamp="2025-01-11T00:00:00Z" lat="0.15" lon="0.15"/></delete>')
    rep = A.update_country("ZZ", Mirror(101, {101: day}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.diffs[0]["counts"]["older_than_stored"] == 1 and rep.diffs[0]["counts"]["deleted"] == 0 and ("n", 5) in _rows()


def test_a_new_way_with_a_vertex_outside_the_bounding_box_is_still_placed_as_the_cut_places_it(cut, osm_lane_dir):
    """Before: only nodes inside the border's box were kept from the file, so one vertex just outside left the way unplaced."""
    nodes = "".join(
        f'<node id="{i}" version="1" timestamp="2025-01-11T00:00:00Z" lat="{lat}" lon="{lat}"/>'
        for i, lat in ((60, 0.11), (61, 0.12), (62, 0.13), (63, 0.35))  # 63 is outside the box (0.1..0.2); the mean (0.1775) is inside
    )
    way = ('<way id="64" version="1" timestamp="2025-01-11T00:00:00Z"><nd ref="60"/><nd ref="61"/><nd ref="62"/><nd ref="63"/>'
           '<tag k="highway" v="residential"/></way>')
    rep = A.update_country("ZZ", Mirror(101, {101: _osc(f"<create>{nodes}{way}</create>")}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    c = rep.diffs[0]["counts"]
    assert (c["inserted"], c["ways_not_placed"]) == (1, 0)
    assert _rows()[("w", 64)].node_count == 4


def test_a_relation_listed_before_its_member_way_is_placed_after_it(cut, osm_lane_dir):
    """Relations are held back until every node and way is stored; applied inline this one would find no member and be dropped."""
    day = _osc(
        '<create><relation id="130" version="1" timestamp="2025-01-11T00:00:00Z"><member type="way" ref="70" role="outer"/>'
        '<tag k="tourism" v="attraction"/></relation>'
        '<node id="71" version="1" timestamp="2025-01-11T00:00:00Z" lat="0.12" lon="0.12"/>'
        '<node id="72" version="1" timestamp="2025-01-11T00:00:00Z" lat="0.14" lon="0.14"/>'
        '<way id="70" version="1" timestamp="2025-01-11T00:00:00Z"><nd ref="71"/><nd ref="72"/><tag k="building" v="yes"/></way></create>'
    )
    rep = A.update_country("ZZ", Mirror(101, {101: day}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.diffs[0]["counts"]["relations_not_placed"] == 0 and ("r", 130) in _rows() and ("w", 70) in _rows()


def test_the_border_relation_stays_the_countrys_even_when_none_of_its_members_is_stored(cut, osm_lane_dir):
    """The cut's rule: a relation is in the country when it IS the border relation. Without that clause this modify would delete relation 100."""
    day = _osc('<modify><relation id="100" version="4" timestamp="2025-01-11T00:00:00Z"><member type="way" ref="9990" role="outer"/>'
               '<tag k="boundary" v="administrative"/><tag k="name" v="Renamed"/></relation></modify>')
    rep = A.update_country("ZZ", Mirror(101, {101: day}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    c = rep.diffs[0]["counts"]
    assert (c["updated"], c["deleted"], c["left_country"]) == (1, 0, 0) and ("r", 100) in _rows()


def test_a_non_finite_coordinate_is_no_position():
    import io

    from src.osm.changes import parse_osc

    doc = b'<osmChange><modify><node id="1" version="2" lat="nan" lon="inf"/></modify></osmChange>'
    (n,) = list(parse_osc(io.BytesIO(doc)))
    assert (n.lat, n.lon) == (None, None)


class _FakeResp:
    status_code = 200
    text = "ok"

    def close(self):
        pass


@pytest.mark.parametrize("raised", ["transport", "redirect"])
def test_the_session_refusals_are_named_as_refusals_not_as_a_failed_mirror(raised):
    """Before: only DiffRefused raised by the SOURCE was tested; the session's own two exceptions were never mapped under test."""
    from src.safety.fetcher import RedirectRefused, TransportUnavailable

    class Sess:
        def get(self, url, **kw):
            if raised == "transport":
                raise TransportUnavailable("no proxy")
            raise RedirectRefused("host")

    with pytest.raises(R.DiffRefused):
        R.GuardedDiffSource("europe", session_factory=lambda u: Sess()).fetch_state()


def test_a_connection_error_while_the_switch_is_engaged_is_named_as_airplane_mode(monkeypatch):
    """The socket-level guard raises inside urllib3 and requests wraps it as a ConnectionError: the switch is asked again to name it."""
    import requests

    class Sess:
        def get(self, url, **kw):
            raise requests.exceptions.ConnectionError("wrapped")

    src = R.GuardedDiffSource("europe", session_factory=lambda u: Sess())
    monkeypatch.setattr(R, "_kill_switch_engaged", lambda: True)
    with pytest.raises(R.DiffRefused) as ei:
        src.fetch_state()
    assert str(ei.value) == R.KILL_SWITCH_TEXT
    monkeypatch.setattr(R, "_kill_switch_engaged", lambda: False)
    with pytest.raises(R.DiffUnavailable):
        src.fetch_state()


def test_the_derived_rows_of_a_deleted_object_go_with_it_not_left_pointing_at_a_reused_id(cut, osm_lane_dir, monkeypatch):
    """``_clear_derived`` finds the R*Tree rows through the country's objects, so it has to run before the objects are deleted."""
    from sqlalchemy import text

    from src.osm import places, view

    places.build_search_index("ZZZ")
    view.build_view_index("ZZZ")
    with store.lane_session("osm") as s:
        pharmacy = s.execute(text("SELECT id FROM osm_objects WHERE osm_type='n' AND osm_id=7")).scalar_one()
        assert s.execute(text("SELECT count(*) FROM osm_rtree WHERE id=:i"), {"i": pharmacy}).scalar_one() == 1, "the premise: it was indexed"
    monkeypatch.setattr(A, "_rebuild_indexes", lambda alpha3, report: None)  # a rebuild that failed must leave no orphan either
    A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    with store.lane_session("osm") as s:
        assert s.execute(text("SELECT count(*) FROM osm_objects WHERE id=:i"), {"i": pharmacy}).scalar_one() == 0
        stale = s.execute(text("SELECT count(*) FROM osm_rtree WHERE id NOT IN (SELECT id FROM osm_objects)")).scalar_one()
        assert stale == 0, "no R*Tree row points at an id no object holds"
