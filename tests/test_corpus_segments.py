"""R826 (row 409) stage 1: the split corpus's registry and id ranges, and the crash rule (condition f).

Every test builds its own shared file with the app's schema and its own segment files in ``tmp_path``; nothing touches the
app's store. Segment files here are plain stdlib SQLite: stage 1 has no segment opener, and the crash rule is about the
order of two commits, which does not depend on the key.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database import segments as sg
from tests._app_engine import app_sqlite_engine


def _shared(tmp_path: Path, articles: int = 0) -> sqlite3.Connection:
    from src.database.models import Base

    path = tmp_path / "open_omniscience.db"
    eng = app_sqlite_engine(path)
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path, isolation_level=None)
    if articles:
        con.execute("INSERT INTO sources (id, name, domain) VALUES (1, 's', 's.test')")
        con.executemany(
            "INSERT INTO articles (id, url, canonical_url, source_id, title, content, hash) VALUES (?, ?, ?, 1, 't', 'c', ?)",
            [
                (i, f"https://s.test/{i}", f"https://s.test/{i}", f"h{i}")
                for i in range(1, articles + 1)
            ],
        )
    return con


def _seg_con(tmp_path: Path, name: str) -> sqlite3.Connection:
    return sqlite3.connect(tmp_path / name, isolation_level=None)


def _identity_reader(tmp_path: Path):
    def read(name: str | None):
        if not name or not (tmp_path / name).exists():
            return None
        c = sqlite3.connect(f"file:{tmp_path / name}?mode=ro", uri=True)
        try:
            return sg.segment_identity(c)
        finally:
            c.close()

    return read


def _snapshot(con: sqlite3.Connection) -> list:
    return [
        con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
        for t in ("corpus_segments", "corpus_id_counter")
    ]


# --- condition g: an existing corpus is untouched -------------------------------------------------------------------


def test_an_empty_registry_is_legacy_segment_0_and_reading_it_writes_nothing(tmp_path):
    con = _shared(tmp_path, articles=5)
    before = _snapshot(con)
    assert sg.registry(con) == [sg.LEGACY_SEGMENT_0]
    assert _snapshot(con) == before == [[], []]


def test_a_store_without_the_tables_is_also_legacy_segment_0(tmp_path):
    con = sqlite3.connect(tmp_path / "old.db", isolation_level=None)
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY)")
    assert sg.registry(con) == [sg.LEGACY_SEGMENT_0]
    with pytest.raises(sg.SegmentError):
        sg.reserve_segment(con, 10)


def test_nothing_in_the_app_calls_the_writing_functions_yet():
    """Stage 1 adds bookkeeping only (R826 g): no module outside this one reserves, commits or opens a segment."""
    root = Path(__file__).resolve().parents[1] / "src"
    callers = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if p.name != "segments.py"
        and any(
            f in p.read_text(encoding="utf-8")
            for f in ("reserve_segment(", "commit_segment(", "mark_open(", "reconcile(")
        )
        and "segments" in p.read_text(encoding="utf-8")
    ]
    assert callers == []


# --- Q3: ranges ------------------------------------------------------------------------------------------------------


def test_the_first_reservation_closes_segment_0_at_what_it_holds_and_starts_above_it(tmp_path):
    con = _shared(tmp_path, articles=7)
    r = sg.reserve_segment(con, 100)
    assert (r.seg_no, r.file_name, r.id_lo, r.id_hi) == (1, "seg-1.db", 8, 107)
    reg = sg.registry(con)
    assert [(s.seg_no, s.file_name, s.state, s.id_lo, s.id_hi) for s in reg] == [
        (0, None, "closed", 1, 7),
        (1, "seg-1.db", "reserved", 8, 107),
    ]
    assert con.execute("SELECT next_id FROM corpus_id_counter").fetchone()[0] == 108
    assert sg.ranges_overlap(reg) == []


def test_ranges_never_overlap_and_the_counter_only_grows(tmp_path):
    con = _shared(tmp_path, articles=3)
    seen = []
    for size in (10, 1, 50, 2):
        r = sg.reserve_segment(con, size)
        seen.append((r.id_lo, r.id_hi))
    assert seen == [(4, 13), (14, 14), (15, 64), (65, 66)]
    assert sg.ranges_overlap(sg.registry(con)) == []


def test_a_reservation_starts_above_articles_the_shared_file_got_since(tmp_path):
    """Belt and braces: whatever holds the highest id (counter, registry, the shared file's articles) wins."""
    con = _shared(tmp_path, articles=3)
    sg.reserve_segment(con, 10)  # 4..13
    con.execute(
        "INSERT INTO articles (id, url, canonical_url, source_id, title, content, hash)"
        " VALUES (500, 'https://s.test/500', 'https://s.test/500', 1, 't', 'c', 'h500')"
    )
    r = sg.reserve_segment(con, 10)
    assert r.id_lo == 501


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "10"])
def test_a_size_that_is_not_a_positive_whole_number_is_refused(tmp_path, bad):
    con = _shared(tmp_path)
    with pytest.raises(sg.SegmentError):
        sg.reserve_segment(con, bad)
    assert _snapshot(con) == [[], []]


