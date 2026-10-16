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


def _tree(tmp_path, *, v2=None, v1=None, proc=None):
    """A fake cgroup mount: ``v2``/``v1`` map a relative cgroup dir to ``{file name: content}``; ``proc`` is /proc/self/cgroup."""
    root = tmp_path / "cg"
    for sub, tree in (("", v2 or {}), ("memory", v1 or {})):
        for rel, files in tree.items():
            d = root / sub / rel
            d.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                (d / name).write_text(content)
    root.mkdir(exist_ok=True)
    pc = tmp_path / "proc_cgroup"
    if proc is not None:
        pc.write_text(proc)
    return reader.cgroup_reading(str(root), str(pc))


def test_an_absent_cgroup_file_is_named_absent_not_unlimited(tmp_path):
    r = _tree(tmp_path, proc="0::/\n")
    assert r["headroom_bytes"] is None and r["source"] is None and not r["unreadable"]
    assert any("memory.max is absent" in n for n in r["notes"])


def test_no_limit_set_is_named_as_such_and_only_max_or_the_sentinel_means_it(tmp_path):
    for raw in ("max", "9223372036854771712"):
        r = _tree(tmp_path / raw[:3], v2={"": {"memory.max": raw, "memory.current": "5"}}, proc="0::/\n")
        assert r["headroom_bytes"] is None and not r["unreadable"] and any("no limit is set" in n for n in r["notes"])
    for raw in ("", "garbled", "-1"):  # S3: not "no limit": a limit that cannot be understood
        r = _tree(tmp_path / ("x" + raw[:3]), v2={"": {"memory.max": raw}}, proc="0::/\n")
        assert r["unreadable"] and r["headroom_bytes"] is None, raw
        assert any("is unparseable" in n for n in r["notes"]) and not any("no limit" in n for n in r["notes"])


def test_an_unreadable_limit_file_is_named_unreadable_and_not_read_as_no_limit(tmp_path):
    (tmp_path / "cg" / "memory.max").mkdir(parents=True)  # reading a directory raises OSError
    pc = tmp_path / "pc"
    pc.write_text("0::/\n")
    r = reader.cgroup_reading(str(tmp_path / "cg"), str(pc))
    assert r["headroom_bytes"] is None and r["unreadable"]
    assert any("is unreadable (IsADirectoryError)" in n for n in r["notes"]), r["notes"]
    assert not any("no limit" in n for n in r["notes"])


def test_a_limit_with_usage_gives_the_headroom_and_unreadable_usage_is_never_counted_as_free(tmp_path):
    ok = _tree(tmp_path / "a", v2={"": {"memory.max": "1000", "memory.current": "300"}}, proc="0::/\n")
    assert ok["headroom_bytes"] == 700 and ok["limit_bytes"] == 1000 and ok["source"] == "cgroup_v2"
    nouse = _tree(tmp_path / "b", v2={"": {"memory.max": "1000"}}, proc="0::/\n")  # no usage file written (S2)
    assert nouse["headroom_bytes"] is None and nouse["unreadable"] and any("usage is absent" in n for n in nouse["notes"])


def test_the_limit_of_the_process_own_cgroup_or_an_ancestor_is_found_not_only_the_mount_roots(tmp_path):
    """B2: a service under a slice with MemoryMax has its limit below the mount root; the tightest level wins."""
    r = _tree(
        tmp_path / "v2",
        v2={"": {"memory.current": "9"}, "a": {"memory.max": "2000", "memory.current": "300"},
            "a/b": {"memory.current": "1"}, "a/b/c": {"memory.max": "max", "memory.current": "1"}},
        proc="0::/a/b/c\n",
    )
    assert r["headroom_bytes"] == 1700 and r["path"] == "/a" and r["source"] == "cgroup_v2", r
    tight = _tree(
        tmp_path / "tight",
        v2={"a": {"memory.max": "2000", "memory.current": "300"}, "a/b": {"memory.max": "500", "memory.current": "100"}},
        proc="0::/a/b\n",
    )
    assert tight["headroom_bytes"] == 400 and tight["path"] == "/a/b"
    v1 = _tree(
        tmp_path / "v1",
        v1={"svc": {"memory.limit_in_bytes": "800", "memory.usage_in_bytes": "200"}},
        proc="12:cpu,cpuacct:/svc\n4:memory:/svc\n",
    )
    assert v1["headroom_bytes"] == 600 and v1["source"] == "cgroup_v1" and v1["path"] == "/svc"


