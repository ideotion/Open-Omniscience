"""The history cut: one country's past read out of the full-history planet (S05-04 S4, Q814 = b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The fixture is ``scripts/make_osm_history_fixture.py``'s: the current-state fixture's country
with its past versions, a deleted shop, a bench whose tags were removed, a cafe that moved in,
one that never did, and a deleted way (the stated gap). Each clause of ``src/osm/history.py``
is one object there, and each test here names which.
"""

from __future__ import annotations

import hashlib
import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.osm import history, ingest
from src.osm.lane_models import OsmHistoryChange, OsmHistoryCut, OsmTagChange
from src.versioned import store
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE, HAVE_OSMIUM, READERS, ROOT

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

HISTORY = ROOT / "tests" / "fixtures" / "osm" / "synthetic-history.osm.pbf"
T1, T2, T3 = (datetime.fromtimestamp(t, UTC) for t in (1420070400, 1577836800, 1735689600))


def _gen():
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_osm_history_fixture", ROOT / "scripts" / "make_osm_history_fixture.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _cut(reader: str) -> history.HistoryReport:
    ingest.ingest_country(FIXTURE, "ZZ", reader=reader)
    return history.ingest_history(HISTORY, FIXTURE, "ZZ", reader=reader)


def _rows() -> list[tuple]:
    with store.lane_session("osm") as s:
        return sorted(
            (r.osm_type, r.osm_id, r.object_version, r.change, r.key or "", r.old_value, r.new_value, r.version_timestamp)
            for r in s.query(OsmHistoryChange)
        )


def _of(rows, t, i):
    return [r for r in rows if r[0] == t and r[1] == i]


def test_the_committed_fixture_is_what_the_generator_writes():
    assert _gen().build() == HISTORY.read_bytes(), "regenerate: python scripts/make_osm_history_fixture.py"


def test_both_decoders_read_the_visible_flag_and_the_history_feature():
    from src.osm import pbf

    hdr = pbf.read_header(HISTORY)
    assert history.HISTORY_FEATURE in hdr.required_features
    assert hdr.replication_timestamp == datetime(2025, 1, 6, tzinfo=UTC)
    chain = [e for e in pbf.iter_elements(HISTORY) if e.id == 26 and isinstance(e, pbf.Node)]
    assert [(e.version, e.visible) for e in chain] == [(1, True), (2, False)]
    way = [e for e in pbf.iter_elements(HISTORY, nodes=False) if e.id == 15]
    assert [(e.version, e.visible) for e in way] == [(1, True), (2, False)]
    # A current extract carries no flag: every object is visible.
    assert all(e.visible for e in pbf.iter_elements(FIXTURE))


@pytest.mark.parametrize("reader", READERS)
def test_the_history_cut_records_its_measurements(osm_lane_dir, reader):
    rep = _cut(reader)
    assert rep.status == "complete" and rep.reader == reader
    with store.lane_session("osm") as s:
        row = s.query(OsmHistoryCut).filter_by(alpha3="ZZZ").one()
        assert row.status == "complete"
        assert row.history_name == HISTORY.name
        assert row.history_bytes == HISTORY.stat().st_size
        assert row.history_vintage == datetime(2025, 1, 6, tzinfo=UTC)
        assert row.ingest_seconds is not None and row.ingest_seconds >= 0
        counts = json.loads(row.counts_json)
        span = json.loads(row.span_json)
    assert span == {"oldest": T1.isoformat(), "newest": T3.isoformat()}
    # 5, 6, 7, 8 (current), 26 (deleted), 27 (untagged later), 28 (moved in); never 9 or 29.
    assert counts["nodes_inside"] == 7
    assert counts["tracked_not_in_file"] == 0


@pytest.mark.parametrize("reader", READERS)
def test_adoption_reads_as_added_at_each_version(osm_lane_dir, reader):
    """Node 5: two keys at creation, two more at version 2, the rest at version 3."""
    _cut(reader)
    cafe = _of(_rows(), "n", 5)
    assert ("n", 5, 1, "created", "", None, None, T1) in cafe
    added = {(r[2], r[4]) for r in cafe if r[3] == "added"}
    assert {(1, "amenity"), (1, "name"), (2, "opening_hours"), (2, "website"), (3, "phone")} <= added
    assert not [r for r in cafe if r[3] in ("removed", "deleted")]


@pytest.mark.parametrize("reader", READERS)
def test_an_emptied_value_is_a_modification_never_a_removal(osm_lane_dir, reader):
    """Node 7: opening_hours set, then emptied."""
    _cut(reader)
    pharmacy = _of(_rows(), "n", 7)
    assert ("n", 7, 2, "modified", "opening_hours", "Mo-Sa 09:00-19:00", "", T3) in pharmacy
    assert not [r for r in pharmacy if r[3] == "removed"]


@pytest.mark.parametrize("reader", READERS)
def test_a_deleted_shop_is_a_closure_the_extract_could_not_show(osm_lane_dir, reader):
    """Node 26: in no current cut, in the prior as created then deleted, its tags removed."""
    _cut(reader)
    butcher = _of(_rows(), "n", 26)
    assert ("n", 26, 1, "created", "", None, None, T1) in butcher
    assert ("n", 26, 2, "deleted", "", None, None, T2) in butcher
    removed = {r[4] for r in butcher if r[3] == "removed" and r[2] == 2}
    assert removed == {"shop", "name"}


