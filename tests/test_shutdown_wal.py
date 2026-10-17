"""The end of the process writes the log back before it disposes the pool, and says so when it could not (the WAL thread, 17 Oct 2026).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FIELD CASE. The 10-10 session of the user's machine ended ``clean`` (the lifespan's teardown ran to its last line) and the next boot
found a 1,409,086,256-byte ``-wal``: 90.8 s of the 92.1 s unlock was its write-back. ``Engine.dispose()`` closes the connections that
are IN the pool; SQLite writes the log back and removes it only when the LAST connection on the file closes, so ONE connection a thread
still has checked out leaves all of it. Measured by ``harness/walshut.py`` (300 MiB, plain and encrypted): 100 % left with a straggler idle
and with a straggler inside a read, gone with every connection back in the pool.

WHAT IS PINNED. (1) The premise, as a test of its own: the disposal alone leaves the log with a straggler (if SQLite ever stops doing
that, this fails and the step is redundant). (2) The step empties the log with an idle straggler; with a straggler inside a read it
returns ``busy`` at once, WITHOUT the wait the connection factory's own 30 s timeout would cost, and leaves the log. Both on a plain and
on an encrypted store. (3) It opens nothing it should not (a locked or missing store), names a failure by CLASS and never raises.
(4) ``dispose_engine`` and the pool count say what they saw, with ``None`` and a reason where they cannot (never 0). (5) The sentinel
carries the log the disposal left and the previous-session text says so, ``clean`` or not, with a ``0`` as a fact and an absent key as
silence. (6) The lifespan runs the step after the storage guard stops and before the disposal, and hands the disposal's answer on.
"""

from __future__ import annotations

import ast
import contextlib
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from src.database import connect as connect_mod
from src.database import session as session_mod
from src.database import shutdown_checkpoint as sc
from src.monitoring import forensics, storage_events

_KEY = "a throwaway passphrase for the shutdown write-back test"
_TARGET = 1024 * 1024  # a log this big is a few hundred commits; the field's was 1.41 GB, the harness's 300 MiB
#: far under the 30 s busy timeout the connection factory gives a connection, which is what a step that WAITED for the reader would cost
_NOT_THE_FACTORY_TIMEOUT_S = 5.0


class Store:
    """A real store on a real file with its own QueuePool, so ``dispose()`` is the engine's own, and a reader pinning the log."""

    def __init__(self, db: Path, eng) -> None:
        self.db, self.eng = db, eng
        self.wal = Path(str(db) + "-wal")
        self.straggler = None

    def wal_bytes(self) -> int:
        return self.wal.stat().st_size if self.wal.exists() else 0

    def grow_log(self) -> None:
        """A reader pins the log (what a long read does), so no checkpoint can pass its mark and the ``-wal`` grows as it did in the field."""
        pin = self.eng.raw_connection()
        pin.cursor().execute("BEGIN")
        pin.cursor().execute("SELECT count(*) FROM t").fetchall()
        writer = self.eng.raw_connection()
        blob = b"x" * 4096
        while self.wal_bytes() < _TARGET:
            cur = writer.cursor()
            cur.execute("BEGIN")
            cur.executemany("INSERT INTO t (b) VALUES (?)", [(blob,)] * 100)
            writer.commit()
        writer.close()
        self.straggler = pin

    def straggler_idle(self) -> None:
        """The straggler's read ends; the connection stays checked out (a pass the scheduler's stop gave up on, between two statements)."""
        self.straggler.rollback()
        self.straggler.cursor().execute("SELECT 1").fetchall()
        self.straggler.rollback()

    def end(self) -> None:
        if self.straggler is not None:
            with contextlib.suppress(Exception):  # a test's clean-up
                self.straggler.close()
        self.eng.dispose()


@pytest.fixture(params=["plain", "encrypted"])
def store(request, tmp_path, monkeypatch):
    db = tmp_path / "shutdown-wal.db"
    if request.param == "encrypted":
        pytest.importorskip("sqlcipher3")
        conn = connect_mod.connect(db, key=_KEY, create_encrypted=True, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")  # the app sets it in session.py's connect event; this engine has none
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, b BLOB)")
        conn.commit()
        conn.close()
        monkeypatch.setattr(connect_mod, "_passphrase", _KEY)  # what the app holds once it is unlocked
        assert connect_mod.is_encrypted_file(db) is True
    else:
        conn = connect_mod.connect(db, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, b BLOB)")
        conn.commit()
        conn.close()
        assert connect_mod.is_encrypted_file(db) is False
    eng = create_engine(
        f"sqlite:///{db}",
        creator=lambda: connect_mod.connect(db, check_same_thread=False),
        poolclass=QueuePool,
        pool_size=4,
        max_overflow=0,
    )
    s = Store(db, eng)
    yield s
    s.end()


