"""R826 stage 3a (row 409): the segment writer core. The open segment is opened read-write through the app's factory and
checked as the reader checks it; ids come from its range in the same transaction as the rows; a full segment rolls over;
the generation is raised in the file first and the registry second, so a crash between the two is recovered and only an
older copy of a file is refused; a hot journal a crash left is rolled back before any read."""
from __future__ import annotations

import ast
import inspect
import json
import os
import re
import shutil
import sqlite3
import textwrap
from pathlib import Path

import pytest

from src.database import at_rest_state, segment_open, segment_write
from src.database import segments as sg
from src.database.connect import have_driver
from src.database.segments import Segment, SegmentError
from tests._app_engine import app_sqlite_engine

_PW = "r826-stage-3a-segment-writer-test-passphrase"
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
posix_only = pytest.mark.skipif(os.name != "posix", reason="links and inode checks (POSIX)")


@pytest.fixture()
def data(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "OOS data"
    d.mkdir()
    (d / at_rest_state.RECORD_NAME).write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    import src.api.unlock as unlock

    monkeypatch.setattr(unlock, "main_db_path", lambda **_: d / "open_omniscience.db")
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", True)
    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: False)
    return d


@pytest.fixture()
def shared(data):
    from src.database.models import Base

    path = data / "open_omniscience.db"
    eng = app_sqlite_engine(path)
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    yield con
    con.close()


@pytest.fixture(autouse=True)
def _no_writer_left():
    yield
    assert not segment_write._WRITER_LOCK.locked(), "every test closes its writer"


def _row(con, seg_no: int) -> Segment:
    return next(s for s in sg.registry(con) if s.seg_no == seg_no)


def _file_counters(data: Path, seg_no: int) -> tuple[int, int]:
    con = sqlite3.connect(f"file:{data / 'corpus' / f'seg-{seg_no}.db'}?mode=ro", uri=True)
    try:
        got = sg.segment_counters(con)
    finally:
        con.close()
    assert got is not None
    return got


# --- the switch ---------------------------------------------------------------------------------------------------------


def test_the_writer_refuses_while_the_switch_is_off(data, shared, monkeypatch):
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", False)
    with pytest.raises(SegmentError):
        segment_write.open_writer(shared)
    assert not (data / "corpus").exists()
    assert sg.registry(shared) == [sg.LEGACY_SEGMENT_0], "nothing reserved either"


@pytest.mark.parametrize(
    "fn",
    [segment_write.open_writer, segment_write.rollover, segment_write.SegmentWriter.open, segment_write.SegmentWriter.transaction],
)
def test_every_writing_entry_asks_the_switch_first(fn):
    """The first call each entry makes, in source order, is ``require_writes()`` (a thread-id read and the refusal of a
    nested call come before it in ``transaction``; neither touches a file)."""
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    calls = sorted((c for c in ast.walk(node) if isinstance(c, ast.Call)), key=lambda c: (c.lineno, c.col_offset))
    names = [ast.unparse(c.func) for c in calls]
    names = [n for n in names if n not in ("threading.get_ident", "WriterBusy")]
    assert names[0] == "require_writes"


def test_nothing_in_src_imports_the_writer():
    root = Path(__file__).resolve().parents[1] / "src"
    imports = re.compile(r"^\s*(?:from\s+[\w.]*segment_write\b|import\s+[\w.]*segment_write\b|from\s+[\w.]+\s+import\s+.*\bsegment_write\b)", re.M)
    hits = [
        str(p)
        for p in root.rglob("*.py")
        if p.name != "segment_write.py" and imports.search(p.read_text(encoding="utf-8", errors="replace"))
    ]
    assert hits == []


# --- ids, rollover ------------------------------------------------------------------------------------------------------


@posix_only
def test_the_first_writer_makes_segment_1_and_ids_come_from_its_range(data, shared):
    w = segment_write.open_writer(shared)
    try:
        assert w.seg.seg_no == 1 and _row(shared, 1).state == "open" and _row(shared, 0).state == "closed"
        with w.transaction() as t:
            ids = t.allocate(3)
        assert list(ids) == [w.seg.id_lo, w.seg.id_lo + 1, w.seg.id_lo + 2]
        with w.transaction() as t:
            assert t.allocate(1)[0] == w.seg.id_lo + 3
        assert w._con.execute("PRAGMA temp_store").fetchone()[0] == 2, "R825: memory temp only"
    finally:
        w.close()


