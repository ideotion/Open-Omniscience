"""The node-location index cannot take the process past the memory it has without a named, recorded stop (S05-04, night 2026-10-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

libosmium's in-memory index picks its size by the extract FILE's bytes, not its node count, so a node-dense file just under the
threshold fills memory and the kernel kills the process with nothing in the run record. These tests pin the three halves of the
answer: the reading of the limit says why when it says nothing (absent, unreadable and "no limit" are different facts), the guard
stops the scan with a named error that is written to the row before any kill, and a limit that cannot be read takes the cautious
file index rather than "unlimited".
"""

from __future__ import annotations

import pytest

from src.osm import ingest, reader
from src.versioned import store
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE, HAVE_OSMIUM

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
needs_osmium = pytest.mark.skipif(not HAVE_OSMIUM, reason="needs the [geo] extra")


def _files(tmp_path, limit=None, used=None, name="v2"):
    lf, uf = tmp_path / f"{name}.limit", tmp_path / f"{name}.used"
    if limit is not None:
        lf.write_text(limit)
    if used is not None:
        uf.write_text(used)
    return (f"cgroup_{name}", str(lf), str(uf))


def test_an_absent_cgroup_file_is_named_absent_not_unlimited(tmp_path):
    r = reader.cgroup_reading((_files(tmp_path),))
    assert r["headroom_bytes"] is None and r["source"] is None
    assert any("is absent" in n for n in r["notes"])


def test_no_limit_set_is_named_as_such(tmp_path):
    for raw in ("max", "9223372036854771712"):
        r = reader.cgroup_reading((_files(tmp_path, limit=raw, used="5"),))
        assert r["headroom_bytes"] is None and any("no limit is set" in n for n in r["notes"])


def test_an_unreadable_limit_file_is_named_unreadable_and_not_read_as_no_limit(tmp_path):
    tmp_path.joinpath("v2.limit").mkdir()  # reading a directory raises OSError
    r = reader.cgroup_reading((("cgroup_v2", str(tmp_path / "v2.limit"), str(tmp_path / "v2.used")),))
    assert r["headroom_bytes"] is None
    assert any("is unreadable (IsADirectoryError)" in n for n in r["notes"]), r["notes"]
    assert not any("no limit" in n for n in r["notes"])


def test_a_limit_with_usage_gives_the_headroom_and_unreadable_usage_says_so(tmp_path):
    ok = reader.cgroup_reading((_files(tmp_path, limit="1000", used="300"),))
    assert ok["headroom_bytes"] == 700 and ok["limit_bytes"] == 1000 and ok["source"] == "cgroup_v2"
    nouse = reader.cgroup_reading((_files(tmp_path, limit="1000", name="x"),))  # no usage file written
    assert nouse["headroom_bytes"] == 1000 and any("usage is unreadable" in n for n in nouse["notes"])


def test_the_room_is_the_tighter_of_the_cgroup_and_mem_available_and_names_its_source(monkeypatch):
    monkeypatch.setattr(reader, "available_memory_bytes", lambda: 8000)
    monkeypatch.setattr(reader, "cgroup_reading", lambda *a: {"source": "cgroup_v2", "limit_bytes": 5000, "headroom_bytes": 3000, "notes": ["n"]})
    assert reader.memory_room() == {"room_bytes": 3000, "source": "cgroup_v2", "notes": ["n"]}
    monkeypatch.setattr(reader, "cgroup_reading", lambda *a: {"source": None, "limit_bytes": None, "headroom_bytes": None, "notes": ["absent"]})
    assert reader.memory_room()["source"] == "mem_available" and reader.memory_room()["room_bytes"] == 8000


def test_nothing_readable_is_none_with_the_reason_never_unlimited(monkeypatch):
    monkeypatch.setattr(reader, "available_memory_bytes", lambda: None)
    monkeypatch.setattr(reader, "cgroup_reading", lambda *a: {"source": None, "limit_bytes": None, "headroom_bytes": None, "notes": ["a"]})
    room = reader.memory_room()
    assert room["room_bytes"] is None and room["source"] is None
    assert "a" in room["notes"] and any("MemAvailable is unreadable" in n for n in room["notes"])


def _room(room_bytes, source="cgroup_v2"):
    return {"room_bytes": room_bytes, "source": source, "notes": []}