def test_segment_names_are_exact():
    assert sg.segment_file_name(1) == "seg-1.db"
    assert sg.SEGMENT_NAME_RE.match("seg-12.db")
    for bad in ("seg-0.db", "seg-01.db", "seg-1.db-wal", "seg-1.db\n", "xseg-1.db", "seg-12345.db"):
        assert not sg.SEGMENT_NAME_RE.match(bad)
    for bad in (0, 10000, True, "1"):
        with pytest.raises(sg.SegmentError):
            sg.segment_file_name(bad)


def test_the_registry_refuses_to_run_inside_a_callers_transaction(tmp_path):
    con = _shared(tmp_path)
    con.execute("BEGIN")
    with pytest.raises(sg.SegmentError):
        sg.reserve_segment(con, 10)
    con.execute("ROLLBACK")


# --- condition f: crash injection between the shared-file commit and the segment commit ------------------------------


class _Crash(BaseException):
    """A kill between two commits: BaseException, so no ``except Exception`` in the code under test swallows it."""


def _create_segment(tmp_path, con, size, crash_at: str | None):
    """The three steps in order, with a simulated kill at ``crash_at``. A kill drops the connections without a commit."""
    r = sg.reserve_segment(con, size)
    if crash_at == "after_reserve":
        raise _Crash
    seg = _seg_con(tmp_path, r.file_name)
    if crash_at == "inside_segment_commit":
        seg.execute("BEGIN IMMEDIATE")
        seg.execute(sg._SEGMENT_META_DDL)
        seg.execute("INSERT INTO segment_meta VALUES (?, ?, ?, 'x')", (r.seg_no, r.id_lo, r.id_hi))
        seg.close()  # closed with the transaction open: SQLite rolls it back, as a kill would
        raise _Crash
    sg.commit_segment(seg, r)
    seg.close()
    if crash_at == "after_segment_commit":
        raise _Crash
    sg.mark_open(con, r)
    return r


