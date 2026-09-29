"""The extract pass: one country cut from an extract into ``osm.db`` (S05-04 S1-S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The fixture is 0.4 row O's synthetic extract, extended for this lane: every clause of the cut
is one object in it (``scripts/make_osm_fixture.py`` names which). Each test runs through BOTH
readers where the ``[geo]`` extra is installed, and one test compares their rows outright, so
the small-country path and the pyosmium path cannot quietly diverge.
"""

from __future__ import annotations

import json
import socket

import pytest

from src.osm import ingest
from src.osm.geometry import BorderError, decode_coords
from src.osm.lane_models import OsmCountry, OsmObject, OsmTagChange
from src.versioned import store
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE, HAVE_OSMIUM, READERS, generator

osm_lane_dir = _osm_lane_helpers.osm_lane_dir


def _rows():
    with store.lane_session("osm") as s:
        return {
            (o.osm_type, o.osm_id): {c.name: getattr(o, c.name) for c in OsmObject.__table__.columns if c.name != "id"}
            for o in s.query(OsmObject)
        }


@pytest.mark.parametrize("reader", READERS)
def test_the_fixture_country_is_cut_with_exactly_the_kept_objects(osm_lane_dir, reader):
    rep = ingest.ingest_country(FIXTURE, "ZZ", reader=reader)
    assert rep.status == "complete"
    assert rep.reader == reader
    rows = _rows()
    assert set(rows) == {
        ("n", 5), ("n", 6), ("n", 7), ("n", 8),  # cafe, bakery, pharmacy, village
        ("w", 10), ("w", 11),  # the border's own admin ways
        ("w", 12), ("w", 13),  # the road, the building
        ("r", 100), ("r", 101),  # the country, the site relation
    }
    assert ("n", 9) not in rows, "a cafe outside the border was kept"
    assert ("w", 14) not in rows, "an untagged way became a row"
    kinds = {k: v["kind"] for k, v in rows.items()}
    assert kinds[("n", 5)] == "poi" and kinds[("n", 8)] == "place"
    assert kinds[("w", 12)] == "road" and kinds[("w", 13)] == "building"
    assert kinds[("r", 100)] == "admin"
    assert rep.counts["poi"] == 4 and rep.counts["road"] == 1 and rep.counts["building"] == 1
    assert rep.name == "Fixture Land"


@pytest.mark.parametrize("reader", READERS)
def test_no_tag_is_lost_between_the_extract_and_the_row(osm_lane_dir, reader):
    from src.osm import tags as T

    g = generator()
    ingest.ingest_country(FIXTURE, "ZZ", reader=reader)
    rows = _rows()
    expected = {("n", i): t for i, _la, _lo, t in g.LANE_NODES if t}
    expected.update({("w", i): t for i, _r, t in g.WAYS + g.LANE_WAYS if t})
    expected.update({("r", i): t for i, t, _m in [g.RELATION, *g.LANE_RELATIONS]})
    for key, row in rows.items():
        scalars = {k: row[T.column_name(k)] for k in T.SCALAR_KEYS if row[T.column_name(k)] is not None}
        fams = {col: json.loads(row[col]) for col in T.FAMILIES.values() if row[col]}
        blob = json.loads(row["other_tags"]) if row["other_tags"] else {}
        assert T.join_tags(scalars, fams, blob) == expected[key], key


@pytest.mark.parametrize("reader", READERS)
def test_negative_space_rounds_trip_as_gaps_never_as_zero(osm_lane_dir, reader):
    """S05-04 §4's skeptic matrix: an empty tag value, and a relation with no geometry."""
    ingest.ingest_country(FIXTURE, "ZZ", reader=reader)
    rows = _rows()
    assert rows[("n", 7)]["t_opening_hours"] == "", "an empty value became NULL or vanished"
    rel = rows[("r", 101)]
    assert rel["lat"] is None and rel["lon"] is None and rel["geom"] is None, "a relation got a made-up point"
    assert json.loads(rel["members"]) == [["w", 13, "outer"]]
    building = rows[("w", 13)]
    assert decode_coords(building["geom"]) == [(0.16, 0.16), (0.16, 0.17), (0.17, 0.17), (0.17, 0.16), (0.16, 0.16)]
    assert building["node_count"] == 5
    assert (building["lat"], building["lon"]) == (0.165, 0.165)
    assert rows[("n", 5)]["version"] == 3
    assert rows[("n", 5)]["timestamp"].isoformat() == "2025-01-01T00:00:00+00:00"


@pytest.mark.skipif(not HAVE_OSMIUM, reason="the [geo] extra is not installed")
def test_both_readers_write_identical_rows(osm_lane_dir, monkeypatch, tmp_path):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    a = _rows()
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "second"))
    ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium")
    assert _rows() == a


def test_the_country_row_records_what_was_measured(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "zzz", reader="python")
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).one()
        assert (row.alpha2, row.alpha3, row.status) == ("ZZ", "ZZZ", "complete")
        assert row.extract_name == "synthetic.osm.pbf", "the full path would record where the operator keeps files"
        assert row.extract_bytes == FIXTURE.stat().st_size
        assert row.extract_vintage is None, "the fixture stamps no vintage; none may be invented"
        assert row.ingest_seconds is not None and row.ingest_seconds >= 0
        assert json.loads(row.border_json)["rings"] == 1
        blob = json.loads(row.blob_json)
        assert blob["objects"] == 10
        assert blob["extended_bytes"] <= blob["q810_bytes"]