@posix_only
def test_a_rolled_back_transaction_gives_its_ids_and_its_generation_back(data, shared):
    w = segment_write.open_writer(shared)
    try:
        before = _file_counters(data, 1)
        with pytest.raises(RuntimeError), w.transaction() as t:
            t.allocate(10)
            raise RuntimeError("the caller's write failed")
        assert _file_counters(data, 1) == before
        assert _row(shared, 1).generation == before[0]
        with w.transaction() as t:
            assert t.allocate(1)[0] == w.seg.id_lo
    finally:
        w.close()


@posix_only
def test_a_full_segment_rolls_over_to_the_next_and_ids_never_overlap(data, shared, monkeypatch):
    monkeypatch.setattr(sg, "DEFAULT_SEGMENT_SIZE", 5)
    w = segment_write.open_writer(shared)
    try:
        with w.transaction() as t:
            first = t.allocate(5)
        with pytest.raises(segment_write.SegmentFull), w.transaction() as t:
            t.allocate(1)
        w = segment_write.rollover(w)
        assert w.seg.seg_no == 2 and _row(shared, 1).state == "closed" and _row(shared, 2).state == "open"
        with w.transaction() as t:
            nxt = t.allocate(5)
        assert nxt[0] > first[-1]
        assert sg.ranges_overlap(sg.registry(shared)) == []
    finally:
        w.close()


def test_the_size_doubles_and_the_file_count_is_capped():
    def segs(n: int, state: str = "closed") -> list[Segment]:
        return [Segment(0, None, "closed", 1, 0)] + [Segment(i, f"seg-{i}.db", state, i * 10, i * 10 + 9) for i in range(1, n + 1)]

    assert sg.next_segment_size(segs(0)) == sg.DEFAULT_SEGMENT_SIZE
    assert sg.next_segment_size(segs(15)) == sg.DEFAULT_SEGMENT_SIZE
    assert sg.next_segment_size(segs(16)) == 2 * sg.DEFAULT_SEGMENT_SIZE
    assert sg.next_segment_size(segs(63)) == 8 * sg.DEFAULT_SEGMENT_SIZE
    with pytest.raises(SegmentError):
        sg.next_segment_size(segs(64))
    assert sg.next_segment_size(segs(64, "abandoned")) == sg.DEFAULT_SEGMENT_SIZE, "an abandoned reservation made no file"


@posix_only
def test_one_writer_per_process(data, shared):
    w = segment_write.open_writer(shared)
    try:
        with pytest.raises(SegmentError):
            segment_write.SegmentWriter.open(shared, _row(shared, 1))
    finally:
        w.close()
    segment_write.open_writer(shared).close()


@posix_only
def test_two_open_rows_keep_only_the_newest_and_a_reserved_row_is_settled(data, shared, monkeypatch):
    monkeypatch.setattr(sg, "DEFAULT_SEGMENT_SIZE", 5)
    segment_write.open_writer(shared).close()  # seg 1, open
    r2 = sg.reserve_segment(shared, 5)
    segment_open.create_segment(r2)
    sg.mark_open(shared, r2)  # a crash left two open rows
    r3 = sg.reserve_segment(shared, 5)  # and a reservation whose file was never made
    w = segment_write.open_writer(shared)
    try:
        assert w.seg.seg_no == 2
        assert [(s.seg_no, s.state) for s in sg.registry(shared)] == [(0, "closed"), (1, "closed"), (2, "open"), (r3.seg_no, "abandoned")]
    finally:
        w.close()


# --- the generation number ----------------------------------------------------------------------------------------------


@posix_only
def test_each_commit_raises_the_generation_in_the_file_then_the_registry(data, shared):
    w = segment_write.open_writer(shared)
    try:
        g0 = _file_counters(data, 1)[0]
        with w.transaction() as t:
            t.allocate(1)
        assert _file_counters(data, 1)[0] == g0 + 1 == _row(shared, 1).generation
    finally:
        w.close()