@pytest.fixture()
def journal(monkeypatch):
    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(storage_events, "note_checkpoint", lambda trigger, **kw: seen.append((trigger, kw)))
    return seen


# --------------------------------------------------------------------------- #
#  (1) + (2) the log, with a straggler
# --------------------------------------------------------------------------- #


def test_the_disposal_alone_leaves_the_whole_log_with_one_connection_still_checked_out(store):
    """THE PREMISE. Negative twin of the next test: without the step, today's shutdown leaves everything."""
    store.grow_log()
    store.straggler_idle()
    before = store.wal_bytes()
    assert before >= _TARGET, "ANTI-VACUITY: no log to leave"
    store.eng.dispose()  # what dispose_engine() does
    assert store.wal_bytes() == before, f"the disposal wrote {before - store.wal_bytes()} bytes back; if SQLite does that now, the step is redundant"


def test_the_step_writes_the_log_back_with_an_idle_straggler_and_the_disposal_then_leaves_none(store, journal):
    store.grow_log()
    store.straggler_idle()
    before = store.wal_bytes()
    assert before >= _TARGET
    out = sc.checkpoint_before_dispose(store.db)
    assert out["outcome"] == "done", out
    assert out["truncate"][0] == 0, "no reader held the log"
    assert out["wal_bytes_before"] == before and out["wal_bytes_after"] == 0, out
    store.eng.dispose()
    assert store.wal_bytes() == 0, "the log came back"
    assert [t for t, _ in journal] == ["shutdown"], "it is recorded in the storage journal under its own trigger"
    kw = journal[0][1]
    assert kw["outcome"] == "done" and kw["wal_before"] == before and kw["wal_after"] == 0


def test_a_straggler_inside_a_read_leaves_the_log_and_the_step_says_busy_without_waiting(store, journal):
    store.grow_log()  # the pinning reader IS the straggler and is still inside its read
    before = store.wal_bytes()
    assert before >= _TARGET
    began = time.monotonic()
    out = sc.checkpoint_before_dispose(store.db)
    waited = time.monotonic() - began
    assert out["outcome"] == "busy" and out["truncate"][0] != 0, out
    assert waited < _NOT_THE_FACTORY_TIMEOUT_S, f"the step waited {waited:.1f} s for a reader: it must report busy at once"
    assert store.wal_bytes() == before, "a busy checkpoint wrote something back or truncated"
    assert journal and journal[0][1]["truncate"][0] != 0, "the busy answer is what the journal gets"


# --------------------------------------------------------------------------- #
#  (3) what it opens, and what it says when it fails
# --------------------------------------------------------------------------- #


def test_a_store_this_process_never_opened_is_not_opened(tmp_path, monkeypatch, journal):
    db = tmp_path / "locked.db"
    db.write_bytes(b"x" * 4096)  # the content does not matter: the lock state decides
    monkeypatch.setattr(connect_mod, "locked_state", lambda _p: "locked")

    def never(*_a, **_k):
        raise AssertionError("a locked store was opened")

    monkeypatch.setattr(connect_mod, "connect", never)
    out = sc.checkpoint_before_dispose(db)
    assert out["outcome"] == "skipped" and "locked" in out["why"], out
    assert journal[0][1]["outcome"] == "skipped" and journal[0][1]["extra"] == {"why": out["why"]}


def test_a_missing_database_file_is_skipped_and_not_created(tmp_path, journal):
    db = tmp_path / "nothing-here.db"
    out = sc.checkpoint_before_dispose(db)
    assert out["outcome"] == "skipped" and not db.exists() and not Path(str(db) + "-wal").exists(), out