@needs_osmium
def test_the_scan_stops_with_a_named_error_written_to_the_row_before_the_kernel_could_kill_it(osm_lane_dir, monkeypatch):
    """Room for 3 locations: the fixture has more, so the guard trips. Without the check this cut completes (red-without)."""
    room = reader.LOCATION_REST_OF_CUT_BYTES + int(3 * reader.LOCATION_GROWTH_PEAK_FACTOR * reader._OsmiumLocations.ENTRY_BYTES) + 1
    monkeypatch.setattr(reader, "memory_room", lambda: _room(room))
    with pytest.raises(reader.LocationIndexTooLarge) as ei:
        ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium")
    assert "OO_OSM_LOCATION_INDEX=file" in str(ei.value) and "cgroup_v2" in str(ei.value)
    from src.osm.lane_models import OsmCountry

    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        assert row.status == "failed" and row.error.startswith("LocationIndexTooLarge"), row.error
        assert "bytes this process has" in row.error


@needs_osmium
def test_a_room_that_fits_does_not_stop_the_cut_and_the_record_shows_the_guard(osm_lane_dir, monkeypatch):
    monkeypatch.setattr(reader, "memory_room", lambda: _room(10 * 1024**3, "mem_available"))
    li = ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium").to_dict()["location_index"]
    assert li["index"] == "sparse_mem_array" and li["room_source"] == "mem_available"
    assert li["max_locations_in_memory"] == int(
        (10 * 1024**3 - reader.LOCATION_REST_OF_CUT_BYTES) / reader.LOCATION_GROWTH_PEAK_FACTOR / li["entry_bytes"]
    )
    assert li["nodes_set"] <= li["max_locations_in_memory"]


@needs_osmium
def test_a_limit_that_cannot_be_read_takes_the_file_index_and_the_cut_is_the_same(osm_lane_dir, monkeypatch, tmp_path):
    from tests.test_osm_ingest import _rows

    ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium")
    want = _rows()
    monkeypatch.setattr(reader, "memory_room", lambda: {"room_bytes": None, "source": None, "notes": ["cgroup_v2: x is absent"]})
    li = ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium", workdir=tmp_path / "w").to_dict()["location_index"]
    assert li["index"] == "sparse_file_array" and "could not be read" in li["rule"] and "x is absent" in li["rule"]
    assert li["max_locations_in_memory"] is None
    assert _rows() == want


@needs_osmium
def test_the_env_var_keeps_the_locations_in_a_file_whatever_the_size(osm_lane_dir, monkeypatch, tmp_path):
    monkeypatch.setenv(reader.LOCATION_INDEX_ENV, "file")
    monkeypatch.setattr(reader, "memory_room", lambda: pytest.fail("a forced file index reads no memory limit"))
    li = ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium", workdir=tmp_path / "w").to_dict()["location_index"]
    assert li["index"] == "sparse_file_array" and reader.LOCATION_INDEX_ENV in li["rule"]


@needs_osmium
def test_a_file_over_the_threshold_reads_no_memory_limit(osm_lane_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(reader.PyosmiumExtract, "ON_DISK_ABOVE", 0)
    monkeypatch.setattr(reader, "memory_room", lambda: pytest.fail("the file index needs no memory room"))
    li = ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium", workdir=tmp_path / "w").to_dict()["location_index"]
    assert li["index"] == "sparse_file_array" and "above" in li["rule"]


@needs_osmium
def test_both_ways_of_storing_a_location_are_guarded(tmp_path):
    room = reader.LOCATION_REST_OF_CUT_BYTES + int(2 * reader.LOCATION_GROWTH_PEAK_FACTOR * reader._OsmiumLocations.ENTRY_BYTES) + 1
    for call in ("set", "set_location"):
        st = reader._OsmiumLocations(tmp_path, on_disk=False, extract_bytes=1, room=_room(room), rule="t")
        assert st.describe()["max_locations_in_memory"] == 2
        from osmium.osm import Location

        arg = (1.0, 2.0) if call == "set" else (Location(2.0, 1.0),)
        getattr(st, call)(1, *arg)
        getattr(st, call)(2, *arg)
        with pytest.raises(reader.LocationIndexTooLarge):
            getattr(st, call)(3, *arg)
        st.close()