@posix_only
def test_a_crash_between_the_file_and_the_registry_is_recovered_never_refused(data, shared, monkeypatch):
    """The file is raised first: a crash before the registry's raise leaves the file NEWER. The reader opens it and the
    next writer catches the registry up."""
    w = segment_write.open_writer(shared)
    with w.transaction() as t:
        t.allocate(1)
    real = segment_write.record_generation

    def crash(*a, **k):
        raise OSError("the process died here")

    monkeypatch.setattr(segment_write, "record_generation", crash)
    with w.transaction() as t:  # committed: the registry's failure is kept owed, never raised (a caller would write again)
        t.allocate(1)
    w.close()  # the owed raise fails again here: the process "died" with the registry behind
    monkeypatch.setattr(segment_write, "record_generation", real)
    file_gen, reg_gen = _file_counters(data, 1)[0], _row(shared, 1).generation
    assert reg_gen is not None and file_gen == reg_gen + 1
    segment_open.open_segment(_row(shared, 1)).close()  # the reader accepts a newer file
    w = segment_write.open_writer(shared)
    try:
        assert _row(shared, 1).generation == file_gen, "the writer caught the registry up"
        with w.transaction() as t:
            t.allocate(1)
        assert _row(shared, 1).generation == file_gen + 1 == _file_counters(data, 1)[0]
    finally:
        w.close()


@posix_only
def test_an_older_copy_put_back_in_the_segments_place_is_refused(data, shared, tmp_path):
    w = segment_write.open_writer(shared)
    p = data / "corpus" / "seg-1.db"
    try:
        with w.transaction() as t:
            t.allocate(1)
        old = tmp_path / "older-copy.db"
        shutil.copyfile(p, old)
        with w.transaction() as t:
            t.allocate(1)
    finally:
        w.close()
    os.replace(old, p)  # an earlier copy (say, from a backup) put back
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_row(shared, 1))
    assert e.value.reason == "older_copy"
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_write.SegmentWriter.open(shared, _row(shared, 1))
    assert e.value.reason == "older_copy"


@sqlcipher_only
@posix_only
def test_the_encrypted_writer_raises_the_generation_and_refuses_a_wrong_key(data, shared, monkeypatch):
    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: True)
    w = segment_write.open_writer(shared, key=_PW)
    try:
        with w.transaction() as t:
            t.allocate(2)
        assert b"SQLite format 3" not in (data / "corpus" / "seg-1.db").read_bytes()[:16]
    finally:
        w.close()
    assert segment_open.open_segment(_row(shared, 1), key=_PW).execute("SELECT generation FROM segment_meta").fetchone()[0] == _row(shared, 1).generation
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_write.SegmentWriter.open(shared, _row(shared, 1), key=_PW + "-wrong")
    assert e.value.reason == "wrong_key"


# --- a hot journal ------------------------------------------------------------------------------------------------------


def _crash_mid_write(p: Path, tmp_path: Path) -> None:
    """Leave ``p`` exactly as a crash inside a write transaction does: the file and a hot journal beside it."""
    con = sqlite3.connect(p, isolation_level=None)
    con.execute("PRAGMA cache_size = 1")
    con.execute("BEGIN IMMEDIATE")
    # Large enough to spill out of a one-page cache: the journal is synced (its header made valid, so it is HOT) and the
    # file's pages are overwritten before the "crash", which is the case a rollback must undo.
    con.execute("UPDATE segment_meta SET next_id = next_id + 1000, created_at = hex(randomblob(200000))")
    db_copy, j_copy = tmp_path / "crash.db", tmp_path / "crash.db-journal"
    shutil.copyfile(p, db_copy)
    shutil.copyfile(f"{p}-journal", j_copy)
    con.execute("ROLLBACK")
    con.close()
    os.replace(db_copy, p)
    os.replace(j_copy, f"{p}-journal")
    assert os.path.getsize(f"{p}-journal") > 0


@posix_only
def test_a_hot_journal_is_rolled_back_before_the_reader_reads(data, shared, tmp_path):
    w = segment_write.open_writer(shared)
    w.close()
    p = data / "corpus" / "seg-1.db"
    next_id = _file_counters(data, 1)[1]
    _crash_mid_write(p, tmp_path)
    with pytest.raises(sqlite3.OperationalError):  # what a read-only open alone meets: SQLITE_READONLY_ROLLBACK
        sqlite3.connect(f"file:{p}?mode=ro", uri=True).execute("SELECT * FROM segment_meta").fetchall()
    con = segment_open.open_segment(_row(shared, 1))
    try:
        assert sg.segment_counters(con)[1] == next_id, "the committed state, not the crashed write"
    finally:
        con.close()
    assert not Path(f"{p}-journal").exists()


