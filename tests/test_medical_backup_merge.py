"""The medical store in a backup (R746): additive merge, this machine's rows always win.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two "machines" are two data directories. Machine B's ``medical.db`` is snapshotted the way the
export does it and merged into machine A's. Pinned here: a record only the backup holds is added
with its class history; a record both hold keeps A's row whole (a newer one in the backup is
counted, never copied over it); the ids the user named join A's list; A's own reads
(``medical_files``, ``medical_cited``) stay behind; a row that fails a check is skipped and
counted; a second import changes nothing; and a failure leaves the store as it was.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.backup import lane_merge
from src.medical import store as M
from src.medical.lane_models import (
    MedicalCited,
    MedicalClassChange,
    MedicalFile,
    MedicalPaper,
    MedicalWanted,
)
from src.versioned import store

T0 = datetime(2026, 11, 1, tzinfo=UTC)
MEMBER = [{"name": "lanes/medical.db", "kind": "medical"}]


@pytest.fixture
def machines(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")

    def use(which: Path) -> None:
        store.dispose_all()
        monkeypatch.setenv("OO_DATA_DIR", str(which))
        store.create_lane(M.LANE)

    yield a, b, use
    store.dispose_all()


def _paper(pmid: int, version: int = 1, *, cls: str = "journal", file: str = "pubmed25n1300.xml.gz", **kw) -> MedicalPaper:
    values = {
        "title": f"Paper {pmid}",
        "journal": "J Test",
        "pub_date": "2024-03",
        "doi": f"10.9999/p.{pmid}",
        "provenance_class": cls,
        "source_file": file,
        "first_seen_at": T0,
        "last_seen_at": T0,
        "abstract_json": '[["", "An abstract."]]',
    }
    values.update(kw)
    return MedicalPaper(pmid=pmid, version=version, **values)


def _seed_b(b: Path, use, tmp_path: Path) -> Path:
    use(b)
    with store.lane_session(M.LANE) as s:
        s.add(_paper(1, title="B's copy of 1", file="pubmed25n1310.xml.gz"))  # both hold it; B's file is newer
        s.add(_paper(2, cls="retracted", notice_kind=None))  # only B
        s.add(MedicalClassChange(pmid=2, version=1, from_class="journal", to_class="retracted",
                                 source_file="pubmed25n1300.xml.gz", recorded_at=T0))
        s.add(MedicalClassChange(pmid=1, version=1, from_class="preprint", to_class="journal",
                                 source_file="pubmed25n1310.xml.gz", recorded_at=T0))  # belongs to A's row: not copied
        s.add(_paper(3, 2, withdrawn_at=T0, withdrawn_in_file="pubmed25n1301.xml.gz"))  # only B, withdrawn
        s.add(MedicalWanted(id_kind="doi", value="10.9999/named.by.b", added_at=T0))
        s.add(MedicalWanted(id_kind="pmid", value="5", added_at=T0))  # A named it too
        s.add(MedicalFile(name="pubmed25n1310.xml.gz", status="finished", finished_at=T0, started_at=T0))
        s.add(MedicalCited(id_kind="pmid", value="777", seen_at=T0))
        s.commit()
    snap = tmp_path / "snap" / "medical.db"
    entry = lane_merge.snapshot_lane_for_backup(M.LANE, snap)
    assert entry["name"] == "lanes/medical.db"
    store.dispose_lane(M.LANE)
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "medical.db")
    return staging


def _seed_a(a: Path, use) -> None:
    use(a)
    with store.lane_session(M.LANE) as s:
        s.add(_paper(1, title="A's copy of 1"))
        s.add(MedicalWanted(id_kind="pmid", value="5", added_at=T0 + timedelta(days=1)))
        s.add(MedicalFile(name="pubmed25n1300.xml.gz", status="finished", finished_at=T0, started_at=T0))
        s.commit()


def _state() -> dict:
    with store.lane_session(M.LANE) as s:
        out = {m.__tablename__: s.execute(select(func.count()).select_from(m)).scalar_one()
               for m in (MedicalPaper, MedicalClassChange, MedicalWanted, MedicalFile, MedicalCited)}
        out["papers"] = sorted((p.pmid, p.version, p.title, p.provenance_class, p.source_file)
                               for p in s.execute(select(MedicalPaper)).scalars())
        return out


def test_the_merge_adds_what_only_the_backup_holds_and_is_idempotent(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _seed_a(a, use)

    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    (lane,) = rep["lanes"]
    assert lane["state"] == "merged", lane
    assert lane["tables"]["medical_papers"] == {"inserted": 2}
    assert lane["tables"]["medical_class_changes"] == {"inserted": 1}
    assert lane["tables"]["medical_wanted"] == {"inserted": 1}
    assert lane["medical"] == {"papers_refused": 0, "wanted_refused": 0, "papers_backup_newer": 1}

    with store.lane_session(M.LANE) as s:
        papers = {(p.pmid, p.version): p for p in s.execute(select(MedicalPaper)).scalars()}
        assert set(papers) == {(1, 1), (2, 1), (3, 2)}
        # Both hold PMID 1: A's row stays whole, though B's came from a newer file.
        assert papers[(1, 1)].title == "A's copy of 1" and papers[(1, 1)].source_file == "pubmed25n1300.xml.gz"
        assert papers[(2, 1)].provenance_class == "retracted" and papers[(2, 1)].abstract_json == '[["", "An abstract."]]'
        assert papers[(3, 2)].withdrawn_in_file == "pubmed25n1301.xml.gz" and papers[(3, 2)].withdrawn_at is not None
        changes = [(c.pmid, c.to_class) for c in s.execute(select(MedicalClassChange)).scalars()]
        assert changes == [(2, "retracted")], "a class history is copied only with the row it describes"
        wanted = {(w.id_kind, w.value) for w in s.execute(select(MedicalWanted)).scalars()}
        assert wanted == {("pmid", "5"), ("doi", "10.9999/named.by.b")}
        # This machine's own reads stay its own.
        assert [f.name for f in s.execute(select(MedicalFile)).scalars()] == ["pubmed25n1300.xml.gz"]
        assert s.execute(select(func.count()).select_from(MedicalCited)).scalar_one() == 0
        # The surface reads the merged rows like any other.
        out = M.papers_cited_by(s, {9: M.Wanted()} | {7: _wanted_pmids("2")})
    assert [p["pmid"] for p in out["papers"]] == [2] and out["papers"][0]["retracted_seen_at"] is not None

    before = _state()
    again = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert again["lanes"][0]["state"] == "merged"
    assert all(v.get("inserted", 0) == 0 for v in again["lanes"][0]["tables"].values())
    assert _state() == before


def _wanted_pmids(*pmids: str) -> M.Wanted:
    w = M.Wanted()
    for p in pmids:
        w.add("pmid", p)
    return w


def test_rows_that_fail_a_check_are_skipped_and_counted(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    member = staging / "lanes" / "medical.db"
    con = sqlite3.connect(member)
    try:
        con.execute("UPDATE medical_papers SET provenance_class = 'peer-reviewed' WHERE pmid = 2")
        con.execute("UPDATE medical_papers SET source_file = '../../corpus.db' WHERE pmid = 3")
        con.execute("INSERT INTO medical_wanted (id_kind, value, added_at) VALUES ('pmid', '12 OR 1', '2026-11-01 00:00:00.000000')")
        con.execute("INSERT INTO medical_wanted (id_kind, value, added_at) VALUES ('url', 'https://x', '2026-11-01 00:00:00.000000')")
        con.execute("INSERT INTO medical_wanted (id_kind, value, added_at) VALUES ('doi', '10.1/Upper', '2026-11-01 00:00:00.000000')")
        con.commit()
    finally:
        con.close()
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    (lane,) = rep["lanes"]
    assert lane["state"] == "merged", lane
    assert lane["medical"]["papers_refused"] == 2 and lane["medical"]["wanted_refused"] == 3
    assert lane["tables"]["medical_papers"] == {"inserted": 0}
    assert lane["tables"]["medical_class_changes"] == {"inserted": 0}
    with store.lane_session(M.LANE) as s:
        assert {p.pmid for p in s.execute(select(MedicalPaper)).scalars()} == {1}
        assert {w.value for w in s.execute(select(MedicalWanted)).scalars()} == {"5", "10.9999/named.by.b"}


def test_a_future_timestamp_or_a_bad_list_is_never_copied(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    con = sqlite3.connect(staging / "lanes" / "medical.db")
    try:
        con.execute("UPDATE medical_papers SET last_seen_at = '2099-01-01 00:00:00.000000' WHERE pmid = 2")
        con.execute("UPDATE medical_papers SET mesh_json = '{\"not\": \"a list\"}' WHERE pmid = 3")
        con.commit()
    finally:
        con.close()
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["medical"]["papers_refused"] == 2
    assert rep["lanes"][0]["tables"]["medical_papers"] == {"inserted": 0}


def test_a_failure_leaves_the_store_as_it_was(machines, tmp_path, monkeypatch):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    before = _state()

    def boom(conn, out):
        lane_merge._merge_medical(conn, out)
        raise RuntimeError("injected")

    monkeypatch.setitem(lane_merge._STEPS, "medical", (boom,))
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["state"] == "failed"
    assert "injected" not in rep["lanes"][0]["reason"]
    assert _state() == before


def test_a_member_that_is_not_a_medical_store_is_refused(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    con = sqlite3.connect(staging / "lanes" / "medical.db")
    try:
        con.execute("UPDATE lane_meta SET kind = 'wiki'")
        con.commit()
    finally:
        con.close()
    _seed_a(a, use)
    before = _state()
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["state"] == "failed"
    assert _state() == before


def test_a_backup_carrying_the_medical_store_carries_the_pubmed_line():
    from src.backup.attribution import attribution_dicts, lane_signal

    lines = attribution_dicts({lane_signal("medical")})
    assert [x["key"] for x in lines] == ["pubmed"]
    assert "National Library of Medicine" in lines[0]["text"] and lines[0]["because"] == "lane:medical"
    assert attribution_dicts({lane_signal("wiki")})[0]["key"] != "pubmed"
    assert "medical" in lane_merge.MERGEABLE_KINDS


# --- hostile members (the security read of #2169) ------------------------------------------------


def _edit_member(staging: Path, *sql: str, params: tuple = ()) -> None:
    con = sqlite3.connect(staging / "lanes" / "medical.db")
    try:
        for stmt in sql:
            con.execute(stmt, params) if "?" in stmt else con.execute(stmt)
        con.commit()
    finally:
        con.close()


@pytest.mark.parametrize("decl", ["id INTEGER", "id INTEGER PRIMARY KEY DESC"])
def test_rows_are_copied_by_rowid_so_a_shared_or_null_id_never_smuggles_one_in(machines, tmp_path, decl):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    # A tested row and an untested one sharing an id (or holding NULL): only the tested one may land.
    _edit_member(
        staging,
        f"CREATE TABLE w2 ({decl}, id_kind VARCHAR(8) NOT NULL, value VARCHAR(300) NOT NULL, added_at DATETIME NOT NULL)",
        "INSERT INTO w2 SELECT NULL, id_kind, value, added_at FROM medical_wanted",
        "INSERT INTO w2 VALUES (1, 'zzz', 'not an id', '2026-11-01 00:00:00.000000')",
        "DROP TABLE medical_wanted",
        "ALTER TABLE w2 RENAME TO medical_wanted",
        f"CREATE TABLE p2 ({decl}, " + ", ".join(
            f'"{c}"' for c in lane_merge._MED_PAPER_COLS
        ) + ")",
        "INSERT INTO p2 SELECT NULL, " + ", ".join(f'"{c}"' for c in lane_merge._MED_PAPER_COLS) + " FROM medical_papers WHERE pmid = 2",
        "INSERT INTO p2 SELECT 1, " + ", ".join(
            "'BOGUS'" if c == "provenance_class" else f'"{c}"' for c in lane_merge._MED_PAPER_COLS
        ) + " FROM medical_papers WHERE pmid = 2",
        "DROP TABLE medical_papers",
        "ALTER TABLE p2 RENAME TO medical_papers",
    )
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["state"] == "merged", rep
    with store.lane_session(M.LANE) as s:
        assert {(w.id_kind, w.value) for w in s.execute(select(MedicalWanted)).scalars()} == {("pmid", "5"), ("doi", "10.9999/named.by.b")}
        assert {(p.pmid, p.provenance_class) for p in s.execute(select(MedicalPaper)).scalars()} == {(1, "journal"), (2, "retracted")}
        M.user_wanted(s)  # never an id kind this build cannot read


def test_a_without_rowid_member_or_one_shadowing_the_rowid_is_refused(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _edit_member(
        staging,
        "CREATE TABLE w2 (id INTEGER PRIMARY KEY, rowid INTEGER, id_kind VARCHAR(8) NOT NULL, value VARCHAR(300) NOT NULL, added_at DATETIME NOT NULL)",
        "INSERT INTO w2 (id, rowid, id_kind, value, added_at) SELECT id, 1, id_kind, value, added_at FROM medical_wanted",
        "DROP TABLE medical_wanted",
        "ALTER TABLE w2 RENAME TO medical_wanted",
    )
    _seed_a(a, use)
    before = _state()
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["state"] == "failed"
    assert _state() == before


def test_a_file_from_a_year_nlm_has_not_reached_refuses_the_row(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _edit_member(staging, "UPDATE medical_papers SET source_file = 'pubmed99n9999.xml.gz' WHERE pmid = 2")
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["medical"]["papers_refused"] == 1
    with store.lane_session(M.LANE) as s:
        assert {p.pmid for p in s.execute(select(MedicalPaper)).scalars()} == {1, 3}


def test_an_abstract_with_a_lone_surrogate_refuses_its_row_not_the_lane(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    from src.utils.compression import CompressionAlgorithm, CompressionConfig, Compressor

    blob = Compressor().compress(b'[["", "\\ud800"]]', algorithm=CompressionAlgorithm.ZLIB,
                                 config=CompressionConfig(algorithm=CompressionAlgorithm.ZLIB, level=6))
    con = sqlite3.connect(staging / "lanes" / "medical.db")
    try:
        con.execute("UPDATE medical_papers SET abstract_json = ? WHERE pmid = 2", (blob,))
        con.commit()
    finally:
        con.close()
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["state"] == "merged"
    assert rep["lanes"][0]["medical"]["papers_refused"] == 1
    assert rep["lanes"][0]["tables"]["medical_papers"] == {"inserted": 1}


def test_the_import_report_names_the_store_and_says_what_it_kept_and_refused():
    from src.backup.import_reports import _living_sources_markdown

    lines: list[str] = []
    _living_sources_markdown(lines, {"lanes": [{
        "kind": "medical", "state": "merged", "seconds": 0.1, "tables": {"medical_papers": {"inserted": 2}},
        "medical": {"papers_refused": 3, "wanted_refused": 0, "papers_backup_newer": 1},
    }]})
    text = "\n".join(lines)
    assert "Medical papers (PubMed): merged" in text and "Unknown store" not in text
    assert "newer PubMed file of 1 papers" in text and "3 papers in the backup were not copied" in text
    assert "named identifiers" not in text


def test_an_abstract_is_rebuilt_here_and_a_bad_or_oversized_one_refuses_its_row(machines, tmp_path):
    import bz2
    import hashlib
    import struct

    from src.utils.compression import COMPRESSION_MAGIC

    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    raw = b"x" * (5 * 1024 * 1024)
    bomb = struct.pack("<4sBBHQ32s", COMPRESSION_MAGIC, 3, 9, 0, len(raw), hashlib.sha256(raw).digest()) + bz2.compress(raw)
    _edit_member(staging, "UPDATE medical_papers SET abstract_json = X'00112233' WHERE pmid = 2")
    con = sqlite3.connect(staging / "lanes" / "medical.db")
    try:
        con.execute("UPDATE medical_papers SET abstract_json = ? WHERE pmid = 3", (bomb,))
        con.commit()
    finally:
        con.close()
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["medical"]["papers_refused"] == 2
    assert rep["lanes"][0]["tables"]["medical_papers"] == {"inserted": 0}


def test_a_copied_abstract_reads_back_as_the_same_sections(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    with store.lane_session(M.LANE) as s:
        p = s.execute(select(MedicalPaper).where(MedicalPaper.pmid == 2)).scalar_one()
        assert p.abstract_json == '[["", "An abstract."]]'


def test_list_columns_must_hold_what_the_parser_writes(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _edit_member(
        staging,
        "UPDATE medical_papers SET status_links_json = '[[[1]]]' WHERE pmid = 2",
        "UPDATE medical_papers SET keywords_json = '[[\"nested\"]]' WHERE pmid = 3",
    )
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["medical"]["papers_refused"] == 2


def test_a_well_formed_status_link_is_copied(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _edit_member(staging, "UPDATE medical_papers SET status_links_json = '[[\"RetractionIn\", 90000009, \"J Test 2025\"]]' WHERE pmid = 2")
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["medical"]["papers_refused"] == 0
    with store.lane_session(M.LANE) as s:
        out = M.papers_cited_by(s, {7: _wanted_pmids("2")})
    assert out["papers"][0]["pmid"] == 2


def test_a_named_doi_outside_printable_ascii_is_refused(machines, tmp_path):
    a, b, use = machines
    staging = _seed_b(b, use, tmp_path)
    _edit_member(
        staging,
        "INSERT INTO medical_wanted (id_kind, value, added_at) VALUES ('doi', '10.1/é', '2026-11-01 00:00:00.000000')",
        "INSERT INTO medical_wanted (id_kind, value, added_at) VALUES ('doi', '10.1/a' || char(11) || 'b', '2026-11-01 00:00:00.000000')",
    )
    _seed_a(a, use)
    rep = lane_merge.merge_staged_lanes(staging, MEMBER, [None])
    assert rep["lanes"][0]["medical"]["wanted_refused"] == 2