@pytest.mark.parametrize("reader", READERS)
def test_tags_removed_from_a_live_node_are_not_a_deletion(osm_lane_dir, reader):
    """Node 27: the bench's tag goes, the node stays."""
    _cut(reader)
    bench = _of(_rows(), "n", 27)
    assert ("n", 27, 2, "removed", "amenity", "bench", None, T3) in bench
    assert not [r for r in bench if r[3] == "deleted"]


@pytest.mark.parametrize("reader", READERS)
def test_a_node_that_moved_in_brings_its_whole_history_and_one_never_inside_none(osm_lane_dir, reader):
    _cut(reader)
    rows = _rows()
    assert ("n", 28, 1, "created", "", None, None, T1) in rows, "the version mapped outside is its past too"
    assert not _of(rows, "n", 29), "a node never inside the border entered the prior"
    assert not _of(rows, "n", 9), "a node outside the border entered the prior"


@pytest.mark.parametrize("reader", READERS)
def test_the_stated_gap_a_deleted_way_is_NOT_in_the_prior(osm_lane_dir, reader):
    """Way 15 was deleted before the extract, so no cut kept it: the gap GAP names."""
    _cut(reader)
    rows = _rows()
    assert not _of(rows, "w", 15)
    assert "not in this history" in history.GAP
    # The current ways are there, with their past.
    assert ("w", 12, 2, "added", "maxspeed", None, "30", T3) in rows


@pytest.mark.parametrize("reader", READERS)
def test_untagged_vertices_never_become_rows(osm_lane_dir, reader):
    _cut(reader)
    rows = _rows()
    for nid in (1, 2, 3, 4, 20, 21, 22, 23, 24, 25, 30, 31):
        assert not _of(rows, "n", nid), nid


@pytest.mark.skipif(not HAVE_OSMIUM, reason="the [geo] extra is not installed")
def test_the_two_readers_write_the_same_rows(osm_lane_dir):
    _cut("python")
    python_rows = _rows()
    store.dispose_all()
    Path(store.lane_path("osm")).unlink()
    _cut("pyosmium")
    assert _rows() == python_rows


def test_the_prior_is_kept_apart_from_the_tracked_window(osm_lane_dir):
    """S06-01 states the planet's prior SEPARATELY: nothing lands in osm_tag_changes."""
    _cut("python")
    with store.lane_session("osm") as s:
        assert s.query(OsmTagChange).count() == 0
        assert s.query(OsmHistoryChange).count() > 0


def test_a_rerun_replaces_the_country_rather_than_doubling_it(osm_lane_dir):
    _cut("python")
    first = _rows()
    history.ingest_history(HISTORY, FIXTURE, "ZZ", reader="python")
    assert _rows() == first


def test_no_current_cut_is_a_refusal_by_name(osm_lane_dir):
    with pytest.raises(history.HistoryError, match="no complete cut"):
        history.ingest_history(HISTORY, FIXTURE, "ZZ", reader="python")


def test_a_current_extract_is_refused_as_history_by_name(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with pytest.raises(history.HistoryError, match="not a full-history file"):
        history.ingest_history(FIXTURE, FIXTURE, "ZZ", reader="python")


def test_redaction_gaps_are_counted_never_smoothed():
    from src.osm.pbf import Node

    counts = {"chains_starting_after_version_1": 0, "version_gaps": 0}
    chain = [Node(9, 2, T1, {"a": "1"}, 0.0, 0.0), Node(9, 4, T2, {"a": "2"}, 0.0, 0.0)]
    rows = history.object_rows("ZZZ", "n", chain, counts)
    assert counts == {"chains_starting_after_version_1": 1, "version_gaps": 1}
    assert [r["change"] for r in rows] == ["created", "added", "modified"]


def test_a_restored_object_reads_restored():
    from src.osm.pbf import Node

    counts = {"chains_starting_after_version_1": 0, "version_gaps": 0}
    chain = [
        Node(9, 1, T1, {"a": "1"}, 0.0, 0.0),
        Node(9, 2, T2, {}, 0.0, 0.0, False),
        Node(9, 3, T3, {"a": "1"}, 0.0, 0.0),
    ]
    events = [(r["object_version"], r["change"]) for r in history.object_rows("ZZZ", "n", chain, counts)]
    assert events == [(1, "created"), (1, "added"), (2, "deleted"), (2, "removed"), (3, "restored"), (3, "added")]


def test_the_history_cut_resolves_ZERO_names_with_the_socket_guard_installed(osm_lane_dir, monkeypatch):
    from src.ingest import clear_kill_switch
    from src.ingest.airplane import install_airplane_socket_guard

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    clear_kill_switch()
    install_airplane_socket_guard()
    seen: list = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (seen.append(a), real(*a, **k))[1])
    history.ingest_history(HISTORY, FIXTURE, "ZZ", reader="python")
    assert seen == [], f"the history cut resolved {len(seen)} name(s)"


def test_history_state_reads_the_cut_and_is_empty_without_a_lane(osm_lane_dir):
    assert history.history_state() == []
    _cut("python")
    (row,) = history.history_state()
    assert row["alpha3"] == "ZZZ" and row["status"] == "complete"
    assert row["counts"]["rows_deleted"] == 1
    assert row["history_vintage"] == "2025-01-06T00:00:00+00:00"


def test_the_fixture_provenance_note_pins_the_history_digest():
    note = (ROOT / "tests" / "fixtures" / "osm" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert hashlib.sha256(HISTORY.read_bytes()).hexdigest() in note