@posix_only
def test_the_writer_rolls_a_hot_journal_back_itself(data, shared, tmp_path):
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    next_id = _file_counters(data, 1)[1]
    _crash_mid_write(p, tmp_path)
    w = segment_write.open_writer(shared)
    try:
        with w.transaction() as t:
            assert t.allocate(1)[0] == next_id
    finally:
        w.close()


@posix_only
def test_a_linked_journal_is_never_rolled_into_the_segment(data, shared, tmp_path):
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    other = tmp_path / "other-journal"
    other.write_bytes(b"j" * 4096)
    os.link(other, f"{p}-journal")
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_row(shared, 1))
    assert e.value.reason == "not_a_segment_file"
    assert other.read_bytes() == b"j" * 4096


# --- stage 4a: a journal is rolled back only into a file confirmed as the segment ------------------------------------------


def _foreign_with_hot_journal(p: Path, tmp_path: Path) -> None:
    """Another program's SQLite database, crashed mid-write, put at the segment's name with its own hot journal."""
    other = tmp_path / "foreign.db"
    con = sqlite3.connect(other, isolation_level=None)
    con.execute("CREATE TABLE notes (body TEXT)")
    con.execute("INSERT INTO notes VALUES ('kept')")
    con.close()
    os.replace(other, p)
    con = sqlite3.connect(p, isolation_level=None)
    con.execute("PRAGMA cache_size = 1")
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE notes SET body = hex(randomblob(200000))")
    db_copy, j_copy = tmp_path / "f.db", tmp_path / "f.db-journal"
    shutil.copyfile(p, db_copy)
    shutil.copyfile(f"{p}-journal", j_copy)
    con.execute("ROLLBACK")
    con.close()
    os.replace(db_copy, p)
    os.replace(j_copy, f"{p}-journal")


def _bytes_beside(p: Path) -> dict[str, bytes]:
    return {x.name: x.read_bytes() for x in sorted(p.parent.iterdir())}


@posix_only
def test_a_foreign_database_with_a_hot_journal_at_the_name_stays_byte_identical(data, shared, tmp_path):
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    _foreign_with_hot_journal(p, tmp_path)
    before = _bytes_beside(p)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_row(shared, 1))
    assert e.value.reason == "schema"
    with pytest.raises(segment_open.SegmentUnavailable):
        segment_write.SegmentWriter.open(shared, _row(shared, 1))
    assert _bytes_beside(p) == before, "neither the file nor its journal was written, and nothing was made beside them"
    assert sqlite3.connect(p).execute("SELECT body FROM notes").fetchall() == [("kept",)], "its own journal, rolled back by its own program"


@posix_only
def test_another_segments_file_with_a_hot_journal_is_never_rolled_back_under_this_name(data, shared, tmp_path):
    segment_write.open_writer(shared).close()
    other = sg.reserve_segment(shared, 10)
    segment_open.create_segment(other)
    p, q = data / "corpus" / "seg-1.db", data / "corpus" / other.file_name
    os.replace(q, p)  # the right schema, another identity
    _crash_mid_write(p, tmp_path)
    before = _bytes_beside(p)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_row(shared, 1))
    assert e.value.reason == "identity"
    assert _bytes_beside(p) == before


@posix_only
def test_an_older_copy_with_a_hot_journal_is_never_rolled_back(data, shared, tmp_path):
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    old = tmp_path / "old.db"
    shutil.copyfile(p, old)
    w = segment_write.open_writer(shared)
    with w.transaction() as t:
        t.allocate(1)
    w.close()
    assert _row(shared, 1).generation > 1
    os.replace(old, p)
    _crash_mid_write(p, tmp_path)
    before = _bytes_beside(p)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_row(shared, 1))
    assert e.value.reason == "older_copy"
    assert _bytes_beside(p) == before


