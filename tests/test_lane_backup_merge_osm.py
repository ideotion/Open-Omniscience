"""Living sources in a backup: the maps lane, copied country by country (R729, R739).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two "machines" are two data directories, as in the wiki and law merge tests. Machine B cuts
the synthetic country from the committed fixture (and, where a test says so, applies a daily
change file to it); its maps lane is snapshotted as a backup member; machine A imports it.

R739: the country is the unit. A finished country A lacks is copied whole in one transaction;
a country both hold keeps A's copy whole and the backup's is counted (and reported when it is
newer); a country the backup never finished is never copied; nothing is replaced or deleted;
the first daily update after an import applies from the copied cursor.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.backup import lane_merge
from src.osm import apply as A
from src.osm import history, ingest
from src.osm.lane_models import (
    OsmCountry,
    OsmDiffRun,
    OsmHistoryChange,
    OsmHistoryCut,
    OsmObject,
    OsmSearchIndex,
    OsmTagChange,
    OsmViewIndex,
    country_basis,
)
from src.versioned import store
from src.versioned.models import VersionedChange
from tests import test_osm_apply as T
from tests._osm_lane_helpers import FIXTURE

HISTORY = FIXTURE.parent / "synthetic-history.osm.pbf"


@pytest.fixture
def machines(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()

    def use(which: Path) -> None:
        store.dispose_all()
        monkeypatch.setenv("OO_DATA_DIR", str(which))
        store.create_lane("osm")

    store.dispose_all()
    yield a, b, use
    store.dispose_all()


def _cut_here(where: Path, *, day1: bool = False) -> None:
    path = T._extract(where)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    if day1:
        rep = A.update_country("ZZ", T.Mirror(101, {101: T.DAY1}), workdir=where / "w", kill_switch=lambda: False)
        assert rep.outcome == "applied", rep.reason


def _snap(b: Path, use, tmp_path: Path, *, edit=None) -> Path:
    use(b)
    if edit is not None:
        con = sqlite3.connect(b / "osm.db")
        try:
            edit(con)
            con.commit()
        finally:
            con.close()
        store.dispose_lane("osm")
    snap = tmp_path / "snap" / "osm.db"
    entry = lane_merge.snapshot_lane_for_backup("osm", snap)
    assert entry["name"] == "lanes/osm.db"
    store.dispose_lane("osm")
    return snap


def _objects() -> dict:
    with store.lane_session("osm") as s:
        return {
            (o.osm_type, o.osm_id): {c.name: getattr(o, c.name) for c in OsmObject.__table__.columns if c.name != "id"}
            for o in s.query(OsmObject)
        }


def _country_row() -> dict | None:
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3="ZZZ").one_or_none()
        if row is None:
            return None
        return {c.name: getattr(row, c.name) for c in OsmCountry.__table__.columns if c.name != "id"}


def _records() -> dict:
    with store.lane_session("osm") as s:
        return {
            "tag_changes": sorted((r.osm_type, r.osm_id, r.key, r.change, r.old_value, r.new_value) for r in s.query(OsmTagChange)),
            "runs": sorted((r.alpha3, r.sequence, r.diff_timestamp) for r in s.query(OsmDiffRun)),
            "feed": sorted((r.feed, r.change_ref, r.cursor_token) for r in s.query(VersionedChange)),
            "history": sorted((r.osm_type, r.osm_id, r.object_version, r.change, r.key or "") for r in s.query(OsmHistoryChange)),
            "cuts": sorted((r.alpha3, r.status) for r in s.query(OsmHistoryCut)),
        }


def _b_state(b: Path, use) -> tuple[dict, dict | None, dict]:
    use(b)
    return _objects(), _country_row(), _records()


def _db_path() -> str:
    from src.versioned.store import lane_path

    return str(lane_path("osm"))


def test_a_finished_country_this_machine_lacks_is_copied_whole_and_its_indexes_rebuilt(machines, tmp_path):
    a, b, use = machines
    use(b)
    _cut_here(b, day1=True)
    want_objects, want_country, want_records = _b_state(b, use)
    assert want_records["tag_changes"] and want_records["runs"] and want_records["feed"], "the fixture day writes change records"
    snap = _snap(b, use, tmp_path)

    use(a)
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["tables"]["osm_countries"] == {"copied": 1, "kept_here": 0, "not_finished_in_backup": 0}
    assert rep["osm_copied"] == ["ZZZ"] and rep["osm_newer_in_backup"] == []
    assert _objects() == want_objects
    assert _country_row() == want_country, "the row comes with its diff cursor, border and counts"
    assert _records() == want_records
    assert rep["tables"]["osm_objects"]["inserted"] == len(want_objects)
    # The indexes a local cut builds at its end were built here, from the copied rows.
    with store.lane_session("osm") as s:
        basis = country_basis(s.query(OsmCountry).filter_by(alpha3="ZZZ").one())
        assert s.query(OsmSearchIndex).filter_by(alpha3="ZZZ").one().basis_ingest == basis
        assert s.query(OsmViewIndex).filter_by(alpha3="ZZZ").one().basis_ingest == basis

    # Importing the same backup again copies nothing and changes nothing.
    again = lane_merge.merge_lane_file("osm", snap, [None])
    assert again["tables"]["osm_countries"] == {"copied": 0, "kept_here": 1, "not_finished_in_backup": 0}
    assert again["osm_newer_in_backup"] == []
    assert _objects() == want_objects and _country_row() == want_country and _records() == want_records


def test_the_first_daily_update_after_the_import_applies_from_the_copied_cursor(machines, tmp_path):
    a, b, use = machines
    use(b)
    _cut_here(b)
    snap = _snap(b, use, tmp_path)
    use(b)
    T_b = A.update_country("ZZ", T.Mirror(101, {101: T.DAY1}), workdir=b / "w", kill_switch=lambda: False)
    assert T_b.outcome == "applied"
    want = _objects()

    use(a)
    lane_merge.merge_lane_file("osm", snap, [None])
    rep = A.update_country("ZZ", T.Mirror(101, {101: T.DAY1}), workdir=a / "w", kill_switch=lambda: False)
    assert (rep.outcome, rep.from_sequence, rep.to_sequence) == ("applied", T.SEQ0, 101), rep.reason
    assert _objects() == want, "the copied country updates exactly as the machine that cut it does"


def test_a_country_copied_after_an_update_continues_from_that_update(machines, tmp_path):
    a, b, use = machines
    use(b)
    _cut_here(b, day1=True)
    snap = _snap(b, use, tmp_path)
    use(a)
    lane_merge.merge_lane_file("osm", snap, [None])
    rep = A.update_country("ZZ", T.Mirror(101, {101: T.DAY1}), workdir=a / "w", kill_switch=lambda: False)
    assert (rep.outcome, rep.to_sequence) == ("current", 101), "the copied cursor already stands at day 101"


def test_a_country_both_hold_keeps_this_copy_whole_and_a_newer_backup_copy_is_reported(machines, tmp_path):
    a, b, use = machines
    use(b)
    _cut_here(b, day1=True)
    snap = _snap(b, use, tmp_path)

    use(a)
    _cut_here(a)
    mine_objects, mine_country, mine_records = _objects(), _country_row(), _records()
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["tables"]["osm_countries"] == {"copied": 0, "kept_here": 1, "not_finished_in_backup": 0}
    assert rep["osm_newer_in_backup"] == ["ZZZ"], "the backup's copy stands at day 101, this one at the extract"
    assert (_objects(), _country_row(), _records()) == (mine_objects, mine_country, mine_records)


def test_an_older_backup_copy_is_counted_and_not_reported_newer(machines, tmp_path):
    a, b, use = machines
    use(b)
    _cut_here(b)
    snap = _snap(b, use, tmp_path)
    use(a)
    _cut_here(a, day1=True)
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["tables"]["osm_countries"]["kept_here"] == 1 and rep["osm_newer_in_backup"] == []


@pytest.mark.parametrize("status", ["failed", "ingesting"])
def test_a_country_the_backup_never_finished_is_never_copied(machines, tmp_path, status):
    a, b, use = machines
    use(b)
    _cut_here(b)
    snap = _snap(b, use, tmp_path, edit=lambda con: con.execute("UPDATE osm_countries SET status = ?", (status,)))
    use(a)
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["tables"]["osm_countries"] == {"copied": 0, "kept_here": 0, "not_finished_in_backup": 1}
    assert _country_row() is None and _objects() == {}


def _ruin_a_way(con) -> None:
    con.execute("UPDATE osm_objects SET geom = x'05' WHERE id = (SELECT min(id) FROM osm_objects WHERE osm_type = 'w')")


def _ruin_a_kind(con) -> None:
    con.execute("UPDATE osm_objects SET kind = 'weapons' WHERE id = (SELECT max(id) FROM osm_objects)")


def _ruin_the_border(con) -> None:
    con.execute("UPDATE osm_countries SET border_rings = x'0102'")


def _ruin_the_alpha2(con) -> None:
    con.execute("UPDATE osm_countries SET alpha2 = 'FR'")


def _ruin_a_text_column(con) -> None:
    con.execute("UPDATE osm_objects SET t_name = x'00ff' WHERE id = (SELECT min(id) FROM osm_objects)")


def _ruin_the_other_tags(con) -> None:
    con.execute("UPDATE osm_objects SET other_tags = '[1, 2]' WHERE id = (SELECT min(id) FROM osm_objects)")


def _ruin_the_cursor(con) -> None:
    con.execute("UPDATE osm_countries SET diff_sequence = 7")


def _drop_an_object(con) -> None:
    con.execute("DELETE FROM osm_objects WHERE id = (SELECT max(id) FROM osm_objects)")


@pytest.mark.parametrize(
    ("ruin", "reason"),
    [
        (_ruin_a_way, "refused_unreadable"),
        (_ruin_a_kind, "refused_unreadable"),
        (_ruin_the_border, "refused_unreadable"),
        (_ruin_the_alpha2, "refused_unreadable"),
        (_ruin_a_text_column, "refused_unreadable"),
        (_ruin_the_other_tags, "refused_unreadable"),
        (_ruin_the_cursor, "refused_unreadable"),
        (_drop_an_object, "refused_incomplete"),
    ],
)
def test_a_country_that_fails_a_readers_checks_is_refused_and_nothing_of_it_is_kept(machines, tmp_path, ruin, reason):
    a, b, use = machines
    use(b)
    _cut_here(b)
    snap = _snap(b, use, tmp_path, edit=ruin)
    use(a)
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    counts = rep["tables"]["osm_countries"]
    assert counts["copied"] == 0 and counts[reason] == 1, counts
    assert _country_row() is None and _objects() == {} and _records()["feed"] == []


def test_an_object_this_lane_already_holds_under_another_country_refuses_the_copy(machines, tmp_path):
    a, b, use = machines
    use(b)
    _cut_here(b)
    snap = _snap(b, use, tmp_path)
    use(b)
    taken = next(iter(_objects()))
    use(a)
    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            "INSERT INTO osm_objects (osm_type, osm_id, country_alpha3, kind, notable) VALUES (?, ?, 'FRA', 'poi', 0)", taken
        )
        con.commit()
    finally:
        con.close()
    store.dispose_lane("osm")
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["tables"]["osm_countries"]["refused_shares_objects"] == 1
    assert _country_row() is None
    assert list(_objects()) == [taken], "only this machine's own row is there"


def test_a_finished_history_cut_travels_with_its_country(machines, tmp_path):
    a, b, use = machines
    use(b)
    assert ingest.ingest_country(FIXTURE, "ZZ", reader="python").status == "complete"
    assert history.ingest_history(HISTORY, FIXTURE, "ZZ", reader="python").status == "complete"
    want = _records()
    assert want["history"] and want["cuts"] == [("ZZZ", "complete")]
    snap = _snap(b, use, tmp_path)
    use(a)
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["osm_history_copied"] == ["ZZZ"]
    assert _records()["history"] == want["history"] and _records()["cuts"] == want["cuts"]


def test_an_unfinished_history_cut_stays_behind_and_the_country_still_comes(machines, tmp_path):
    a, b, use = machines
    use(b)
    assert ingest.ingest_country(FIXTURE, "ZZ", reader="python").status == "complete"
    assert history.ingest_history(HISTORY, FIXTURE, "ZZ", reader="python").status == "complete"
    snap = _snap(b, use, tmp_path, edit=lambda con: con.execute("UPDATE osm_history_cuts SET status = 'failed'"))
    use(a)
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["tables"]["osm_countries"]["copied"] == 1 and rep["osm_history_copied"] == []
    assert _records()["history"] == [] and _records()["cuts"] == []


def test_a_backup_from_a_build_with_more_tag_columns_waits_for_that_build(machines, tmp_path):
    a, b, use = machines
    use(b)
    _cut_here(b)
    snap = _snap(b, use, tmp_path, edit=lambda con: con.execute("ALTER TABLE osm_objects ADD COLUMN t_future TEXT"))
    use(a)
    rep = lane_merge.merge_lane_file("osm", snap, [None])
    assert rep["tables"]["osm_countries"]["made_by_a_newer_version"] == 1
    assert _country_row() is None


def test_the_import_report_says_when_the_backup_holds_a_newer_copy():
    from src.backup.import_reports import _living_sources_markdown

    lines: list[str] = []
    _living_sources_markdown(lines, {"lanes": [{
        "kind": "osm", "state": "merged", "seconds": 1.0,
        "tables": {"osm_countries": {"copied": 0, "kept_here": 1, "not_finished_in_backup": 0}},
        "osm_newer_in_backup": ["ZZZ"],
    }]})
    text = "\n".join(lines)
    assert "Maps (OpenStreetMap): merged" in text
    assert "newer copy of 1 country" in text and "ZZZ" in text and "kept whole" in text


def test_a_backup_carrying_the_maps_store_credits_openstreetmap_and_the_odbl(tmp_path):
    """Q823 = a: OpenStreetMap's credit and the ODbL line wherever map data leaves the machine,
    and a backup that carries the maps store is such a place. Measured from the folder's own
    manifest, so a backup without the store carries no such line."""
    import json

    from src.backup.export_summary import export_facts

    def keys(members):
        d = tmp_path / f"dest{len(members)}"
        d.mkdir()
        (d / "volumes.json").write_text(json.dumps({"lane_members": members}), encoding="utf-8")
        return {line["key"] for line in export_facts(d)["attribution"]}

    assert "openstreetmap" not in keys([])
    got = keys([{"name": "lanes/osm.db", "kind": "osm"}, {"name": "lanes/wiki.db", "kind": "wiki"}])
    assert {"openstreetmap", "wikipedia"} <= got
    assert "openstreetmap" not in keys([{"name": "../osm.db", "kind": "osm"}]), "a member this build would not have written names nothing"


def test_an_encrypted_maps_store_rides_with_its_virtual_tables_and_merges(machines, tmp_path, monkeypatch):
    """The real path: the store is SQLCipher, and it holds the map's R*Tree and the search's
    full-text tables. The snapshot keeps the encryption, and the import opens it with its key."""
    import shutil

    from src.database.connect import is_encrypted_file

    a, b, use = machines
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", "machine pass", raising=False)
    use(b)
    _cut_here(b, day1=True)
    want_objects, want_country, want_records = _b_state(b, use)
    snap = _snap(b, use, tmp_path)
    assert is_encrypted_file(snap) is True
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "osm.db")
    use(a)
    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/osm.db", "kind": "osm", "sqlcipher": True}], ["machine pass"])
    assert rep["lanes"][0]["state"] == "merged", rep
    assert rep["lanes"][0]["tables"]["osm_countries"]["copied"] == 1
    assert (_objects(), _country_row(), _records()) == (want_objects, want_country, want_records)
