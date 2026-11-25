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


def _opener_threads() -> list[str]:
    """The opener's own threads, by name: a count of every thread in the process moves with whatever else the run started."""
    return [t.name for t in threading.enumerate() if t.name.startswith("oo-segment")]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_segment_files_are_not_written_by_this_build(data, monkeypatch):
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", False)
    with pytest.raises(SegmentError):
        segment_open.create_segment(_res(1), key=_PW)
    assert not (data / "corpus").exists()


def test_nothing_in_src_turns_segment_writes_on():
    import re

    root = Path(__file__).resolve().parents[1] / "src"
    named = re.compile(r"SEGMENT_WRITES_ENABLED")
    hits = []
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if p.name == "segment_open.py":
            # its own definition, and the reads of it, only: never an assignment to anything but False
            assigned = re.findall(r"SEGMENT_WRITES_ENABLED\s*(?::\s*\w+\s*)?=(?!=)\s*(\w+)", text)
            if assigned != ["False"]:
                hits.append(f"{p}: {assigned}")
        elif named.search(text):
            hits.append(str(p))  # no other module names the switch at all: no setattr, no import, no assignment
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
    stores = json.loads((data / at_rest_state.RECORD_NAME).read_text(encoding="utf-8"))["stores"]
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
    damaged = bytearray(b"\xff" * 4096)
    damaged[:16] = b"SQLite format 3\0"
    damaged[18] = damaged[19] = 1  # a rollback-journal header, so the damage is found by the open, not the header check
    (data / "corpus" / "seg-2.db").write_bytes(bytes(damaged))
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
    assert segment_open.start_background_open(lambda: con) is None
    assert _opener_threads() == []
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


def test_every_open_of_the_store_asks_for_the_segments_as_its_last_init_step():
    """The boot, the unlock and every disposal-then-reopen (restore, repair, merge) go through init_db; the segments open at
    its end, so an unlocked or restored corpus never reads as one without segments."""
    import ast

    root = Path(__file__).resolve().parents[1] / "src"
    tree = ast.parse((root / "database" / "session.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "init_db")
    calls = [ast.unparse(c.value.func) for c in fn.body if isinstance(c, ast.Expr) and isinstance(c.value, ast.Call)]
    assert calls[-1] == "_open_segments"
    assert "init_db()" in (root / "api" / "unlock.py").read_text(encoding="utf-8")
    assert "_open_corpus_segments" not in (root / "api" / "main.py").read_text(encoding="utf-8")


def test_a_disposal_then_init_db_opens_the_segments_again(monkeypatch):
    from src.database import session

    calls: list[str] = []
    monkeypatch.setattr(segment_open, "start_background_open", lambda *a, **k: calls.append("open"))
    session._open_segments()
    assert calls == ["open"]

    def boom(*a, **k):
        raise RuntimeError("registry")

    monkeypatch.setattr(segment_open, "start_background_open", boom)
    session._open_segments()  # never fails the init


def test_the_opener_creates_and_writes_only_behind_the_switch():
    import ast
    import inspect

    fn = ast.parse(inspect.getsource(segment_open.create_segment)).body[0]
    first = fn.body[1] if isinstance(fn.body[0], ast.Expr) else fn.body[0]
    while isinstance(first, ast.ImportFrom):
        first = fn.body[fn.body.index(first) + 1]
    assert isinstance(first, ast.If) and "SEGMENT_WRITES_ENABLED" in ast.unparse(first.test)


# --- the two security reads (2026-11-25) ---


@posix_only
def test_a_plaintext_segment_in_wal_mode_is_refused_and_no_wal_or_shm_is_made(data, monkeypatch):
    p = _plain_segment(data, monkeypatch, _res(1))
    con = sqlite3.connect(p)
    assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    con.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{p}{suffix}").unlink(missing_ok=True)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "not_a_segment_file"
    assert sorted(x.name for x in (data / "corpus").iterdir()) == ["seg-1.db"], "the refusal created no -wal or -shm"


@posix_only
@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_a_hard_linked_or_linked_sidecar_is_refused_before_any_open(data, monkeypatch, tmp_path, suffix):
    p = _plain_segment(data, monkeypatch, _res(1))
    victim = tmp_path / "victim"
    victim.write_bytes(b"v" * 1500)
    os.link(victim, f"{p}{suffix}")
    opened: list[int] = []
    monkeypatch.setattr("src.database.connect.connect", lambda *a, **k: opened.append(1))
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "not_a_segment_file" and opened == []
    assert victim.read_bytes() == b"v" * 1500
    os.unlink(f"{p}{suffix}")
    os.symlink(victim, f"{p}{suffix}")
    with pytest.raises(segment_open.SegmentUnavailable):
        segment_open.open_segment(_seg(_res(1)))


@posix_only
def test_encryption_is_compared_on_the_header_before_any_driver_sees_the_file(data, monkeypatch):
    _plain_segment(data, monkeypatch, _res(1))
    _shared(monkeypatch, True)
    opened: list[int] = []
    monkeypatch.setattr("src.database.connect.connect", lambda *a, **k: opened.append(1))
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)), key=_PW)
    assert e.value.reason == "encryption_differs" and opened == []