@posix_only
def test_the_writer_refuses_a_journal_its_read_only_open_did_not_confirm(data, shared, monkeypatch):
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    real = segment_open.open_segment

    def then_a_journal(seg, *, key=None):
        con = real(seg, key=key)
        Path(f"{p}-journal").write_bytes(b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7" + b"j" * 4088)  # appears after the confirmation
        return con

    monkeypatch.setattr(segment_open, "open_segment", then_a_journal)
    before = _bytes_beside(p)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_write.SegmentWriter.open(shared, _row(shared, 1))
    assert e.value.reason == "unreadable"
    after = _bytes_beside(p)
    assert after.pop("seg-1.db-journal").startswith(b"\xd9\xd5") and after == before


@posix_only
def test_a_live_writers_journal_is_never_taken_for_a_crash(data, shared):
    """A journal beside the file while another connection is inside a write transaction (it holds the lock): the reader
    reads the last committed state, and neither the file nor the journal is touched. Only SQLite's own hot-journal
    refusal leads to a rollback (security read 2 on stage 4a)."""
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    next_id = _file_counters(data, 1)[1]
    live = sqlite3.connect(p, isolation_level=None)
    try:
        live.execute("BEGIN IMMEDIATE")
        live.execute("UPDATE segment_meta SET next_id = next_id + 1000")
        assert Path(f"{p}-journal").stat().st_size > 0
        file_before, journal_before = p.read_bytes(), Path(f"{p}-journal").read_bytes()
        con = segment_open.open_segment(_row(shared, 1))
        try:
            assert sg.segment_counters(con)[1] == next_id, "the committed state"
        finally:
            con.close()
        assert p.read_bytes() == file_before and Path(f"{p}-journal").read_bytes() == journal_before
        live.execute("COMMIT")
    finally:
        live.close()
    assert _file_counters(data, 1)[1] == next_id + 1000, "the live writer's transaction went through"


@sqlcipher_only
@posix_only
def test_an_encrypted_segments_hot_journal_is_confirmed_and_rolled_back(data, shared, monkeypatch, tmp_path):
    """sqlcipher3 names the refusal by its primary code only (SQLITE_READONLY): the encrypted path still finds the hot
    journal, confirms the file read-only and rolls it back."""
    from src.database.connect import connect

    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: True)
    segment_write.open_writer(shared, key=_PW).close()
    p = data / "corpus" / "seg-1.db"
    first = segment_open.open_segment(_row(shared, 1), key=_PW)
    try:
        next_id = sg.segment_counters(first)[1]
    finally:
        first.close()
    con = connect(p, key=_PW, cipher_page_size=segment_open.SEGMENT_PAGE_SIZE)
    con.isolation_level = None
    con.execute("PRAGMA cache_size = 1")
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE segment_meta SET next_id = next_id + 1000, created_at = hex(randomblob(200000))")
    db_copy, j_copy = tmp_path / "crash.db", tmp_path / "crash.db-journal"
    shutil.copyfile(p, db_copy)
    shutil.copyfile(f"{p}-journal", j_copy)
    con.execute("ROLLBACK")
    con.close()
    os.replace(db_copy, p)
    os.replace(j_copy, f"{p}-journal")
    confirmed = []
    real = segment_open._confirm_beside_journal
    monkeypatch.setattr(segment_open, "_confirm_beside_journal", lambda *a: (confirmed.append(1), real(*a)))
    got = segment_open.open_segment(_row(shared, 1), key=_PW)
    try:
        assert sg.segment_counters(got)[1] == next_id, "the committed state, not the crashed write"
    finally:
        got.close()
    assert confirmed == [1] and not Path(f"{p}-journal").exists()


def test_a_wrong_passphrase_beside_a_hot_journal_never_rolls_anything_back(data, shared, monkeypatch, tmp_path):
    """SQLite refuses a hot journal before it decrypts page 1, so a wrong key is first taken for a crash. The read-only
    confirmation is what stops it: the reason is wrong_key, no rollback runs and every file stays byte-identical."""
    from src.database.connect import connect

    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: True)
    segment_write.open_writer(shared, key=_PW).close()
    p = data / "corpus" / "seg-1.db"
    con = connect(p, key=_PW, cipher_page_size=segment_open.SEGMENT_PAGE_SIZE)
    con.isolation_level = None
    con.execute("PRAGMA cache_size = 1")
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE segment_meta SET next_id = next_id + 1000, created_at = hex(randomblob(200000))")
    db_copy, j_copy = tmp_path / "crash.db", tmp_path / "crash.db-journal"
    shutil.copyfile(p, db_copy)
    shutil.copyfile(f"{p}-journal", j_copy)
    con.execute("ROLLBACK")
    con.close()
    os.replace(db_copy, p)
    os.replace(j_copy, f"{p}-journal")
    before = {x.name: x.read_bytes() for x in sorted(p.parent.iterdir())}
    confirmed, rolled = [], []
    real_confirm, real_roll = segment_open._confirm_beside_journal, segment_open._roll_back_journal
    monkeypatch.setattr(segment_open, "_confirm_beside_journal", lambda *a: (confirmed.append(1), real_confirm(*a))[1])
    monkeypatch.setattr(segment_open, "_roll_back_journal", lambda *a: (rolled.append(1), real_roll(*a))[1])
    with pytest.raises(segment_open.SegmentUnavailable) as got:
        segment_open.open_segment(_row(shared, 1), key="not-the-passphrase")
    assert got.value.reason == "wrong_key"
    assert confirmed == [1] and rolled == []
    assert {x.name: x.read_bytes() for x in sorted(p.parent.iterdir())} == before