@pytest.mark.parametrize(
    ("crash_at", "expected_state"),
    [
        ("after_reserve", "abandoned"),
        ("inside_segment_commit", "abandoned"),
        ("after_segment_commit", "open"),
    ],
)
def test_a_crash_between_the_two_commits_wastes_ids_and_never_reuses_them(
    tmp_path, crash_at, expected_state
):
    con = _shared(tmp_path, articles=2)
    with pytest.raises(_Crash):
        _create_segment(tmp_path, con, 10, crash_at)
    con.close()

    # "Restart": a fresh connection to the shared file, then the boot-time reconcile.
    con = sqlite3.connect(tmp_path / "open_omniscience.db", isolation_level=None)
    crashed = [s for s in sg.registry(con) if s.seg_no == 1][0]
    assert (crashed.state, crashed.id_lo, crashed.id_hi) == ("reserved", 3, 12)
    done = sg.reconcile(con, _identity_reader(tmp_path))
    assert done == (
        {"opened": [1], "abandoned": []}
        if expected_state == "open"
        else {"opened": [], "abandoned": [1]}
    )
    assert [s.state for s in sg.registry(con) if s.seg_no == 1] == [expected_state]

    # The next segment never reuses the crashed range, whatever became of it.
    r2 = _create_segment(tmp_path, con, 10, None)
    assert (r2.seg_no, r2.id_lo, r2.id_hi) == (2, 13, 22)
    reg = sg.registry(con)
    assert sg.ranges_overlap(reg) == []
    assert [s.state for s in reg] == ["closed", expected_state, "open"]


def test_reconcile_abandons_a_file_whose_identity_does_not_match_its_row(tmp_path):
    """A file at the right NAME proves nothing: only the exact number and range recorded by step 2 opens the row."""
    con = _shared(tmp_path)
    r = sg.reserve_segment(con, 10)
    other = sg.Reservation(r.seg_no, r.file_name, r.id_lo, r.id_hi + 1)
    seg = _seg_con(tmp_path, r.file_name)
    sg.commit_segment(seg, other)
    seg.close()
    assert sg.reconcile(con, _identity_reader(tmp_path)) == {"opened": [], "abandoned": [1]}


def test_reconcile_with_nothing_reserved_changes_nothing(tmp_path):
    con = _shared(tmp_path)
    _create_segment(tmp_path, con, 5, None)
    before = _snapshot(con)
    assert sg.reconcile(con, _identity_reader(tmp_path)) == {"opened": [], "abandoned": []}
    assert _snapshot(con) == before


def test_a_segment_file_records_one_identity_and_refuses_a_second(tmp_path):
    con = _shared(tmp_path)
    r = sg.reserve_segment(con, 5)
    seg = _seg_con(tmp_path, r.file_name)
    sg.commit_segment(seg, r)
    with pytest.raises(sg.SegmentError):
        sg.commit_segment(seg, r)
    assert sg.segment_identity(seg) == (r.seg_no, r.id_lo, r.id_hi)


def test_mark_open_refuses_a_row_that_is_not_reserved(tmp_path):
    con = _shared(tmp_path)
    r = _create_segment(tmp_path, con, 5, None)
    with pytest.raises(sg.SegmentError):
        sg.mark_open(con, r)


# --- the backup keeps them per machine -------------------------------------------------------------------------------


def test_a_restore_never_carries_another_machines_registry():
    from src.backup.merge import _MERGE_HANDLED, _MERGE_NOT_CARRIED

    for t in ("corpus_segments", "corpus_id_counter"):
        assert t in _MERGE_NOT_CARRIED and t not in _MERGE_HANDLED


class _CommitFails(sqlite3.Connection):
    """A connection whose COMMIT raises once, as SQLITE_BUSY or an I/O error would."""

    fail_commit = True

    def execute(self, sql, *args):  # type: ignore[override]
        if sql == "COMMIT" and self.fail_commit:
            self.fail_commit = False
            raise sqlite3.OperationalError("database is locked")
        return super().execute(sql, *args)


def test_a_failed_commit_leaves_no_transaction_open_and_writes_nothing(tmp_path):
    _shared(tmp_path).close()
    con = sqlite3.connect(
        tmp_path / "open_omniscience.db", isolation_level=None, factory=_CommitFails
    )
    with pytest.raises(sqlite3.OperationalError):
        sg.reserve_segment(con, 10)
    assert not con.in_transaction
    assert _snapshot(con) == [[], []]
    r = sg.reserve_segment(con, 10)  # the connection is usable again
    assert (r.seg_no, r.id_lo) == (1, 1)
