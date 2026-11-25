"""R826 stage 2 (row 409): the segment opener. Every segment is opened read-only through the app's factory, hardened, its
schema compared object by object with the one this build makes, and its recorded identity with its registry row; anything
else is "segment N unavailable" with a fixed reason, never a read of the file."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest

from src.backup.staged_key import db_errors
from src.database import at_rest_state, segment_open
from src.database.connect import have_driver
from src.database.segments import Reservation, Segment, SegmentError

_PW = "r826-stage-2-segment-opener-test-passphrase"
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
    return d


def _shared(monkeypatch, encrypted: bool) -> None:
    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: encrypted)


def _res(n: int, lo: int | None = None) -> Reservation:
    lo = lo if lo is not None else 1000 * n
    return Reservation(n, f"seg-{n}.db", lo, lo + 999)


def _seg(r: Reservation, state: str = "closed") -> Segment:
    return Segment(r.seg_no, r.file_name, state, r.id_lo, r.id_hi)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_segment_files_are_not_written_by_this_build(data, monkeypatch):
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", False)
    with pytest.raises(SegmentError):
        segment_open.create_segment(_res(1), key=_PW)
    assert not (data / "corpus").exists()


def test_nothing_in_src_turns_segment_writes_on():
    root = Path(__file__).resolve().parents[1] / "src"
    hits = [
        str(p) for p in root.rglob("*.py")
        if "SEGMENT_WRITES_ENABLED = True" in p.read_text(encoding="utf-8", errors="replace")
        or "SEGMENT_WRITES_ENABLED=True" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == []


@posix_only
@sqlcipher_only
def test_each_segment_has_its_own_salt_opens_with_the_key_and_is_named_in_the_record(data, monkeypatch):
    _shared(monkeypatch, True)
    p1 = segment_open.create_segment(_res(1), key=_PW)
    p2 = segment_open.create_segment(_res(2), key=_PW)
    assert (os.stat(data / "corpus").st_mode & 0o777) == 0o700
    h1, h2 = p1.read_bytes()[:16], p2.read_bytes()[:16]
    assert h1 != h2 and b"SQLite format 3" not in h1
    stores = json.loads((data / at_rest_state.RECORD_NAME).read_text())["stores"]
    assert {"corpus:seg-1", "corpus:seg-2"} <= set(stores)
    before = _sha(p1)
    con = segment_open.open_segment(_seg(_res(1)), key=_PW)
    try:
        assert con.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        assert con.execute("PRAGMA cell_size_check").fetchone()[0] == 1
        assert con.execute("PRAGMA cache_size").fetchone()[0] == -segment_open.CLOSED_CACHE_KIB
        with pytest.raises(db_errors()):
            con.execute("CREATE TABLE x(y)")  # read-only
    finally:
        con.close()
    assert _sha(p1) == before, "opening a segment writes nothing"


@sqlcipher_only
def test_a_key_that_does_not_open_a_segment_makes_only_that_segment_unavailable(data, monkeypatch):
    _shared(monkeypatch, True)
    segment_open.create_segment(_res(1), key=_PW)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)), key=_PW + "-wrong")
    assert e.value.reason == "wrong_key" and str(e.value) == "segment 1 unavailable"
    assert _PW not in repr(e.value)


@sqlcipher_only
def test_a_plaintext_segment_beside_an_encrypted_corpus_is_never_read(data, monkeypatch):
    _shared(monkeypatch, False)
    segment_open.create_segment(_res(1), key=_PW)
    assert (data / "corpus" / "seg-1.db").read_bytes()[:15] == b"SQLite format 3"
    _shared(monkeypatch, True)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)), key=_PW)
    assert e.value.reason == "encryption_differs"


@sqlcipher_only
def test_an_encrypted_segment_beside_a_plaintext_corpus_is_refused_too(data, monkeypatch):
    _shared(monkeypatch, True)
    segment_open.create_segment(_res(1), key=_PW)
    _shared(monkeypatch, False)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)), key=_PW)
    assert e.value.reason == "encryption_differs"


def _plain_segment(data: Path, monkeypatch, r: Reservation, extra: tuple[str, ...] = ()) -> Path:
    _shared(monkeypatch, False)
    p = segment_open.create_segment(r)
    if extra:
        con = sqlite3.connect(p)
        for sql in extra:
            con.execute(sql)
        con.commit()
        con.close()
    return p


@pytest.mark.parametrize(
    "extra",
    [
        ("CREATE TABLE evil(x)",),
        ("CREATE INDEX ix_meta ON segment_meta(seg_no)",),
        ("CREATE VIEW v AS SELECT 1",),
        ("CREATE TRIGGER tr AFTER INSERT ON segment_meta BEGIN SELECT 1; END",),
    ],
)
def test_a_schema_that_is_not_exactly_the_apps_is_refused_before_any_row_is_read(data, monkeypatch, extra):
    _plain_segment(data, monkeypatch, _res(1), extra)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "schema"


def test_sqlite_statistics_tables_are_allowed(data, monkeypatch):
    p = _plain_segment(data, monkeypatch, _res(1))
    con = sqlite3.connect(p)
    con.execute("ANALYZE")
    con.commit()
    con.close()
    segment_open.open_segment(_seg(_res(1))).close()


def test_the_reference_schema_is_what_the_segment_ddl_makes(data, monkeypatch):
    p = _plain_segment(data, monkeypatch, _res(1))
    con = sqlite3.connect(p)
    try:
        assert segment_open._schema_of(con) == segment_open.reference_schema()
    finally:
        con.close()


@pytest.mark.parametrize("row", [Segment(1, "seg-1.db", "closed", 1000, 1998), Segment(1, "seg-1.db", "closed", 999, 1999)])
def test_a_file_recording_another_identity_is_not_that_segment(data, monkeypatch, row):
    _plain_segment(data, monkeypatch, _res(1))
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(row)
    assert e.value.reason == "identity"


def test_a_file_named_for_another_segment_is_refused(data, monkeypatch):
    p = _plain_segment(data, monkeypatch, _res(1))
    os.rename(p, p.with_name("seg-2.db"))
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(2)))
    assert e.value.reason == "identity"


def test_a_missing_segment_is_missing_and_nothing_is_created(data, monkeypatch):
    _shared(monkeypatch, False)
    (data / "corpus").mkdir()
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(3)))
    assert e.value.reason == "missing"
    assert list((data / "corpus").iterdir()) == []


@posix_only
def test_links_and_second_names_are_not_segment_files(data, monkeypatch, tmp_path):
    p = _plain_segment(data, monkeypatch, _res(1))
    os.link(p, tmp_path / "second-name.db")
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "not_a_segment_file"
    os.unlink(tmp_path / "second-name.db")
    os.rename(p, tmp_path / "elsewhere.db")
    os.symlink(tmp_path / "elsewhere.db", p)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "not_a_segment_file"


@posix_only
def test_a_linked_corpus_folder_is_not_the_corpus_folder(data, monkeypatch, tmp_path):
    _plain_segment(data, monkeypatch, _res(1))
    os.rename(data / "corpus", tmp_path / "real-corpus")
    os.symlink(tmp_path / "real-corpus", data / "corpus")
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "not_a_segment_file"


def test_segment_zero_is_never_opened_here():
    with pytest.raises(SegmentError):
        segment_open.open_segment(Segment(0, None, "closed", 1, 10))


def test_a_new_segment_never_overwrites_a_file_with_its_name(data, monkeypatch):
    _shared(monkeypatch, False)
    (data / "corpus").mkdir()
    (data / "corpus" / "seg-1.db").write_bytes(b"someone else's file")
    with pytest.raises(SegmentError):
        segment_open.create_segment(_res(1))
    assert (data / "corpus" / "seg-1.db").read_bytes() == b"someone else's file"


def test_the_set_opens_newest_first_and_counts_unavailable_segments(data, monkeypatch):
    for n in (1, 2, 3):
        _plain_segment(data, monkeypatch, _res(n))
    (data / "corpus" / "seg-2.db").write_bytes(b"SQLite format 3\0" + b"\xff" * 4080)  # damaged
    regs = [
        Segment(0, None, "closed", 1, 999),
        _seg(_res(1)), _seg(_res(2)), _seg(_res(3), "open"),
        Segment(4, "seg-4.db", "abandoned", 4000, 4999),
        Segment(5, "seg-5.db", "reserved", 5000, 5999),
    ]
    wanted = segment_open.SegmentSet.wanted(regs)
    assert [s.seg_no for s in wanted] == [3, 2, 1]
    order: list[int] = []
    real = segment_open.open_segment

    def spy(seg, key=None):
        order.append(seg.seg_no)
        return real(seg, key=key)

    monkeypatch.setattr(segment_open, "open_segment", spy)
    sset = segment_open.SegmentSet(segments=wanted)
    assert sset.status()["opening"] is True
    sset.open_all(threads=1)
    st = sset.status()
    assert order == [3, 2, 1]
    assert st == {"total": 3, "opened": 2, "opening": False, "unavailable": [{"segment": 2, "reason": "unreadable"}]}
    assert sset.connection(3) is not None and sset.connection(2) is None
    sset.close()
    assert sset.status()["opened"] == 0


def test_an_empty_registry_starts_nothing(monkeypatch):
    con = sqlite3.connect(":memory:")
    before = threading.active_count()
    assert segment_open.start_background_open(lambda: con) is None
    assert threading.active_count() == before
    assert segment_open.current_status() == {"total": 0, "opened": 0, "opening": False, "unavailable": []}


def test_the_background_open_and_close_all(data, monkeypatch):
    _plain_segment(data, monkeypatch, _res(1))
    shared = sqlite3.connect(":memory:", check_same_thread=False)
    shared.execute(
        "CREATE TABLE corpus_segments (seg_no INTEGER PRIMARY KEY, file_name TEXT, state TEXT, id_lo INTEGER,"
        " id_hi INTEGER, created_at TEXT, state_at TEXT)"
    )
    shared.execute("CREATE TABLE corpus_id_counter (id INTEGER PRIMARY KEY, next_id INTEGER)")
    shared.execute("INSERT INTO corpus_segments VALUES (1, 'seg-1.db', 'closed', 1000, 1999, '', '')")
    try:
        sset = segment_open.start_background_open(lambda: shared)
        assert sset is not None
        sset._done.wait(30)
        assert segment_open.current_status()["opened"] == 1
        from src.database.session import dispose_engine

        dispose_engine()
        assert segment_open.current_status()["total"] == 0, "a disposal (lock, erase, restore) closes every segment"
    finally:
        segment_open.close_all()


def test_health_says_n_of_m_only_when_there_are_segments(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    client = TestClient(app)
    assert "segments" not in client.get("/api/health").json()
    status = {"total": 3, "opened": 1, "opening": True, "unavailable": [{"segment": 2, "reason": "wrong_key"}]}
    monkeypatch.setattr(segment_open, "current_status", lambda: status)
    assert client.get("/api/health").json()["segments"] == status


def test_start_up_asks_for_the_segments_after_the_schema():
    import ast

    tree = ast.parse((Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_deferred_startup")
    lines = {
        c.func.id: c.lineno
        for c in ast.walk(fn)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
    }
    assert lines["init_db"] < lines["_open_corpus_segments"] < lines["_run_startup_upkeep"]


def test_the_opener_creates_and_writes_only_behind_the_switch():
    import ast
    import inspect

    fn = ast.parse(inspect.getsource(segment_open.create_segment)).body[0]
    first = fn.body[1] if isinstance(fn.body[0], ast.Expr) else fn.body[0]
    while isinstance(first, ast.ImportFrom):
        first = fn.body[fn.body.index(first) + 1]
    assert isinstance(first, ast.If) and "SEGMENT_WRITES_ENABLED" in ast.unparse(first.test)