def test_an_immutable_open_is_only_ever_read_only(tmp_path):
    from src.database.connect import connect

    p = tmp_path / "x.db"
    sqlite3.connect(p).close()
    with pytest.raises(ValueError):
        connect(p, immutable=True)


# --- the registry column on a store made before it ----------------------------------------------------------------------


def test_a_registry_made_before_the_generation_column_reads_and_heals(tmp_path):
    """Stage 1 stores have ``corpus_segments`` without ``generation``: the registry reads it as "none recorded", and the
    boot self-heal adds the column without touching a row (the live store is never alembic-migrated)."""
    from src.database.maintenance import ensure_corpus_segment_generation_column

    path = tmp_path / "stage1.db"
    con = sqlite3.connect(path, isolation_level=None)
    con.execute(
        "CREATE TABLE corpus_segments (seg_no INTEGER PRIMARY KEY, file_name VARCHAR(32) UNIQUE, state VARCHAR(16) NOT NULL,"
        " id_lo INTEGER NOT NULL, id_hi INTEGER, created_at DATETIME, state_at DATETIME)"
    )
    con.execute("CREATE TABLE corpus_id_counter (id INTEGER PRIMARY KEY, next_id INTEGER NOT NULL)")
    con.execute("INSERT INTO corpus_segments VALUES (0, NULL, 'closed', 1, 9, '', '')")
    assert [s.generation for s in sg.registry(con)] == [None]
    eng = app_sqlite_engine(path)
    try:
        assert ensure_corpus_segment_generation_column(eng) == ["generation"]
        assert ensure_corpus_segment_generation_column(eng) == []
    finally:
        eng.dispose()
    assert con.execute("SELECT seg_no, state, id_hi, generation FROM corpus_segments").fetchall() == [(0, "closed", 9, None)]
    sg.record_generation(con, 0, 3)
    sg.record_generation(con, 0, 2)  # never lowered
    assert sg.registry(con)[0].generation == 3
    con.close()


# --- the two security reads of stage 3a (2026-11-25) --------------------------------------------------------------------


@posix_only
def test_with_the_switch_off_a_hot_journal_is_never_rolled_back(data, shared, tmp_path, monkeypatch):
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    _crash_mid_write(p, tmp_path)
    before = (p.read_bytes(), Path(f"{p}-journal").read_bytes())
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", False)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_row(shared, 1))
    assert e.value.reason == "unreadable"
    assert (p.read_bytes(), Path(f"{p}-journal").read_bytes()) == before, "this build writes no segment"


@posix_only
@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_no_read_write_open_beside_a_write_ahead_log(data, shared, tmp_path, suffix):
    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    Path(f"{p}{suffix}").write_bytes(b"")
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_write.SegmentWriter.open(shared, _row(shared, 1))
    assert e.value.reason == "not_a_segment_file"
    Path(f"{p}{suffix}").unlink()
    _crash_mid_write(p, tmp_path)
    Path(f"{p}{suffix}").write_bytes(b"")
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_row(shared, 1))
    assert e.value.reason == "not_a_segment_file"
    assert Path(f"{p}-journal").exists(), "the journal was not rolled into the file"


@posix_only
def test_a_registry_that_cannot_be_raised_after_a_commit_is_owed_never_raised(data, shared, monkeypatch):
    w = segment_write.open_writer(shared)
    try:
        real = segment_write.record_generation
        monkeypatch.setattr(segment_write, "record_generation", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("busy")))
        with w.transaction() as t:
            ids = t.allocate(1)
        assert ids[0] == w.seg.id_lo, "the commit stood and the caller saw no error"
        assert _file_counters(data, 1)[0] == _row(shared, 1).generation + 1
        monkeypatch.setattr(segment_write, "record_generation", real)
        with w.transaction() as t:
            t.allocate(1)
        assert _file_counters(data, 1)[0] == _row(shared, 1).generation, "paid at the next commit"
    finally:
        w.close()