def test_a_failure_is_named_by_class_only_and_never_raises(store, monkeypatch, journal, caplog):
    secret = "words of the engine that quote what it was handed"

    def boom(*_a, **_k):
        raise RuntimeError(secret)

    monkeypatch.setattr(connect_mod, "connect", boom)
    with caplog.at_level("DEBUG"):
        out = sc.checkpoint_before_dispose(store.db)
    assert out["outcome"] == "failed" and out["error"] == "RuntimeError", out
    assert secret not in repr(out) and secret not in caplog.text and secret not in repr(journal), "the engine's words reached a record"
    assert journal[0][1]["outcome"] == "failed" and journal[0][1]["error"] == "RuntimeError"


# --------------------------------------------------------------------------- #
#  (4) what the disposal and the pool count say
# --------------------------------------------------------------------------- #


def test_the_pool_count_is_the_pools_own_and_says_why_when_it_has_none(store, monkeypatch):
    assert session_mod.pool_checkouts(store.eng) == {"checked_out": 0}
    store.grow_log()
    assert session_mod.pool_checkouts(store.eng) == {"checked_out": 1}, "the pinning reader is the one connection still out"

    class NoCount:
        pass

    class Eng:
        pool = NoCount()

    none = session_mod.pool_checkouts(Eng())
    assert none["checked_out"] is None and "NoCount has no checkedout()" in none["checked_out_why"], none

    class Broken:
        def checkedout(self):
            raise ValueError("secret words")

    class Eng2:
        pool = Broken()

    broken = session_mod.pool_checkouts(Eng2())
    assert broken["checked_out"] is None and "ValueError" in broken["checked_out_why"] and "secret" not in broken["checked_out_why"], broken


def test_dispose_engine_returns_what_the_pool_held_just_before_it_and_still_disposes(store, monkeypatch):
    monkeypatch.setattr(session_mod, "engine", store.eng)
    store.grow_log()  # one connection out
    idle = store.eng.raw_connection()
    idle.close()  # and one back in the pool
    assert store.eng.pool.checkedin() >= 1
    seen = session_mod.dispose_engine()
    assert seen == {"checked_out": 1}, seen
    assert store.eng.pool.checkedin() == 0, "the pool's idle connections were closed"


# --------------------------------------------------------------------------- #
#  (5) the sentinel and the text
# --------------------------------------------------------------------------- #


@pytest.fixture()
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    monkeypatch.setattr(forensics, "_WAL_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_STOP_SIGNAL", None)
    return tmp_path


def _wal(dd, nbytes: int | None) -> None:
    p = dd / f"{forensics._DB_NAME}-wal"
    if nbytes is None:
        p.unlink(missing_ok=True)
    else:
        p.write_bytes(b"\0" * nbytes)


def _next_boot() -> dict:
    forensics._PREV_LOADED = False
    forensics._PREV_AT_BOOT = None
    forensics.record_session_start()
    return forensics.previous_session_report()


def test_dispose_facts_read_the_log_now_and_never_turn_unknown_into_zero(dd):
    _wal(dd, 1234)
    f = forensics.dispose_facts({"checked_out": 3}, {"outcome": "busy"})
    assert f == {"wal_bytes_after_dispose": 1234, "connections_checked_out_at_dispose": 3, "shutdown_checkpoint": "busy"}, f
    _wal(dd, None)
    assert forensics.dispose_facts({"checked_out": 0}, {"outcome": "done"})["wal_bytes_after_dispose"] == 0, "no file is a log of 0 bytes"
    unknown = forensics.dispose_facts({"checked_out": None, "checked_out_why": "Q has no checkedout()"}, None)
    assert unknown["connections_checked_out_at_dispose"] is None and unknown["checked_out_why"] == "Q has no checkedout()"
    assert unknown["shutdown_checkpoint"] is None and "did not run" in unknown["shutdown_checkpoint_why"]
    failed = forensics.dispose_facts(None, {"outcome": "failed", "error": "OperationalError"})
    assert failed["shutdown_checkpoint"] == "failed" and failed["shutdown_checkpoint_why"] == "OperationalError"
    assert failed["connections_checked_out_at_dispose"] is None and failed["checked_out_why"] == "the pool was not asked"


def test_the_first_phase_stamps_the_teardowns_start_once_and_only_known_facts_are_kept(dd):
    forensics.record_session_start()
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    first = forensics._read_state()["shutdown_began_at"]
    time.sleep(1.1)  # the stamp has whole-second resolution
    forensics.record_shutdown_phase("dispose-done", facts={"wal_bytes_after_dispose": 7, "a_passphrase": "no"})
    state = forensics._read_state()
    assert state["shutdown_began_at"] == first, "stamped once, on the first phase"
    assert state["shutdown_phase_at"] > first
    assert state["wal_bytes_after_dispose"] == 7 and "a_passphrase" not in state


