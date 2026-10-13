"""The first failed read is read again by itself (damaged-database plan, slice E1: the re-read of the latch).

E1 pauses collection on the first ``SQLITE_CORRUPT`` it sees, from one read on one connection. A code 11 that a fresh read does not repeat
(memory pressure, a copy made while the file changed) used to pause an unattended machine until someone started collection again. The
maintainer's coordinator ruled (2026-10-13): the pause comes AT ONCE (the writers stop before anything is read, and a provisional pause is
not a damaged verdict), the tables the failing statement names are read again on fresh connections, and the pause ends by itself when they
all read clean; a table that reads clean and then fails again in the same process latches and STAYS, and the page says why.

Every claim about a verdict is made against REAL SQLite files (pages overwritten as ``test_database_damage.py`` does); the error that a
healthy file does not give is a driver-shaped one handed to ``note``, so the read that follows is the REAL re-read of a healthy file.

  * (a) a damaged table: the re-read confirms it, the latch stays, the record says ``damaged`` (and the damage is filed as a finding);
  * (b) a healthy file: the pause is set at once, said as provisional, and ends by itself; the incident is answered, the record says so;
  * (c) the same table failing again: it latches and stays, with NO second re-read, and a start still releases it;
  * (d)/(e) a statement that names nothing the file has is never counted as clean;
  * (f) a re-read that cannot be made (switch off, no file, check running, table list unreadable, a stop, a failure) leaves the latch as
    a first failed read leaves it, with the reason in the record;
  * (g) a CLOSED connection handed to ``note_raw_driver_error`` still latches (OPEN_QUEUE (e));
  * (h) a read that fails while the re-read runs keeps the latch; a start during the re-read does not release it.
"""
from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from src.database import damage, verify
from src.database.damage import (
    FILE_CORPUS,
    FILE_LAW,
    FILE_WIKI,
    REREAD_CLEAN,
    REREAD_CLEAN_HELD,
    REREAD_DAMAGED,
    REREAD_NOT_MADE,
    REREAD_STAYED,
    REREAD_UNREAD,
    DamageRegistry,
    statement_names,
)
from src.scheduler import storage_guard as sg

ROOT = Path(__file__).resolve().parents[1]
PAGE = 4096
READ = "SELECT title FROM articles WHERE id = ?"


# --------------------------------------------------------------------------- #
#  fixtures: a real store, a real damaged copy, a registry of this test's own
# --------------------------------------------------------------------------- #
def _build_store(path: Path, rows: int = 3000, fts: bool = False) -> None:
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA page_size={PAGE}")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT)")
    con.execute("CREATE INDEX ix_articles_title ON articles (title)")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    rng = random.Random(7)
    con.executemany(
        "INSERT INTO articles (title, content) VALUES (?, ?)",
        [(f"title {i}", "".join(rng.choice("abcdefghij ") for _ in range(900))) for i in range(rows)],
    )
    con.executemany("INSERT INTO notes (body) VALUES (?)", [(f"note {i}",) for i in range(20)])
    if fts:
        con.execute("CREATE VIRTUAL TABLE article_fts USING fts5(title, content)")
        con.execute("INSERT INTO article_fts (title, content) SELECT title, content FROM articles")
    con.commit()
    con.close()