@posix_only
def test_a_transaction_sqlite_ended_early_commits_nothing_more(data, shared):
    w = segment_write.open_writer(shared)
    try:
        before = _file_counters(data, 1)
        with pytest.raises(SegmentError), w.transaction() as t:
            t.con.execute("ROLLBACK")  # what SQLite does by itself on SQLITE_FULL or an I/O error
            t.allocate(5)
        assert _file_counters(data, 1) == before, "no statement ran in autocommit"
        with pytest.raises(SegmentError), w.transaction() as t:
            t.con.execute("ROLLBACK")
        assert _file_counters(data, 1) == before
    finally:
        w.close()


@posix_only
def test_a_nested_call_refuses_instead_of_hanging(data, shared):
    w = segment_write.open_writer(shared)
    try:
        with w.transaction():
            with pytest.raises(segment_write.WriterBusy), w.transaction():
                pass
            with pytest.raises(segment_write.WriterBusy):
                segment_write.rollover(w)
            with pytest.raises(segment_write.WriterBusy):
                w.close()
    finally:
        w.close()


@posix_only
def test_a_second_writer_never_settles_the_registry_under_a_live_one(data, shared):
    w = segment_write.open_writer(shared)
    try:
        before = sg.registry(shared)
        with pytest.raises(segment_write.WriterBusy):
            segment_write.open_writer(shared)
        assert sg.registry(shared) == before
    finally:
        w.close()


@posix_only
def test_a_create_that_fails_after_the_record_named_it_forgets_it(data, shared, monkeypatch):
    """The record names the file, then the read-back's close fails: the file goes, and so does its record entry."""
    forgot: list[str] = []
    monkeypatch.setattr(at_rest_state, "forget_segment", lambda path, *a, **k: forgot.append(Path(path).name) or True)
    monkeypatch.setattr(at_rest_state, "record_segment", lambda *a, **k: True)
    real_open = segment_open.open_segment

    class _Back:
        def __init__(self, con):
            self._con = con

        def close(self):
            self._con.close()
            raise OSError("the read-back did not close cleanly")

    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: True)
    if not have_driver():
        pytest.skip("sqlcipher3 not installed")
    monkeypatch.setattr(segment_open, "open_segment", lambda seg, key=None: _Back(real_open(seg, key=key)))
    with pytest.raises(OSError):
        segment_open.create_segment(sg.Reservation(1, "seg-1.db", 10, 19), key=_PW)
    assert forgot == ["seg-1.db"] and list((data / "corpus").iterdir()) == []


# --- R826 ordering (coordinator, 2026-11-25): with the switch off, nothing makes a file under corpus/ ----------------------


def test_with_the_switch_off_no_path_makes_anything_under_corpus(data, shared, monkeypatch):
    """Every entry that can reach a segment file, driven with the switch off over a registry that names segments: the
    corpus folder is never created. (The erase sweep of corpus/ is on main since b001b6ffa, #2393; this holds anyway.)"""
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", False)
    shared.execute(
        "INSERT INTO corpus_segments (seg_no, file_name, state, id_lo, id_hi) VALUES (0, NULL, 'closed', 1, 0),"
        " (1, 'seg-1.db', 'closed', 1, 9), (2, 'seg-2.db', 'open', 10, 19), (3, 'seg-3.db', 'reserved', 20, 29)"
    )
    sset = segment_open.start_background_open(lambda: sqlite3.connect(data / "open_omniscience.db", check_same_thread=False))
    assert sset is not None
    sset._done.wait(30)
    assert {u["reason"] for u in sset.status()["unavailable"]} == {"missing"}
    segment_open.close_all()
    for seg in sg.registry(shared):
        if seg.file_name:
            with pytest.raises(segment_open.SegmentUnavailable):
                segment_open.open_segment(seg)
    for call in (
        lambda: segment_write.open_writer(shared),
        lambda: segment_write.SegmentWriter.open(shared, _row(shared, 2)),
        lambda: segment_open.create_segment(sg.Reservation(4, "seg-4.db", 30, 39)),
    ):
        with pytest.raises(SegmentError):
            call()
    assert not (data / "corpus").exists()