def test_a_clean_end_that_left_a_log_never_reads_as_a_clean_log(dd):
    _wal(dd, 4_000_000)
    forensics.record_session_start()
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    forensics.record_shutdown_phase("dispose-done", facts=forensics.dispose_facts({"checked_out": 2}, {"outcome": "busy"}))
    forensics.record_clean_shutdown()
    rep = _next_boot()
    assert rep["previous_session"] == "clean", "the sentinel's word is what it was: the teardown ran"
    assert rep["wal_bytes_after_dispose"] == 4_000_000 and rep["connections_checked_out_at_dispose"] == 2
    text = forensics.render_text({"previous_session": rep})
    assert "- ended: clean" in text
    assert "the -wal was LEFT by that session's end: 4,000,000 bytes" in text and "2 connection(s) still checked out" in text, text
    assert "the write-back before it: busy" in text and "not that this log was written back" in text
    assert "teardown began at:" in text and "to the end" in text, "the teardown's duration is readable now"


def test_a_log_of_zero_is_a_fact_and_an_unrecorded_value_is_silence(dd):
    _wal(dd, None)
    forensics.record_session_start()
    forensics.record_shutdown_phase("dispose-done", facts=forensics.dispose_facts({"checked_out": 0}, {"outcome": "done"}))
    forensics.record_clean_shutdown()
    rep = _next_boot()
    assert rep["wal_bytes_after_dispose"] == 0, "0 is carried, not dropped as falsy"
    assert "the -wal was empty after that session's pool was disposed" in forensics.render_text({"previous_session": rep})
    # a sentinel written by a build before this one has none of the keys: nothing is said, in particular not "empty"
    old = {"previous_session": "clean", "started_at": "2026-10-10T00:00:00+00:00", "ended_at": "2026-10-10T06:37:36+00:00"}
    assert "disposal" not in forensics.render_text({"previous_session": old}) and "LEFT" not in forensics.render_text({"previous_session": old})


def test_an_unreadable_log_is_not_called_empty(dd):
    forensics.record_session_start()
    forensics.record_shutdown_phase("dispose-done", facts={"wal_bytes_after_dispose": None, "wal_after_dispose_why": "the -wal's size could not be read"})
    forensics.record_clean_shutdown()
    rep = _next_boot()
    text = forensics.render_text({"previous_session": rep})
    assert "was not measured (the -wal's size could not be read" in text and "was empty" not in text, text


# --------------------------------------------------------------------------- #
#  (6) the wiring
# --------------------------------------------------------------------------- #


def test_the_lifespan_writes_the_log_back_after_the_guard_stops_and_before_the_disposal_and_hands_the_answer_on():
    """Read from the parse tree (a comment quoting a call name cannot satisfy it), in the form of ``tests/test_database_verify.py``."""
    tree = ast.parse(Path("src/api/main.py").read_text(encoding="utf-8"))
    [life] = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"]
    yield_line = next(n.lineno for n in ast.walk(life) if isinstance(n, ast.Yield))
    calls = [n for n in ast.walk(life) if isinstance(n, ast.Call) and n.lineno > yield_line]

    def lines(name: str) -> list[int]:
        return [c.lineno for c in calls if (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == name]

    guard, step, dispose = lines("_stop_storage_guard"), lines("checkpoint_before_dispose"), lines("dispose_engine")
    assert guard and step and dispose, (guard, step, dispose)
    assert guard[0] < step[0] < dispose[0], "the write-back goes after the storage guard stops and before the pool is disposed"
    [stamp] = [c for c in calls if getattr(c.func, "id", None) == "record_shutdown_phase" and c.args and getattr(c.args[0], "value", None) == "dispose-done"]
    facts = next(k.value for k in stamp.keywords if k.arg == "facts")
    assert isinstance(facts, ast.Call) and getattr(facts.func, "id", None) == "dispose_facts", "the dispose phase carries dispose_facts(...)"
    assert [getattr(a, "id", None) for a in facts.args] == ["disposed", "shutdown_checkpoint"], "the disposal's answer and the step's are what it is built from"