def _leaf_pages(path: Path, table: str) -> list[int]:
    con = sqlite3.connect(path)
    try:
        return [p for p, t in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name=?", (table,)) if t == "leaf"]
    except sqlite3.OperationalError:
        pytest.skip("this SQLite build has no dbstat virtual table (SQLITE_ENABLE_DBSTAT_VTAB)")
    finally:
        con.close()


def _overwrite(path: Path, pages: list[int]) -> None:
    with open(path, "r+b") as f:
        for pg in pages:
            f.seek((pg - 1) * PAGE)
            f.write(random.Random(pg).randbytes(PAGE))


@pytest.fixture
def healthy(tmp_path):
    path = tmp_path / "corpus.db"
    _build_store(path)
    return path


@pytest.fixture
def damaged(tmp_path):
    path = tmp_path / "corpus.db"
    _build_store(path)
    _overwrite(path, sorted(random.Random(1).sample(_leaf_pages(path, "articles"), 3)))
    return path


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """A registry of this test's own, the process-global one for the length of the test, with the re-read ON (the process's own is built
    that way; the suite's isolation fixture switches the global one off, and a registry built without the argument is not re-reading)."""
    r = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json", rereads=True)
    monkeypatch.setattr(damage, "registry", r)
    verify._reset_for_tests()
    yield r
    verify._reset_for_tests()


def _corrupt():
    cls = type("DatabaseError", (Exception,), {"__module__": "sqlite3"})
    exc = cls("database disk image is malformed")
    exc.sqlite_errorcode = 11
    return exc


def _fail(reg, path, statement=READ, key=FILE_CORPUS):
    return reg.note(key, _corrupt(), statement=statement, path=path)


def _file(reg, key=FILE_CORPUS):
    return reg.state()["files"].get(key) or {}


def _settled(reg, key=FILE_CORPUS, timeout=60.0):
    """The file's state once no re-read holds a claim on it."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = _file(reg, key)
        if not st.get("rechecking"):
            return st
        time.sleep(0.02)
    raise AssertionError("the re-read did not end")


def _join_rereads(timeout=60.0):
    """Wait for every re-read thread to end, and fail if one does not: an assertion about what a LATE answer did is only about that
    answer once the thread that gives it has ended."""
    end = time.monotonic() + timeout
    for t in [t for t in threading.enumerate() if t.name == "oo-database-reread"]:
        t.join(max(0.0, end - time.monotonic()))
    assert not [t for t in threading.enumerate() if t.name == "oo-database-reread" and t.is_alive()], "a re-read thread did not end"


class _Hold:
    """Stops ``verify.check_table`` at its first call until ``release()``: the pause is then observed WHILE the re-read runs."""

    def __init__(self, monkeypatch):
        self.entered = threading.Event()
        self._go = threading.Event()
        self.calls: list[str] = []
        real = verify.check_table

        def slow(path, table, **kw):
            self.calls.append(table)
            self.entered.set()
            assert self._go.wait(60), "the test never released the re-read"
            return real(path, table, **kw)

        monkeypatch.setattr(verify, "check_table", slow)

    def release(self):
        self._go.set()


def _frames(reg):
    return [n["frame"] for n in reg.notes()]


# --------------------------------------------------------------------------- #
#  the names a statement writes
# --------------------------------------------------------------------------- #
def test_statement_names_are_every_identifier_in_every_quoting_and_no_value():
    assert statement_names(None) == frozenset() and statement_names("") == frozenset()
    got = statement_names(
        "SELECT a.id, \"Sources\".x FROM articles a, `notes` JOIN [Keywords] k ON k.x = 'Secret' WHERE a.id IN (?, ?) LIMIT 5"
    )
    assert {"articles", "notes", "sources", "keywords"} <= got, "a comma join, a join and every quoting are written names"
    assert "secret" not in got, "a string literal names nothing"
    assert statement_names("SELECT 1 FROM ARTICLES") >= {"articles"}, "SQLite's names are case-blind: lower-cased"
    assert "main" in statement_names("SELECT * FROM main.articles") and "articles" in statement_names("SELECT * FROM main.articles")
    assert "a b" in statement_names('SELECT * FROM "a b"') and "a\"b" in statement_names('SELECT * FROM "a""b"')


# --------------------------------------------------------------------------- #
#  (a) a damaged table: the re-read confirms it
# --------------------------------------------------------------------------- #
def test_a_damaged_table_is_confirmed_by_the_re_read_and_the_latch_stays(reg, damaged):
    from tests.test_database_damage import _first_failing_read

    eng = create_engine(f"sqlite:///{damaged}")
    damage.attach(eng, FILE_CORPUS)
    lo, exc = _first_failing_read(eng)
    assert exc is not None, "the page overwrite no longer shows up through a read"
    assert reg.latched(FILE_CORPUS), "the pause is set by the failed read itself"
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS), "a table that reads damaged again keeps the pause"
    assert st["reread"]["result"] == REREAD_DAMAGED and st["reread"]["tables"] == ["articles"], st["reread"]
    assert st["check_tables"] == ["articles"], "the finding is the per-table check's: a start reads it again"
    assert "auto_released" not in st
    frames = _frames(reg)
    assert damage.FRAME_DATA in frames and damage.FRAME_REREADING not in frames, "provisional no more"
    kinds = {i.get("code_name") for i in reg.state(detail=True)["incidents"]}
    assert "SQLITE_CORRUPT" in kinds


# --------------------------------------------------------------------------- #
#  (b) a healthy file: paused at once, provisional, released by itself, recorded as such
# --------------------------------------------------------------------------- #
def test_a_failed_read_that_does_not_repeat_pauses_at_once_and_ends_by_itself(reg, healthy, monkeypatch, tmp_path):
    hold = _Hold(monkeypatch)
    assert _fail(reg, healthy)
    assert reg.latched(FILE_CORPUS), "the writers stop before anything is read"
    assert sg.storage_guard.admit() == "damage"
    assert hold.entered.wait(60)
    assert reg.latched(FILE_CORPUS)
    assert damage.FRAME_REREADING in _frames(reg), "the page says the pause is provisional while the table is read again"
    [inc] = reg.state(detail=True)["incidents"]
    assert not inc.get("superseded"), "nothing is answered before the re-read is"
    hold.release()
    st = _settled(reg)
    assert not reg.latched(FILE_CORPUS), "a clean re-read ends the pause by itself"
    assert sg.storage_guard.admit() is None, "the scheduler's pause loop sees the latch gone"
    assert st["reread"]["result"] == REREAD_CLEAN and st["reread"]["tables"] == ["articles"], "only the table the statement names was read"
    assert hold.calls == ["articles"]
    assert st["auto_released"] == ["articles"]
    [inc] = reg.state(detail=True)["incidents"]
    assert inc["superseded"] is True, "the failed read is answered: the next start does not owe a check for it"
    assert reg.notes() == []
    assert reg.flush_durable()
    on_disk = json.loads((tmp_path / "database-damage.json").read_text(encoding="utf-8"))["files"][FILE_CORPUS]
    assert on_disk["reread"]["result"] == REREAD_CLEAN and "auto_released" not in on_disk and "rechecking" not in on_disk


def test_a_statement_over_several_tables_reads_each_and_a_damaged_one_keeps_the_latch(reg, tmp_path):
    path = tmp_path / "corpus.db"
    _build_store(path)
    _overwrite(path, sorted(random.Random(1).sample(_leaf_pages(path, "articles"), 3)))
    assert _fail(reg, path, "SELECT n.body, a.title FROM notes n JOIN articles a ON a.id = n.id WHERE a.id > ?")
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS)
    assert st["reread"]["result"] == REREAD_DAMAGED and st["reread"]["tables"] == ["articles", "notes"]
    assert st["check_tables"] == ["articles"], "the table that read clean is not carried as a finding"


# --------------------------------------------------------------------------- #
#  (c) the same table failing again: it stays
# --------------------------------------------------------------------------- #
def test_a_table_that_failed_again_after_a_clean_re_read_latches_and_stays(reg, healthy, monkeypatch):
    calls: list[tuple] = []
    real = verify.reread
    monkeypatch.setattr(verify, "reread", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    assert _fail(reg, healthy)
    _settled(reg)
    assert not reg.latched(FILE_CORPUS) and len(calls) == 1

    assert _fail(reg, healthy)
    assert reg.latched(FILE_CORPUS)
    st = _file(reg)
    time.sleep(0.2)  # a re-read that wrongly started would have settled by now
    assert len(calls) == 1, "no second automatic re-read for a table that was already released"
    assert reg.latched(FILE_CORPUS) and not _file(reg).get("rechecking")
    assert st["reread"]["result"] == REREAD_STAYED and st["auto_stayed"] == ["articles"]
    frames = _frames(reg)
    assert damage.FRAME_STAYED in frames and damage.FRAME_REREADING not in frames
    [inc] = reg.state(detail=True)["incidents"]
    assert not inc.get("superseded"), "a failed read after the answer is a new reason to check at the next start"

    assert reg.retry(reason="the operator started collection") == [FILE_CORPUS], "a start still lifts the pause"
    assert not reg.latched(FILE_CORPUS) and "auto_stayed" not in _file(reg)
    assert _fail(reg, healthy) and reg.latched(FILE_CORPUS)
    time.sleep(0.2)
    assert len(calls) == 1, "and the first failed read after that pauses it again, still without a re-read"
    assert _file(reg)["auto_stayed"] == ["articles"]


def test_a_different_table_after_a_clean_re_read_is_read_in_its_turn(reg, healthy):
    assert _fail(reg, healthy)
    _settled(reg)
    assert _fail(reg, healthy, "SELECT body FROM notes WHERE id = ?")
    st = _settled(reg)
    assert not reg.latched(FILE_CORPUS), "notes never failed before: its first failure is read again like any first"
    assert st["auto_released"] == ["articles", "notes"] and st["reread"]["tables"] == ["notes"]


# --------------------------------------------------------------------------- #
#  (d)/(e) a statement that names nothing the file has
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "statement, why",
    [
        ("SELECT * FROM a_table_this_file_does_not_have", "no-table-named"),
        ("SELECT 1", "no-table-named"),
        (None, "no-statement"),
    ],
)
def test_a_statement_that_names_no_table_of_the_file_never_releases_the_latch(reg, healthy, statement, why):
    assert _fail(reg, healthy, statement)
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS), "a name that is not in the file is never counted as a table that read clean"
    assert st["reread"]["result"] == REREAD_NOT_MADE and st["reread"]["why"] == why
    assert "check_tables" not in st and "auto_released" not in st
    assert reg.retry(reason="start") == [FILE_CORPUS], "the latch is exactly what a first failed read leaves: a start releases it"


# --------------------------------------------------------------------------- #
#  (f) a re-read that cannot be made
# --------------------------------------------------------------------------- #
def test_a_re_read_that_is_switched_off_is_not_made(reg, healthy, monkeypatch):
    monkeypatch.setenv("OO_BOOT_VERIFY", "0")
    assert _fail(reg, healthy)
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS) and st["reread"] == {**st["reread"], "result": REREAD_NOT_MADE, "why": "switched-off"}


def test_no_file_to_read_is_not_a_clean_read(reg, tmp_path):
    assert _fail(reg, tmp_path / "gone.db")
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS) and st["reread"]["why"] == "no-file"
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert _fail(reg, empty, key=FILE_WIKI)
    assert _settled(reg, FILE_WIKI)["reread"]["why"] == "no-file"
    assert not (tmp_path / "gone.db").exists(), "a re-read must never be what makes a data file exist"


def test_a_check_that_is_running_decides_instead_of_the_re_read(reg, healthy):
    reg.verification_arm("test")
    assert _fail(reg, healthy)
    st = _file(reg)
    assert reg.latched(FILE_CORPUS) and not st.get("rechecking") and st["reread"]["why"] == "check-running"


def test_a_table_list_that_cannot_be_read_keeps_the_latch(reg, healthy, monkeypatch):
    monkeypatch.setattr(verify, "inspect_confirmed", lambda path, **k: {"error": (damage.VERDICT_UNCHECKED, "locked")})
    assert _fail(reg, healthy)
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS) and st["reread"]["why"] == "list-unreadable"


def test_a_list_two_connections_disagree_about_keeps_the_latch(reg, healthy, monkeypatch):
    monkeypatch.setattr(
        verify, "inspect_confirmed", lambda path, **k: {"names": ["articles"], "facts": {}, "second_read": verify.SECOND_READ_CLEAN}
    )
    assert _fail(reg, healthy)
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS) and st["reread"]["why"] == "list-unreadable"


def test_a_stop_ends_the_re_read_without_an_answer(reg, healthy, monkeypatch):
    hold = _Hold(monkeypatch)
    assert _fail(reg, healthy, "SELECT * FROM articles, notes")
    assert hold.entered.wait(60)
    verify._CANCEL.set()
    hold.release()
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS), "a read that was stopped is no answer"
    assert st["reread"]["why"] == "stopped" and "check_tables" not in st
    assert reg.retry(reason="start") == [FILE_CORPUS]


def test_a_failure_in_the_re_read_keeps_the_latch_and_records_the_class_only(reg, healthy, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError(f"/home/someone/{healthy.name} database disk image is malformed")

    monkeypatch.setattr(verify, "check_table", boom)
    assert _fail(reg, healthy)
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS) and st["reread"]["why"] == "failed" and "check_tables" not in st
    assert reg.flush_durable()
    assert "someone" not in (tmp_path / "database-damage.json").read_text(encoding="utf-8"), "engine text is not recorded"


def test_a_thread_that_cannot_be_started_keeps_the_latch(reg, healthy, monkeypatch):
    real_thread = threading.Thread

    class _NoThread:
        def start(self):
            raise RuntimeError("can't start new thread")

    def factory(*a, **k):
        return _NoThread() if k.get("name") == "oo-database-reread" else real_thread(*a, **k)

    monkeypatch.setattr(verify.threading, "Thread", factory)
    assert _fail(reg, healthy)
    st = _file(reg)
    assert reg.latched(FILE_CORPUS) and not st.get("rechecking") and st["reread"]["why"] == "no-thread"


def test_the_pause_switch_off_starts_no_re_read(reg, healthy, monkeypatch):
    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    assert _fail(reg, healthy)
    st = _file(reg)
    assert not st.get("rechecking") and "reread" not in st, "nothing is paused, so nothing is released"


def test_a_file_with_no_writer_to_pause_starts_no_re_read(reg, healthy):
    assert _fail(reg, healthy, key="osm")
    st = _file(reg, "osm")
    assert not st.get("rechecking") and "reread" not in st


def test_the_re_read_is_on_in_the_process_and_only_the_suites_isolation_fixture_turns_it_off():
    import subprocess
    import sys

    # A fresh interpreter: this process's own registry has been through the suite's isolation fixture already.
    out = subprocess.run(
        [sys.executable, "-c", "from src.database import damage; print(damage.registry.rereads)"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=True,
    )
    assert out.stdout.strip() == "True", "the process's own registry must re-read a first failed read"
    assert DamageRegistry(path_fn=lambda: Path("x")).rereads is False, "a registry built for a test is not re-reading unless asked"
    needle = ".rereads" + " = False"
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "tests").rglob("*.py"))
        if p.name not in ("conftest.py", Path(__file__).name) and needle in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"only tests/conftest.py switches the re-read off: {offenders}"
    assert "damage.registry" + needle in (ROOT / "tests/conftest.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  (h) a read that fails while it runs; a start during it; a replaced file
# --------------------------------------------------------------------------- #
def test_a_start_during_the_re_read_does_not_release_the_latch_it_is_settling(reg, healthy, monkeypatch):
    hold = _Hold(monkeypatch)
    assert _fail(reg, healthy)
    assert hold.entered.wait(60)
    assert reg.retry(reason="the operator started collection") == [], "the claim is the pause until the answer is in"
    assert reg.latched(FILE_CORPUS)
    hold.release()
    _settled(reg)
    assert not reg.latched(FILE_CORPUS), "and the clean answer then ends it by itself"


def test_a_start_before_the_re_read_has_named_its_tables_does_not_release_the_latch(reg, healthy, monkeypatch):
    """The window between the latch and the table list: the claim exists, ``check_tables`` does not yet."""
    gate = threading.Event()
    real = verify.inspect_confirmed
    entered = threading.Event()

    def slow(path, **k):
        entered.set()
        assert gate.wait(60)
        return real(path, **k)

    monkeypatch.setattr(verify, "inspect_confirmed", slow)
    assert _fail(reg, healthy)
    assert entered.wait(60) and "check_tables" not in _file(reg)
    assert reg.retry(reason="start") == []
    gate.set()
    _settled(reg)
    assert not reg.latched(FILE_CORPUS)


def test_a_read_that_fails_while_the_re_read_runs_keeps_the_latch(reg, healthy, monkeypatch):
    hold = _Hold(monkeypatch)
    assert _fail(reg, healthy)
    assert hold.entered.wait(60)
    assert _fail(reg, healthy, "SELECT body FROM notes WHERE id = ?"), "another failed read lands meanwhile"
    hold.release()
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS), "a clean answer about the first table says nothing about the second failure"
    assert st["reread"]["result"] == REREAD_CLEAN_HELD and "auto_released" not in st and "check_tables" not in st
    assert reg.retry(reason="start") == [FILE_CORPUS], "the start releases it the E1 way, and the first failed read pauses it again"


def test_a_replaced_file_ends_the_claim_and_the_late_answer_is_dropped(reg, healthy, monkeypatch):
    hold = _Hold(monkeypatch)
    assert _fail(reg, healthy)
    assert hold.entered.wait(60)
    assert reg.retry(reason="a restore swapped the file", file_replaced=True) == [FILE_CORPUS]
    assert not reg.latched(FILE_CORPUS)
    hold.release()
    _join_rereads()
    st = _settled(reg)
    assert not reg.latched(FILE_CORPUS)
    assert "auto_released" not in st and "reread" not in st, "an answer about a file that no longer is settles nothing"


def test_a_read_that_lists_its_tables_after_the_file_was_replaced_and_latched_again_reads_nothing(reg, healthy, monkeypatch):
    """The window the claim's token exists for: the first read is still listing the file when a restore swaps it, the new file latches
    on a failed read that makes no claim of its own (no statement), and the first read then comes back with its table list. It must find
    no claim of its own: no table set on the new latch, no read, and no release of a file it never looked at."""
    gate = threading.Event()
    entered = threading.Event()
    real = verify.inspect_confirmed

    def slow(path, **k):
        entered.set()
        assert gate.wait(60)
        return real(path, **k)

    monkeypatch.setattr(verify, "inspect_confirmed", slow)
    reads: list[str] = []
    real_check = verify.check_table
    monkeypatch.setattr(verify, "check_table", lambda path, table, **kw: (reads.append(table), real_check(path, table, **kw))[1])
    assert _fail(reg, healthy)
    assert entered.wait(60)
    assert reg.retry(reason="a restore swapped the file", file_replaced=True) == [FILE_CORPUS]
    assert _fail(reg, healthy, None), "the replaced file fails a read of its own"
    assert reg.latched(FILE_CORPUS) and not _file(reg).get("rechecking")
    gate.set()
    _join_rereads()
    st = _file(reg)
    assert reg.latched(FILE_CORPUS), "the late first read releases nothing about a file it never read"
    assert "check_tables" not in st and not reads, "and names no table on the new latch and reads none"
    assert st["reread"]["why"] == "no-statement"


def test_no_claim_is_made_against_a_check_that_is_running(reg, healthy, monkeypatch):
    """The refusal is made where the claim is, not only where the thread would have started: a claim that existed for the instant between
    the two would be a pause with an owner nobody had started."""
    seen: list[object] = []
    real = verify.reread

    def spy(file_key, names, **k):
        seen.append(_file(reg, file_key).get("rechecking"))
        return real(file_key, names, **k)

    monkeypatch.setattr(verify, "reread", spy)
    reg.verification_arm("test")
    assert _fail(reg, healthy)
    assert all(rc is None for rc in seen), "the check is running: the latch carried no claim when the re-read was asked for"
    assert _file(reg)["reread"]["why"] == "check-running"


def test_a_table_that_could_not_be_read_keeps_the_latch_the_e1_way(reg, healthy, monkeypatch):
    unread = {"table": "articles", "verdict": damage.VERDICT_UNCHECKED, "seconds": 0.0, "detail": ["the file was busy"]}
    monkeypatch.setattr(verify, "check_table", lambda path, table, **k: dict(unread, table=table))
    assert _fail(reg, healthy)
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS) and st["reread"]["result"] == REREAD_UNREAD
    assert "check_tables" not in st and "auto_released" not in st
    assert reg.retry(reason="start") == [FILE_CORPUS], "a read that never comes back must not hold the operator's start for ever"


def test_a_failed_read_after_the_answer_makes_the_incident_unanswered_again(reg, healthy):
    assert _fail(reg, healthy)
    _settled(reg)
    [inc] = reg.state(detail=True)["incidents"]
    assert inc["superseded"] is True and inc["answered_by"] == REREAD_CLEAN, "the incident itself says what answered it"
    assert _fail(reg, healthy)
    [inc] = reg.state(detail=True)["incidents"]
    assert not inc.get("superseded") and inc["repeats"] == 1
    assert "answered_by" not in inc, "and nothing answers it any more"


def test_a_clean_re_read_answers_the_failed_read_it_was_made_for_and_not_an_earlier_unread_one(tmp_path, monkeypatch):
    """An operator's start releases an E1 latch unread, so its incident stays owed to the next start's check. A clean read of ANOTHER
    table, made for a later failed read, must not answer it."""
    now = [1_000_000.0]
    r = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json", clock=lambda: now[0], rereads=False)
    path = tmp_path / "corpus.db"
    _build_store(path)
    assert _fail(r, path, "SELECT title FROM articles WHERE id = ?") and r.latched(FILE_CORPUS)
    assert r.retry(reason="start") == [FILE_CORPUS], "released unread: nothing answered the first incident"
    now[0] += 120
    r.rereads = True
    monkeypatch.setattr(damage, "registry", r)
    verify._reset_for_tests()
    try:
        assert _fail(r, path, "SELECT body FROM notes WHERE id = ?")
        _settled(r)
    finally:
        verify._reset_for_tests()
    assert not r.latched(FILE_CORPUS)
    first, second = r.state(detail=True)["incidents"]
    assert second["superseded"] is True and not first.get("superseded"), "the earlier error is still owed a check"


def test_a_record_written_after_the_clean_release_is_born_answered(reg, healthy, monkeypatch):
    """A slow drive: the record thread is still writing when the re-read has already released the pause."""
    monkeypatch.setattr(damage, "RECORD_WAIT_S", 0.05)
    go = threading.Event()
    real = reg._record_new

    def held(*a, **k):
        assert go.wait(60)
        return real(*a, **k)

    monkeypatch.setattr(reg, "_record_new", held)
    assert _fail(reg, healthy)
    _settled(reg)
    assert not reg.latched(FILE_CORPUS) and reg.state(detail=True)["incidents"] == []
    go.set()
    end = time.monotonic() + 30
    while not reg.state(detail=True)["incidents"] and time.monotonic() < end:
        time.sleep(0.02)
    [inc] = reg.state(detail=True)["incidents"]
    assert inc["superseded"] is True and inc["answered_by"] == REREAD_CLEAN


def test_a_full_text_table_is_read_with_its_shadow_tables(reg, tmp_path, monkeypatch):
    path = tmp_path / "fts.db"
    _build_store(path, rows=200, fts=True)
    hold = _Hold(monkeypatch)
    hold.release()
    assert _fail(reg, path, "SELECT rowid FROM article_fts WHERE article_fts MATCH ?")
    st = _settled(reg)
    assert {"article_fts", "article_fts_data", "article_fts_idx", "article_fts_docsize", "article_fts_config"} <= set(hold.calls), hold.calls
    assert "articles" not in hold.calls and "notes" not in hold.calls
    assert not reg.latched(FILE_CORPUS) and st["reread"]["result"] == REREAD_CLEAN


def test_the_re_read_of_the_wiki_lane_reads_its_own_file(reg, tmp_path):
    lane = tmp_path / "wiki.db"
    _build_store(lane)
    assert _fail(reg, lane, key=FILE_WIKI)
    _settled(reg, FILE_WIKI)
    assert not reg.latched(FILE_WIKI)
    assert _file(reg, FILE_WIKI)["reread"]["result"] == REREAD_CLEAN


# --------------------------------------------------------------------------- #
#  (g) a closed connection still latches
# --------------------------------------------------------------------------- #
def test_a_closed_connection_handed_to_the_raw_driver_helper_still_latches_the_file(reg, healthy, monkeypatch):
    monkeypatch.setattr(reg, "rereads", False)  # the latch the test hands to the helper stays as latched
    eng = create_engine(f"sqlite:///{healthy}")
    damage.attach(eng, FILE_CORPUS)
    conn = eng.connect()
    conn.close()
    with pytest.raises(Exception):  # noqa: B017,PT011 - SQLAlchemy's ResourceClosedError: the handle cannot answer
        conn.connection  # noqa: B018
    assert damage.note_raw_driver_error(conn, _corrupt(), statement=READ) is False, "nothing to discard on a closed handle"
    assert reg.latched(FILE_CORPUS), "the error is latched against the attached file all the same"


# --------------------------------------------------------------------------- #
#  the words
# --------------------------------------------------------------------------- #
def test_the_two_new_sentences_say_why_and_what_a_start_does_and_are_in_twelve_locales():
    assert "read the same table or tables again" in damage.FRAME_REREADING and "ends by itself" in damage.FRAME_REREADING
    assert "stays paused" in damage.FRAME_STAYED and "The note above says how to try again" in damage.FRAME_STAYED
    # both are shown for any paused file (the Wikipedia and law files are not released by a start of collection): neither names an action
    # that belongs to one file's note, nor says "collection" is what is paused
    for frame in (damage.FRAME_REREADING, damage.FRAME_STAYED):
        assert "collection" not in frame.lower() and "starting collection" not in frame.lower()
    assert "{" not in damage.FRAME_REREADING and "{" not in damage.FRAME_STAYED
    for p in sorted((ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in (damage.FRAME_REREADING, damage.FRAME_STAYED):
            assert k in d, f"{p.name} lacks {k[:50]!r}"
            if p.name != "en.json":
                assert d[k] != k, f"{p.name}: untranslated {k[:50]!r}"


# --------------------------------------------------------------------------- #
#  the independent read's findings
# --------------------------------------------------------------------------- #
def _held_finding(reg, path, tables):
    """A check's finding for the corpus file lands (an earlier check's, held at the attempts cap)."""
    reg.verification_file_held(FILE_CORPUS, path=path, attempts=3, reason="the check was left unfinished", tables=tables)


@pytest.mark.parametrize("where", ["before-the-list", "while-reading"])
def test_a_checks_finding_that_lands_during_the_re_read_decides_the_latch_and_a_start_reads_its_table(reg, healthy, monkeypatch, where):
    """The block of the read: the re-read overwrote (or popped) the check's table set, and the start then released a latch whose
    measured table had never been read."""
    monkeypatch.setattr(verify, "_path_of", lambda key: healthy)
    if where == "before-the-list":
        gate, entered = threading.Event(), threading.Event()
        real = verify.inspect_confirmed

        def slow(path, **k):
            entered.set()
            assert gate.wait(60)
            return real(path, **k)

        monkeypatch.setattr(verify, "inspect_confirmed", slow)
        release = gate.set
    else:
        hold = _Hold(monkeypatch)
        entered, release = hold.entered, hold.release
    assert _fail(reg, healthy)
    assert entered.wait(60)
    _held_finding(reg, healthy, ["notes"])
    release()
    _join_rereads()
    st = _file(reg)
    assert reg.latched(FILE_CORPUS), "a clean read of the statement's table says nothing about the table the check measured"
    assert "notes" in st["check_tables"], "the check's table set stands"
    assert st["reread"]["why"] == "check-found" and not st.get("rechecking")
    assert reg.retry(reason="start") == [], "a start reads the check's table first, and the pause ends only when it reads clean"
    st = _settled(reg)
    assert not reg.latched(FILE_CORPUS), "and it reads clean (the file is healthy), which is what releases it"


def test_a_check_finding_replaces_the_stayed_sentence(reg, healthy):
    assert _fail(reg, healthy)
    _settled(reg)
    assert _fail(reg, healthy) and damage.FRAME_STAYED in _frames(reg)
    _held_finding(reg, healthy, ["notes"])
    assert damage.FRAME_STAYED not in _frames(reg), "a start now reads the check's tables, which the stayed sentence does not say"


def test_an_earlier_sessions_incident_count_is_not_a_read_that_failed_during_the_re_read(tmp_path, healthy, monkeypatch):
    """The record of an earlier session is read lazily, after the claim stored its count: its incidents joined the live count and the
    clean answer read as 'another read failed meanwhile', so the pause never ended by itself."""
    record = lambda: tmp_path / "database-damage.json"  # noqa: E731
    before = DamageRegistry(path_fn=record, rereads=False)
    for _ in range(3):
        assert _fail(before, healthy)
    before.flush_durable()
    r = DamageRegistry(path_fn=record, rereads=True)
    monkeypatch.setattr(damage, "registry", r)
    verify._reset_for_tests()
    try:
        assert _fail(r, healthy)
        st = _settled(r)
    finally:
        verify._reset_for_tests()
    assert st["reread"]["result"] == REREAD_CLEAN and not r.latched(FILE_CORPUS)
    assert r.state()["files"][FILE_CORPUS]["incidents"] == 4, "the counts still add up"


def test_a_table_list_that_reads_damaged_on_two_connections_is_recorded_as_damaged_not_as_no_re_read(reg, tmp_path, monkeypatch):
    path = tmp_path / "corpus.db"
    monkeypatch.setattr(verify, "_path_of", lambda key: path)
    _build_store(path)
    with open(path, "r+b") as f:
        f.seek(100)
        f.write(random.Random(5).randbytes(PAGE - 100))
    assert _fail(reg, path)
    st = _settled(reg)
    assert reg.latched(FILE_CORPUS)
    assert st["reread"]["result"] == REREAD_DAMAGED, "the re-read failed twice: that is a finding, not 'no re-read was made'"
    assert st["check_tables"] == [verify.SCHEMA_ENTRY], "so a start reads every table"
    assert reg.retry(reason="start") == [], "and does not release the latch unread"
    _settled(reg)
    assert reg.latched(FILE_CORPUS), "the start read the file again and the list still reads damaged"


def test_a_restore_over_an_unlatched_file_forgets_what_the_old_file_taught(reg, healthy):
    assert _fail(reg, healthy)
    st = _settled(reg)
    assert not reg.latched(FILE_CORPUS) and st["auto_released"]
    assert reg.retry(reason="a restore swapped the file", file_replaced=True) == []
    st = _file(reg)
    assert "auto_released" not in st and "reread" not in st
    assert _fail(reg, healthy)
    st = _settled(reg)
    assert st["reread"]["result"] == REREAD_CLEAN, "the new file's first failed read is re-read, not 'again' the old file's table"
    assert damage.FRAME_STAYED not in _frames(reg)


def test_the_failing_statements_own_thread_never_looks_at_the_data_file(reg, healthy, monkeypatch):
    seen: list[str] = []
    real = Path.stat

    def stat(self, *a, **k):
        if self == healthy:
            seen.append(threading.current_thread().name)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "stat", stat)
    caller = threading.current_thread().name
    assert _fail(reg, healthy)
    _settled(reg)
    _join_rereads()
    assert "oo-database-reread" in seen, "the re-read looked at the file, on its own thread"
    assert caller not in seen, "and the thread of the failing statement did not (its drive may be the failing one)"


def test_while_the_re_read_runs_the_page_says_only_that(reg, healthy, monkeypatch):
    hold = _Hold(monkeypatch)
    assert _fail(reg, healthy)
    assert hold.entered.wait(60)
    frames = _frames(reg)
    assert damage.FRAME_REREADING in frames
    assert damage.FRAME_DATA not in frames, "a start during the re-read does not try again, which the damage sentence would say"
    assert damage.FRAME_REPAIR_NEXT_START not in frames, "and nothing says the file is damaged before the re-read has"
    hold.release()
    _join_rereads()


@pytest.mark.parametrize("key, lane_frame", [(FILE_WIKI, damage.FRAME_WIKI), (FILE_LAW, damage.FRAME_LAW)])
def test_the_stayed_sentence_beside_a_lanes_note_names_no_action_that_is_not_the_lanes(reg, tmp_path, key, lane_frame):
    path = tmp_path / f"{key}.db"
    _build_store(path)
    assert _fail(reg, path, key=key)
    _settled(reg, key)
    assert _fail(reg, path, key=key)
    frames = [n["frame"] for n in reg.notes() if n["file"] == key]
    assert frames == [lane_frame, damage.FRAME_STAYED]
    assert "collection" not in damage.FRAME_STAYED.lower()