@posix_only
def test_encryption_is_checked_again_on_the_driver_the_open_used(data, monkeypatch):
    """A file swapped for a plaintext one during the open and back again: the header said encrypted, the standard driver
    opened it, and that is refused whatever an earlier open of the name recorded."""
    p = _plain_segment(data, monkeypatch, _res(1))
    _shared(monkeypatch, True)
    monkeypatch.setattr(segment_open, "_header_encrypted", lambda header: True)
    monkeypatch.setattr("src.database.connect.connect", lambda *a, **k: sqlite3.connect(f"file:{p}?mode=ro", uri=True))
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)), key=_PW)
    assert e.value.reason == "encryption_differs"


@posix_only
def test_a_segment_another_program_holds_is_in_use_not_a_wrong_key(data, monkeypatch):
    from src.database.connect import StoreHeldError

    _plain_segment(data, monkeypatch, _res(1))

    def held(*a, **k):
        raise StoreHeldError("held")

    monkeypatch.setattr("src.database.connect.connect", held)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "in_use"


def test_a_registry_that_cannot_be_read_says_so_never_zero(monkeypatch):
    def broken():
        raise sqlite3.DatabaseError("malformed")

    try:
        assert segment_open.start_background_open(broken) is None
        st = segment_open.current_status()
        assert st["total"] is None and st["registry"] == "unreadable"
    finally:
        segment_open.close_all()
    assert segment_open.current_status()["total"] == 0