def test_re_ingest_replaces_the_country_never_doubles_it(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert len(_rows()) == 10
    with store.lane_session("osm") as s:
        assert s.query(OsmCountry).count() == 1


def test_a_country_the_extract_does_not_hold_is_REFUSED_and_recorded_failed(osm_lane_dir):
    with pytest.raises(BorderError, match="FR"):
        ingest.ingest_country(FIXTURE, "FR", reader="python")
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3="FRA").one()
        assert row.status == "failed"
        assert "BorderError" in row.error
        assert s.query(OsmObject).count() == 0


def test_an_unknown_country_code_is_refused_before_anything_opens(osm_lane_dir):
    with pytest.raises(ValueError, match="not an ISO"):
        ingest.ingest_country(FIXTURE, "XQ", reader="python")
    assert not store.lane_exists("osm")


def test_without_the_extra_any_size_is_read_in_pure_python(osm_lane_dir, monkeypatch):
    """R77: no file-size cap; only an explicit request for pyosmium without it is refused."""
    from src.osm import reader

    monkeypatch.setattr(reader, "pyosmium_version", lambda: None)
    assert reader.open_extract(FIXTURE).name == "python"
    with pytest.raises(reader.GeoExtraMissing, match="not installed"):
        reader.open_extract(FIXTURE, reader="pyosmium")


def test_the_ingest_is_the_same_in_memory_on_a_work_file_and_after_a_spill(osm_lane_dir, monkeypatch, tmp_path):
    """A budget of None (memory unreadable) uses the file from the start; 1 byte spills at the
    first node; a large one never spills. All three write the same rows, and no work file stays."""
    from src.osm import reader

    seen = []
    for budget in (10**9, None, 1):
        monkeypatch.setattr(reader, "memory_budget_bytes", lambda b=budget: b)
        ingest.ingest_country(FIXTURE, "ZZ", reader="python", workdir=tmp_path / "work")
        seen.append({k: (v["lat"], v["lon"], v["geom"]) for k, v in _rows().items()})
        assert not list((tmp_path / "work").glob("osm-locations*"))
    assert seen[0] and seen[0] == seen[1] == seen[2]


def test_the_adaptive_store_spills_past_its_budget(tmp_path):
    from src.osm.reader import DICT_BYTES_PER_NODE, _AdaptiveLocations

    st = _AdaptiveLocations(tmp_path, 3 * DICT_BYTES_PER_NODE)
    for i in range(3):
        st.set(i, float(i), -float(i))
    assert not st.spilled
    st.set(3, 3.0, -3.0)
    assert st.spilled and st.get(0) == (0.0, -0.0) and st.get(3) == (3.0, -3.0) and st.get(9) is None
    st.close()
    assert not list(tmp_path.glob("osm-locations*"))


def test_the_change_model_exists_and_stays_EMPTY_in_0_5(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        assert s.query(OsmTagChange).count() == 0


def test_a_full_ingest_resolves_ZERO_names_with_the_socket_guard_installed(osm_lane_dir, monkeypatch):
    from src.ingest import clear_kill_switch
    from src.ingest.airplane import install_airplane_socket_guard

    clear_kill_switch()
    install_airplane_socket_guard()
    seen: list = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (seen.append(a), real(*a, **k))[1])
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert seen == [], f"the ingest resolved {len(seen)} name(s)"


def test_osm_db_is_encrypted_with_the_corpus_passphrase(osm_lane_dir, monkeypatch):
    """Q825 = a: «Same answers as the Wikipedia lane» -- encrypted alike, no exceptions."""
    from src.database.connect import is_encrypted_file, set_passphrase

    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", "the osm lane shares it", raising=False)
    try:
        ingest.ingest_country(FIXTURE, "ZZ", reader="python")
        assert is_encrypted_file(store.lane_path("osm")) is True
    finally:
        store.dispose_all()
        set_passphrase(None)


def test_the_location_work_file_is_deleted_after_the_run(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    work = osm_lane_dir / "osm_work"
    assert not work.exists() or not any(work.iterdir())


@pytest.mark.skipif(not HAVE_OSMIUM, reason="the [geo] extra is not installed")
def test_the_on_disk_location_index_is_used_and_then_deleted(osm_lane_dir, monkeypatch):
    """A continent extract puts the box's node locations in a file; it must not outlive the run."""
    from src.osm import reader

    monkeypatch.setattr(reader.PyosmiumExtract, "ON_DISK_ABOVE", 0)
    made: list = []
    real = reader._OsmiumLocations.__init__

    def spy(self, workdir, *, on_disk):
        real(self, workdir, on_disk=on_disk)
        made.append(self._file)

    monkeypatch.setattr(reader._OsmiumLocations, "__init__", spy)
    rep = ingest.ingest_country(FIXTURE, "ZZ", reader="pyosmium")
    assert rep.counts["building"] == 1, "the ways read no locations from the file index"
    assert made and made[0] is not None
    assert not made[0].exists(), "the location index outlived the ingest"