def test_the_own_cgroup_file_absent_reads_the_root_and_unreadable_is_a_limit_we_cannot_see(tmp_path):
    root = _tree(tmp_path / "x", v2={"": {"memory.max": "100", "memory.current": "10"}}, proc=None)
    assert root["headroom_bytes"] == 90 and any("is absent: only the cgroup mount root" in n for n in root["notes"])
    (tmp_path / "pc").mkdir()
    bad = reader.cgroup_reading(str(tmp_path / "x" / "cg"), str(tmp_path / "pc"))
    assert bad["unreadable"] and bad["headroom_bytes"] is None


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


def test_a_cgroup_limit_that_cannot_be_read_gives_no_room_even_when_mem_available_is_readable(monkeypatch):
    monkeypatch.setattr(reader, "available_memory_bytes", lambda: 8000)
    monkeypatch.setattr(reader, "cgroup_reading", lambda *a: {"source": None, "headroom_bytes": None, "unreadable": True, "notes": ["u"]})
    room = reader.memory_room()
    assert room["room_bytes"] is None and "u" in room["notes"]
    assert reader.memory_budget_bytes(room) is None  # the pure-Python path then keeps the locations in the file from the start


def test_the_growth_factor_is_the_doubling_not_the_end_count():
    """B1: the vector reallocates by doubling, so right after a doubling the old and the new buffer are both held: 2.0, not 1.68."""
    assert reader.LOCATION_GROWTH_PEAK_FACTOR >= 2.0
    assert reader.location_capacity(reader.LOCATION_REST_OF_CUT_BYTES + 32 * 1000) == 1000


def _room(room_bytes, source="cgroup_v2"):
    return {"room_bytes": room_bytes, "source": source, "notes": []}


@needs_osmium
def test_the_scan_stops_with_a_named_error_written_to_the_row_before_the_kernel_could_kill_it(osm_lane_dir, monkeypatch):
    """Room for 3 locations: the fixture has more, so the guard trips. Without the check this cut completes (red-without)."""
    room = reader.LOCATION_REST_OF_CUT_BYTES + int(3 * reader.LOCATION_GROWTH_PEAK_FACTOR * reader._OsmiumLocations.ENTRY_BYTES) + 1
    monkeypatch.setattr(reader, "memory_room", lambda: _room(room))
    monkeypatch.setattr(reader, "LOCATION_MIN_IN_MEMORY", 1)  # this room is tiny on purpose: keep the in-memory index under the guard
    monkeypatch.delenv(reader.LOCATION_INDEX_ENV, raising=False)
    with pytest.raises(reader.LocationIndexTooLarge) as ei:
        ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium")
    assert "OO_OSM_LOCATION_INDEX=file" in str(ei.value) and "cgroup_v2" in str(ei.value)
    from src.osm.lane_models import OsmCountry

    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        assert row.status == "failed" and row.error.startswith("LocationIndexTooLarge"), row.error
        assert "bytes this process has" in row.error and "held 3 locations (48 bytes settled)" in row.error  # S5: what was stored


@needs_osmium
def test_a_room_that_fits_does_not_stop_the_cut_and_the_record_shows_the_guard(osm_lane_dir, monkeypatch):
    monkeypatch.setattr(reader, "memory_room", lambda: _room(10 * 1024**3, "mem_available"))
    monkeypatch.delenv(reader.LOCATION_INDEX_ENV, raising=False)
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
    monkeypatch.delenv(reader.LOCATION_INDEX_ENV, raising=False)
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


@needs_osmium
def test_a_room_that_cannot_hold_a_useful_index_takes_the_file_up_front_not_a_stop_on_the_first_node(osm_lane_dir, monkeypatch, tmp_path):
    """S1: 200 MiB of room (page cache counts as used) is below the rest-of-cut term; main would have ingested this extract."""
    from tests.test_osm_ingest import _rows

    ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium")
    want = _rows()
    monkeypatch.delenv(reader.LOCATION_INDEX_ENV, raising=False)
    monkeypatch.setattr(reader, "memory_room", lambda: _room(200 * 1024**2))
    li = ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium", workdir=tmp_path / "w").to_dict()["location_index"]
    assert li["index"] == "sparse_file_array" and "holds fewer than" in li["rule"] and li["room_bytes"] == 200 * 1024**2
    assert _rows() == want


def test_the_env_var_is_parsed_loudly(monkeypatch):
    monkeypatch.delenv(reader.LOCATION_INDEX_ENV, raising=False)
    assert reader.location_index_choice() is None
    for raw, want in (("file", "file"), (" FILE ", "file"), ("auto", None), ("", None)):
        monkeypatch.setenv(reader.LOCATION_INDEX_ENV, raw)
        assert reader.location_index_choice() == want
    monkeypatch.setenv(reader.LOCATION_INDEX_ENV, "disk")
    with pytest.raises(ValueError, match="must be 'file' or 'auto'"):
        reader.location_index_choice()