def test_health_says_the_registry_was_not_read(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setattr(segment_open, "current_status", lambda: dict(segment_open.REGISTRY_UNREADABLE))
    seg = TestClient(app).get("/api/health").json()["segments"]
    assert seg["total"] is None and seg["registry"] == "unreadable"


def test_a_set_read_from_a_registry_a_disposal_overtook_is_never_installed(monkeypatch):
    shared = sqlite3.connect(":memory:", check_same_thread=False)
    shared.execute(
        "CREATE TABLE corpus_segments (seg_no INTEGER PRIMARY KEY, file_name TEXT, state TEXT, id_lo INTEGER,"
        " id_hi INTEGER, created_at TEXT, state_at TEXT)"
    )
    shared.execute("CREATE TABLE corpus_id_counter (id INTEGER PRIMARY KEY, next_id INTEGER)")
    shared.execute("INSERT INTO corpus_segments VALUES (1, 'seg-1.db', 'closed', 1000, 1999, '', '')")

    def factory():
        segment_open.close_all()  # a lock or an erase lands while the registry is read
        return shared

    try:
        assert segment_open.start_background_open(factory) is None
        assert segment_open.current_status()["total"] == 0
        assert _opener_threads() == []
    finally:
        segment_open.close_all()


@posix_only
def test_a_new_segment_name_swapped_for_a_link_gets_no_table_and_no_row(data, monkeypatch, tmp_path):
    """The name is taken empty with O_EXCL; a link put in its place before the write (here: to another database, as the
    shared corpus would be) is found by the inode check, and the other file is left as it was."""
    from src.database import connect as connect_mod

    other = tmp_path / "other.db"
    sqlite3.connect(other).close()
    sqlite3.connect(other).execute("CREATE TABLE keep(x)").connection.commit()
    before = _sha(other)
    _shared(monkeypatch, False)
    real = connect_mod.connect

    def swap_then_connect(path, *a, **k):
        os.unlink(path)
        os.symlink(other, path)
        return real(path, *a, **k)

    monkeypatch.setattr(connect_mod, "connect", swap_then_connect)
    with pytest.raises(SegmentError):
        segment_open.create_segment(_res(1))
    assert _sha(other) == before


@posix_only
def test_a_link_already_at_the_name_is_never_followed(data, monkeypatch, tmp_path):
    other = tmp_path / "dangling-target.db"
    (data / "corpus").mkdir(mode=0o700)
    os.symlink(other, data / "corpus" / "seg-1.db")
    _shared(monkeypatch, False)
    with pytest.raises(SegmentError):
        segment_open.create_segment(_res(1))
    assert not other.exists()


@sqlcipher_only
def test_a_segment_the_record_refuses_is_a_failed_create(data, monkeypatch):
    _shared(monkeypatch, True)
    monkeypatch.setattr(at_rest_state, "record_segment", lambda *a, **k: False)
    with pytest.raises(SegmentError):
        segment_open.create_segment(_res(1), key=_PW)
    assert list((data / "corpus").iterdir()) == [], "a failed create frees its name"
    monkeypatch.undo()
    _carry_data(data, monkeypatch)
    _shared(monkeypatch, True)
    segment_open.create_segment(_res(1), key=_PW)  # the same reservation can be made again


# --- stage 3 carry-overs from the final read of stage 2 (L1 to L4, L6) ---


def _carry_data(data: Path, monkeypatch) -> None:
    """Re-apply the ``data`` fixture's settings after a ``monkeypatch.undo()``."""
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    import src.api.unlock as unlock

    monkeypatch.setattr(unlock, "main_db_path", lambda **_: data / "open_omniscience.db")
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", True)


@posix_only
@sqlcipher_only
def test_an_encrypted_segment_in_wal_mode_is_refused_and_its_wal_and_shm_are_removed(data, monkeypatch):
    from src.database.connect import connect

    _shared(monkeypatch, True)
    p = segment_open.create_segment(_res(1), key=_PW)
    con = connect(p, key=_PW, cipher_page_size=segment_open.SEGMENT_PAGE_SIZE)
    assert str(con.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
    con.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{p}{suffix}").unlink(missing_ok=True)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)), key=_PW)
    assert e.value.reason == "not_a_segment_file"
    assert sorted(x.name for x in (data / "corpus").iterdir()) == ["seg-1.db"], "the refused open left no -wal or -shm"


@posix_only
def test_a_sidecar_that_was_there_before_a_refused_open_is_left_alone(data, monkeypatch):
    p = _plain_segment(data, monkeypatch, _res(1), extra=("CREATE TABLE evil(x)",))
    Path(f"{p}-shm").write_bytes(b"")
    Path(f"{p}-wal").write_bytes(b"")
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == "schema"
    assert sorted(x.name for x in (data / "corpus").iterdir()) == ["seg-1.db", "seg-1.db-shm", "seg-1.db-wal"]


def test_only_empty_new_wal_and_new_shm_are_removed(tmp_path):
    p = tmp_path / "seg-1.db"
    p.write_bytes(b"x")
    Path(f"{p}-wal").write_bytes(b"pages")  # holds pages: never removed
    Path(f"{p}-shm").write_bytes(b"")
    Path(f"{p}-journal").write_bytes(b"")  # a writer's journal: never removed here
    segment_open._remove_sidecars_made(p, frozenset({"-wal", "-shm", "-journal"}))
    assert sorted(x.name for x in tmp_path.iterdir()) == ["seg-1.db", "seg-1.db-journal", "seg-1.db-wal"]


def _held_error() -> sqlite3.OperationalError:
    exc = sqlite3.OperationalError("database is locked")
    exc.sqlite_errorcode = 5  # SQLITE_BUSY
    return exc


@posix_only
@pytest.mark.parametrize(("error", "reason"), [(_held_error, "in_use"), (lambda: sqlite3.DatabaseError("malformed"), "unreadable")])
def test_a_schema_that_could_not_be_read_is_never_reported_as_a_foreign_schema(data, monkeypatch, error, reason):
    _plain_segment(data, monkeypatch, _res(1))

    def unread(con):
        raise error()

    monkeypatch.setattr(segment_open, "_schema_of", unread)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_open.open_segment(_seg(_res(1)))
    assert e.value.reason == reason


def test_check_schema_is_false_only_for_a_schema_it_read():
    con = sqlite3.connect(":memory:")
    try:
        for ddl in segment_open.SEGMENT_DDL:
            con.execute(ddl)
        assert segment_open.check_schema(con) is True
        con.execute("CREATE TABLE evil(x)")
        assert segment_open.check_schema(con) is False
    finally:
        con.close()
    with pytest.raises(sqlite3.ProgrammingError):
        segment_open.check_schema(con)  # closed: raises, never False


def test_a_closed_set_opens_nothing_more(monkeypatch):
    opened: list[int] = []
    monkeypatch.setattr(segment_open, "open_segment", lambda seg, key=None: opened.append(seg.seg_no))
    sset = segment_open.SegmentSet(segments=[_seg(_res(2)), _seg(_res(1))])
    sset.close()
    sset.open_all(threads=1)
    assert opened == [] and sset.status()["opened"] == 0


@posix_only
def test_a_failed_plaintext_create_frees_its_name(data, monkeypatch):
    _shared(monkeypatch, False)

    def refuse(con, r):
        raise SegmentError("the registry refused it")

    monkeypatch.setattr(segment_open, "commit_segment", refuse)
    with pytest.raises(SegmentError):
        segment_open.create_segment(_res(1))
    assert list((data / "corpus").iterdir()) == []


@posix_only
def test_a_failed_create_never_removes_a_file_it_did_not_make(data, monkeypatch, tmp_path):
    other = tmp_path / "other.db"
    other.write_bytes(b"someone else's file")
    _shared(monkeypatch, False)
    real = segment_open.commit_segment

    def swap_then_fail(con, r):
        name = data / "corpus" / r.file_name
        os.unlink(name)
        os.link(other, name)  # the name now leads to a file with two names
        raise SegmentError("failed after the swap")

    monkeypatch.setattr(segment_open, "commit_segment", swap_then_fail)
    with pytest.raises(SegmentError) as e:
        segment_open.create_segment(_res(1))
    assert "left in place" in str(e.value)
    assert (data / "corpus" / "seg-1.db").read_bytes() == b"someone else's file" and other.exists()
    monkeypatch.setattr(segment_open, "commit_segment", real)
