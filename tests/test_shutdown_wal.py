"""The end of the process writes the log back before it disposes the pool, and says so when it could not (the WAL thread, 17 Oct 2026).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FIELD CASE. The 10-10 session of the user's machine ended ``clean`` (the lifespan's teardown ran to its last line) and the next boot
found a 1,409,086,256-byte ``-wal``: 90.8 s of the 92.1 s unlock was its write-back. ``Engine.dispose()`` closes the connections that
are IN the pool; SQLite writes the log back and removes it only when the LAST connection on the file closes, so ONE connection a thread
still has checked out leaves all of it. Measured by ``harness/walshut.py`` (300 MiB, plain and encrypted): 100 % left with a straggler idle
and with a straggler inside a read, gone with every connection back in the pool.

WHAT IS PINNED. (1) The premise, as a test of its own: the disposal alone leaves the log with a straggler (if SQLite ever stops doing
that, this fails and the step is redundant). (2) The step empties the log with an idle straggler. With a straggler inside a read it
answers ``busy`` WITHOUT the wait the connection factory's own 30 s timeout would cost, in shapes that depend on where the reader's
snapshot lies: older than every frame (only the frames up to its mark are copied, the log is as it was) and newer than the frames (every
frame is copied, the answer is still ``busy``, the file keeps its size and the straggler's close then removes it); a WRITER caught mid-write
answers like the second, and the record cannot tell the two apart. All on a plain and on an encrypted store. (3) It opens nothing it should not (a locked or missing store), names a failure by CLASS, never raises, and holds the
library swap lock across the whole step: a swap that arrives mid-step is refused with ``LibraryBusy`` and a step that arrives mid-swap
waits. (4) ``dispose_engine`` and the pool count say what they saw, with ``None`` and a reason where they cannot (never 0), including
after an EARLIER disposal replaced the pool. (5) The sentinel carries the log the disposal left as ONE ``dispose`` record and the
previous-session text says so, ``clean`` or not, with a ``0`` as a fact and an absent key as silence. (6) The lifespan stamps the
write-back phase and runs the step after the storage guard stops and before the disposal, and hands the disposal's answer on.
"""

from __future__ import annotations

import ast
import contextlib
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from src.database import connect as connect_mod
from src.database import library_generation as lg
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

    def _start_read(self):
        pin = self.eng.raw_connection()
        pin.cursor().execute("BEGIN")
        pin.cursor().execute("SELECT count(*) FROM t").fetchall()
        return pin

    def grow_log(self, *, reader_after_writes: bool = False) -> None:
        """A reader pins the log (what a long read does), so no checkpoint can pass its mark and the ``-wal`` grows as it did in the field.

        By default the reader's snapshot is OLDER than every frame (it began before the writes). With ``reader_after_writes`` the writes come
        first, with nothing folding the log behind the test's back, and the reader begins its read after them: its snapshot is at the END of
        the log, which is what a scheduler pass that began its read recently looks like (the Opus read of 26 Oct found the step's answer
        differs between the two)."""
        pin = None if reader_after_writes else self._start_read()
        writer = self.eng.raw_connection()
        writer.cursor().execute("PRAGMA wal_autocheckpoint=0")
        blob = b"x" * 4096
        while self.wal_bytes() < _TARGET:
            cur = writer.cursor()
            cur.execute("BEGIN")
            cur.executemany("INSERT INTO t (b) VALUES (?)", [(blob,)] * 100)
            writer.commit()
        writer.close()
        self.straggler = pin if pin is not None else self._start_read()

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


def test_a_reader_whose_snapshot_predates_the_log_makes_the_step_say_busy_at_once_with_only_its_own_frames_written_back(store, journal):
    """SHAPE A. The reader began before the writes, so only the frames up to its mark are safe to copy: the answer is instant, the checkpointed
    count is far under the log's, and the log is as it was."""
    store.grow_log()  # the pinning reader IS the straggler, inside its read, and its snapshot is older than every frame
    before = store.wal_bytes()
    assert before >= _TARGET
    began = time.monotonic()
    out = sc.checkpoint_before_dispose(store.db)
    waited = time.monotonic() - began
    assert out["outcome"] == "busy" and out["truncate"][0] != 0, out
    assert waited < _NOT_THE_FACTORY_TIMEOUT_S, f"the step waited {waited:.1f} s for a reader: it must not wait for one"
    assert out["truncate"][1] > out["truncate"][2], f"frames were written back though the reader's snapshot predates them: {out['truncate']}"
    assert out["copied_all"] is False, out
    assert store.wal_bytes() == before, "a busy checkpoint wrote something back or truncated"
    assert journal and journal[0][1]["truncate"][0] != 0, "the busy answer is what the journal gets"


def test_a_reader_whose_snapshot_is_newer_than_the_log_gets_the_whole_log_written_back_and_the_answer_is_still_busy(store, journal):
    """SHAPE B, the common one (a pass that began its read after the writes), and the one the first version of this module's text got wrong:
    TRUNCATE copies the frames up to the reader's snapshot, which here is every frame, BEFORE it finds the reader, so the whole write-back runs
    and only then comes ``busy``; the file keeps its size. The record has to tell this from shape A, and the straggler's close then has
    nothing left to copy."""
    store.grow_log(reader_after_writes=True)
    before = store.wal_bytes()
    assert before >= _TARGET, "ANTI-VACUITY: no log to write back"
    out = sc.checkpoint_before_dispose(store.db)
    assert out["outcome"] == "busy" and out["truncate"][0] != 0, out
    log, copied = out["truncate"][1], out["truncate"][2]
    assert log > 0 and copied == log, f"every frame must have been written back though the answer is busy: {out['truncate']}"
    assert out["copied_all"] is True, out
    assert store.wal_bytes() == before, "the file keeps its size: a busy TRUNCATE does not truncate"
    # what the disposal's facts record, and the words they print
    facts = forensics.dispose_facts({"checked_out": 1}, out)["dispose"]
    assert facts["step"] == "copied", facts
    assert "every frame was written back" in forensics.DISPOSE_STEP_WORDS[facts["step"]]
    # the straggler's close is the last connection on the file: nothing is left to copy and the log goes
    store.straggler.close()
    store.straggler = None
    store.eng.dispose()
    assert store.wal_bytes() == 0, "the last close should have removed a log that was already written back"


def test_a_writer_caught_mid_write_answers_like_a_recent_reader_so_copied_does_not_mean_nothing_is_left(store, journal):
    """SHAPE C (the delta read of 26 Oct). The scheduler's stop gives up on a pass that is INSIDE a write transaction: TRUNCATE then falls back to
    a passive checkpoint, copies every committed frame and answers ``(1, n, n)``, exactly as it does for a reader whose snapshot is newer than
    the frames. The row cannot tell the two apart, so the record says ``copied`` for both, its words must not blame a reader alone, and the
    writer's own commit afterwards puts frames in the log that this step never wrote back."""
    store.grow_log(reader_after_writes=True)
    store.straggler_idle()  # no reader: the only thing holding the log is the writer below
    before = store.wal_bytes()
    assert before >= _TARGET, "ANTI-VACUITY: no log to write back"
    writer = store.eng.raw_connection()
    try:
        cur = writer.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("INSERT INTO t (b) VALUES (?)", (b"y" * 4096,))
        out = sc.checkpoint_before_dispose(store.db)
        assert out["outcome"] == "busy" and out["truncate"][0] != 0, out
        log, copied = out["truncate"][1], out["truncate"][2]
        assert log > 0 and copied == log, f"a busy writer lock must not stop the committed frames being copied: {out['truncate']}"
        assert out["copied_all"] is True, out
        assert store.wal_bytes() == before, "the file keeps its size: a busy TRUNCATE does not truncate"
        writer.commit()
        assert store.wal_bytes() > before, "ANTI-VACUITY: the writer's commit put no frame in the log, so there is nothing the step did not write back"
    finally:
        writer.close()
    step = forensics.dispose_facts({"checked_out": 1}, out)["dispose"]["step"]
    words = forensics.DISPOSE_STEP_WORDS[step]
    assert step == "copied" and "a reader" in words and "a writer in the middle of a write" in words, (
        f"the words for a row both a reader and a writer give must name both as the holder: {words}"
    )


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


class _Answers:
    """A stand-in for the step's connection that answers the checkpoint with a row of the test's choosing."""

    def __init__(self, row) -> None:
        self._row = row

    def execute(self, sql, *args):
        row = self._row if "wal_checkpoint" in sql else None
        return type("R", (), {"fetchone": lambda _self: row})()

    def close(self):
        return None


@pytest.mark.parametrize(
    ("row", "outcome", "copied_all", "step"),
    [
        ((0, 5, 5), "done", None, "done"),
        ((1, 7, 7), "busy", True, "copied"),  # a snapshot newer than the frames, or a writer mid-write: every frame written back, the log still held
        ((1, 7, 3), "busy", False, "busy"),  # a snapshot older than the frames: not all of it
        ((1, -1, -1), "busy", False, "busy"),  # the CHECKPOINT lock itself was busy (another checkpoint): this step copied nothing, the answer is silent on the rest
        ((1, 0, 0), "busy", False, "busy"),  # an empty log answered busy: there was nothing to copy, so it was not "all copied"
    ],
)
def test_the_answer_of_the_checkpoint_is_read_into_outcome_and_copied_all(store, monkeypatch, journal, row, outcome, copied_all, step):
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: _Answers(row))
    out = sc.checkpoint_before_dispose(store.db)
    assert (out["outcome"], out["copied_all"], out["truncate"]) == (outcome, copied_all, list(row)), out
    assert forensics.dispose_facts({"checked_out": 0}, out)["dispose"]["step"] == step


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


class _HeldAtCheckpoint:
    """A stand-in for the step's connection that stops at the checkpoint until the test lets it go, so the step is provably MID-STEP."""

    def __init__(self, conn, at_checkpoint: threading.Event, let_go: threading.Event) -> None:
        self._c, self._at, self._go = conn, at_checkpoint, let_go

    def execute(self, sql, *args):
        if "wal_checkpoint" in sql:
            self._at.set()
            assert self._go.wait(30), "the test never let the step go"
        return self._c.execute(sql, *args)

    def close(self):
        return self._c.close()


class _HeldAtClose:
    """A stand-in for the step's connection that stops at ITS CLOSE until the test lets it go. The close is the hazard the swap lock is for: as
    the last connection on the old file it removes the ``-wal`` and ``-shm`` BY NAME."""

    def __init__(self, conn, at_close: threading.Event, let_go: threading.Event) -> None:
        self._c, self._at, self._go = conn, at_close, let_go

    def execute(self, sql, *args):
        return self._c.execute(sql, *args)

    def close(self):
        self._at.set()
        assert self._go.wait(30), "the test never let the step go"
        return self._c.close()


def _run_step_in_a_thread(db: Path) -> tuple[threading.Thread, dict]:
    result: dict = {}
    t = threading.Thread(target=lambda: result.update(out=sc.checkpoint_before_dispose(db)), daemon=True)
    t.start()
    return t, result


def test_a_swap_that_arrives_in_the_middle_of_the_step_is_refused_and_the_file_is_not_switched(store, monkeypatch, tmp_path):
    """M1 of the 26 Oct read. The step's connection is raw: the pool's stamp never reaches it and nothing refuses it, so the library swap lock
    is what keeps a restore from replacing the file while it is open (its last close would remove the NEW file's log by name)."""
    at_checkpoint, let_go = threading.Event(), threading.Event()
    real = connect_mod.connect
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: _HeldAtCheckpoint(real(*a, **k), at_checkpoint, let_go))
    thread, result = _run_step_in_a_thread(store.db)
    try:
        assert at_checkpoint.wait(30), "the step never reached its checkpoint"
        generation = lg.current()
        incoming = tmp_path / "incoming.db"
        incoming.write_bytes(b"a library about to be switched in")
        with pytest.raises(lg.LibraryBusy), lg.swap_window(incoming, timeout=0.2):
            pytest.fail("the swap window was granted while the step had the file open")
        assert lg.current() == generation, "the generation moved though the swap was refused"
        assert incoming.exists(), "the refused swap must leave the incoming file where it was"
    finally:
        let_go.set()
        thread.join(30)
    assert result["out"]["outcome"] in ("done", "busy"), result
    with lg.swap_window(tmp_path / "later.db"):  # the lock is given back: a swap after the step gets its window at once
        pass


def test_a_swap_that_arrives_while_the_step_is_closing_its_connection_is_refused(store, monkeypatch, tmp_path):
    """The delta read of 26 Oct: the test above stops the step at its checkpoint, so a later edit that moved ``conn.close()`` out of the lock
    passed it. The close is where the last connection on the file removes the log by name, so the lock must still be held there."""
    at_close, let_go = threading.Event(), threading.Event()
    real = connect_mod.connect
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: _HeldAtClose(real(*a, **k), at_close, let_go))
    thread, result = _run_step_in_a_thread(store.db)
    try:
        assert at_close.wait(30), "the step never reached its close"
        generation = lg.current()
        incoming = tmp_path / "incoming.db"
        incoming.write_bytes(b"a library about to be switched in")
        with pytest.raises(lg.LibraryBusy), lg.swap_window(incoming, timeout=0.2):
            pytest.fail("the swap window was granted while the step's connection was still open")
        assert lg.current() == generation, "the generation moved though the swap was refused"
        assert incoming.exists(), "the refused swap must leave the incoming file where it was"
    finally:
        let_go.set()
        thread.join(30)
    assert result["out"]["outcome"] in ("done", "busy"), result
    with lg.swap_window(tmp_path / "later.db"):  # given back once the connection is closed
        pass


def test_a_step_that_arrives_in_the_middle_of_a_swap_waits_for_it(store, monkeypatch, tmp_path):
    opened = threading.Event()
    real = connect_mod.connect

    def spy(*a, **k):
        opened.set()
        return real(*a, **k)

    monkeypatch.setattr(connect_mod, "connect", spy)
    incoming = tmp_path / "incoming.db"
    incoming.write_bytes(b"x")
    with lg.swap_window(incoming):
        thread, result = _run_step_in_a_thread(store.db)
        assert not opened.wait(0.5), "the step opened a connection while a swap held the window"
    assert opened.wait(30), "the step never ran once the window was released"
    thread.join(30)
    assert result["out"]["outcome"] in ("done", "busy"), result


def test_the_step_reads_the_file_the_creator_opens_and_declines_off_sqlite(tmp_path, monkeypatch, journal):
    """L4 of the 26 Oct read: one source for the path (``session.DB_FILE``, the creator's own string), and a backend check."""
    monkeypatch.setattr(session_mod, "DB_FILE", None)
    out = sc.checkpoint_before_dispose()
    assert out["outcome"] == "skipped" and out["why"] == "not sqlite", out
    monkeypatch.setattr(session_mod, "DB_FILE", ":memory:")
    assert sc.checkpoint_before_dispose()["why"] == "no file"
    odd = tmp_path / "a%20b" / "lib?x.db"  # SQLAlchemy would un-escape the % and cut at the ?: the creator opens the string as written
    odd.parent.mkdir()
    odd.write_bytes(b"x" * 4096)
    monkeypatch.setattr(session_mod, "DB_FILE", str(odd))
    monkeypatch.setattr(connect_mod, "locked_state", lambda p: "locked" if Path(p) == odd else "unlocked-plaintext")
    out = sc.checkpoint_before_dispose()
    assert out["why"] == "locked" and out["wal_path"] == str(odd) + "-wal", out


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
    monkeypatch.setattr(session_mod, "_LEFT_BEHIND", 0)  # the module remembers earlier disposals; this test is the first
    store.grow_log()  # one connection out
    idle = store.eng.raw_connection()
    idle.close()  # and one back in the pool
    assert store.eng.pool.checkedin() >= 1
    seen = session_mod.dispose_engine()
    assert seen == {"checked_out": 1}, seen
    assert store.eng.pool.checkedin() == 0, "the pool's idle connections were closed"


def test_a_disposal_after_one_that_left_connections_out_says_it_cannot_count(store, monkeypatch):
    """M2 of the 26 Oct read. The in-app power button disposes BEFORE it signals the process; ``Engine.dispose()`` swaps in a new pool, so a
    connection checked out at that moment belongs to the old one and the lifespan's later count read ``0`` while it was still open."""
    monkeypatch.setattr(session_mod, "engine", store.eng)
    monkeypatch.setattr(session_mod, "_LEFT_BEHIND", 0)
    store.grow_log()  # one connection out (the straggler)
    first = session_mod.dispose_engine()
    assert first == {"checked_out": 1}, first
    assert session_mod.pool_checkouts(store.eng) == {"checked_out": 0}, "ANTI-VACUITY: the new pool really does read 0 while the straggler is open"
    second = session_mod.dispose_engine()
    assert second == {"checked_out": None, "checked_out_why": session_mod.EARLIER_DISPOSAL}, second
    facts = forensics.dispose_facts(second, {"outcome": "busy", "copied_all": False, "wal_path": str(store.wal)})["dispose"]
    assert facts["out"] == "earlier", facts
    assert forensics.DISPOSE_OUT_WORDS["earlier"] == "an earlier disposal replaced the pool"


def test_a_disposal_after_one_that_held_nothing_is_counted_as_before(store, monkeypatch):
    monkeypatch.setattr(session_mod, "engine", store.eng)
    monkeypatch.setattr(session_mod, "_LEFT_BEHIND", 0)
    assert session_mod.dispose_engine() == {"checked_out": 0}
    store.grow_log()
    assert session_mod.dispose_engine() == {"checked_out": 1}, "nothing was left behind by the first, so the second's count is the whole truth"
    assert session_mod.dispose_engine()["checked_out"] is None, "and now one was left behind"
    monkeypatch.setattr(session_mod, "_LEFT_BEHIND", None)  # an earlier disposal that could not count at all
    assert session_mod.dispose_engine()["checked_out_why"] == session_mod.EARLIER_DISPOSAL


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
    assert f == {"dispose": {"wal": 1234, "out": 3, "step": "busy"}}, f
    _wal(dd, None)
    assert forensics.dispose_facts({"checked_out": 0}, {"outcome": "done"})["dispose"]["wal"] == 0, "no file is a log of 0 bytes"
    unknown = forensics.dispose_facts({"checked_out": None, "checked_out_why": "Q has no checkedout()"}, None)["dispose"]
    assert unknown["out"] == "unknown" and unknown["step"] == "not run", "an unknown is a CODE in place of the number, never 0"
    failed = forensics.dispose_facts(None, {"outcome": "failed", "error": "OperationalError"})["dispose"]
    assert failed["step"] == "failed" and failed["out"] == "unasked"
    for why, code in (("locked", "locked"), ("fresh", "fresh"), ("not sqlite", "no db"), ("no file", "no db")):
        got = forensics.dispose_facts({"checked_out": 0}, {"outcome": "skipped", "why": why})["dispose"]
        assert got["step"] == code, (why, got)
    # every code the facts can carry has its words
    assert set(forensics.DISPOSE_OUT_WORDS) == {"earlier", "unknown", "unasked"} and set(forensics.DISPOSE_WAL_WORDS) == {"unreadable"}
    assert set(forensics.DISPOSE_STEP_WORDS) == {"done", "busy", "copied", "failed", "locked", "fresh", "no db", "not run", "unknown"}


def test_the_facts_read_the_log_of_the_file_the_step_looked_at(dd, tmp_path):
    """L4: the data folder's log is not the one a ``DATABASE_URL`` elsewhere writes."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "lib.db-wal").write_bytes(b"\0" * 777)
    _wal(dd, 5)
    f = forensics.dispose_facts({"checked_out": 0}, {"outcome": "done", "wal_path": str(elsewhere / "lib.db-wal")})
    assert f["dispose"]["wal"] == 777, f
    assert forensics.dispose_facts({"checked_out": 0}, {"outcome": "done"})["dispose"]["wal"] == 5, "without a path it is the data folder's own"


def test_the_first_phase_stamps_the_teardowns_start_once_and_only_known_facts_are_kept(dd):
    forensics.record_session_start()
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    first = forensics._read_state()["shutdown_began_at"]
    time.sleep(1.1)  # the stamp has whole-second resolution
    forensics.record_shutdown_phase("dispose-done", facts={"dispose": {"wal": 7, "out": 0, "step": "done"}, "a_passphrase": "no"})
    state = forensics._read_state()
    assert state["shutdown_began_at"] == first, "stamped once, on the first phase"
    assert state["shutdown_phase_at"] > first
    assert state["dispose"] == {"wal": 7, "out": 0, "step": "done"} and "a_passphrase" not in state


def test_a_death_inside_the_write_back_is_its_own_verdict(dd):
    """L5: the step can take as long as a service manager's stop timeout, so a death inside it must not read as a death during shutdown."""
    forensics.record_session_start()
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    forensics.record_shutdown_phase("writing-back")
    assert _next_boot()["previous_session"] == "unclean-end-during-write-back"
    from src.monitoring import session_history as sh

    sh._reset_for_tests()
    try:
        rec = sh._seed_pre_ledger(
            {"state": "writing-back", "started_at": "2026-10-26T05:00:00+00:00", "shutdown_phase_at": "2026-10-26T06:00:00+00:00", "pid": 1}
        )
    finally:
        sh._reset_for_tests()
    assert rec is not None and rec["clean"] is False and rec["at"] == "2026-10-26T06:00:00Z", rec
    assert "died during its own shutdown" in rec["basis"], rec


def test_a_clean_end_that_left_a_log_never_reads_as_a_clean_log(dd):
    _wal(dd, 4_000_000)
    forensics.record_session_start()
    forensics.record_shutdown_phase("shutting-down", reason="lifespan shutdown")
    forensics.record_shutdown_phase("dispose-done", facts=forensics.dispose_facts({"checked_out": 2}, {"outcome": "busy"}))
    forensics.record_clean_shutdown()
    rep = _next_boot()
    assert rep["previous_session"] == "clean", "the sentinel's word is what it was: the teardown ran"
    assert rep["dispose"]["wal"] == 4_000_000 and rep["dispose"]["out"] == 2 and rep["dispose"]["step"] == "busy"
    text = forensics.render_text({"previous_session": rep})
    assert "- ended: clean" in text
    assert "the -wal was LEFT by that session's end: 4,000,000 bytes" in text and "2 connection(s) still checked out" in text, text
    assert "a reader, a writer or another checkpoint held the log" in text, "busy is worded as what it is: not only a reader"
    assert "not that this log was written back" in text and "(wal_at_boot)" in text
    assert "the teardown took" in text and "s from its first step to the end" in text, "the teardown's duration is readable now"
    assert "teardown began at:" not in text, "the timestamp is not copied (45 B of the byte room); the seconds are computed"


def test_the_clean_sentence_is_not_printed_under_a_verdict_that_is_not_clean(dd):
    """L1: the line says "'clean' above", so it belongs under a clean end only."""
    _wal(dd, 4_000_000)
    forensics.record_session_start()
    forensics.record_shutdown_phase("dispose-done", facts=forensics.dispose_facts({"checked_out": 2}, {"outcome": "busy"}))
    rep = _next_boot()  # no clean stamp: the end is "unclean-end-after-dispose"
    assert rep["previous_session"] == "unclean-end-after-dispose"
    text = forensics.render_text({"previous_session": rep})
    assert "the -wal was LEFT by that session's end" in text and "'clean' above" not in text, text


def test_a_log_of_zero_is_a_fact_and_an_unrecorded_value_is_silence(dd):
    _wal(dd, None)
    forensics.record_session_start()
    forensics.record_shutdown_phase("dispose-done", facts=forensics.dispose_facts({"checked_out": 0}, {"outcome": "done"}))
    forensics.record_clean_shutdown()
    rep = _next_boot()
    assert rep["dispose"]["wal"] == 0, "0 is carried, not dropped as falsy"
    assert "the -wal was empty after that session's pool was disposed" in forensics.render_text({"previous_session": rep})
    # a sentinel written by a build before this one has none of the keys: nothing is said, in particular not "empty"
    old = {"previous_session": "clean", "started_at": "2026-10-10T00:00:00+00:00", "ended_at": "2026-10-10T06:37:36+00:00"}
    assert "disposal" not in forensics.render_text({"previous_session": old}) and "LEFT" not in forensics.render_text({"previous_session": old})


def test_an_unreadable_log_is_not_called_empty_and_the_write_back_outcome_is_still_said(dd):
    forensics.record_session_start()
    forensics.record_shutdown_phase("dispose-done", facts={"dispose": {"wal": "unreadable", "out": 0, "step": "failed"}})
    forensics.record_clean_shutdown()
    rep = _next_boot()
    text = forensics.render_text({"previous_session": rep})
    assert "was not measured (the -wal's size could not be read" in text and "was empty" not in text, text
    assert "the write-back before it: the write-back failed" in text, "L2: the not-measured line says what the write-back did"


def test_a_damaged_sentinel_cannot_widen_the_report(dd):
    """The sentinel is a file on disk and anything may have written it: the report rebuilds the member field by field."""
    forensics.record_session_start()
    forensics.record_shutdown_phase("dispose-done")
    state = forensics._read_state()
    state["dispose"] = {"wal": 10**400, "out": True, "step": "a" * 500, "why": {"wal": "x" * 500}, "extra": [1] * 1000}
    forensics._write_state(state)
    forensics.record_clean_shutdown()
    member = _next_boot()["dispose"]
    assert {k: member[k] for k in ("wal", "out", "step")} == {"wal": "unreadable", "out": "unknown", "step": "unknown"}, member
    assert "not run" not in forensics.DISPOSE_STEP_WORDS["unknown"] and "did not run" not in forensics.DISPOSE_STEP_WORDS["unknown"], (
        "a step code this build does not know must not read as a step that never ran"
    )
    assert set(member) <= {"wal", "out", "step", "took"}, member
    # a number past its cut is not a measurement; a code the tables do not know is not carried
    state = forensics._read_state()
    state["dispose"] = {"wal": forensics.DISPOSE_WAL_MAX_BYTES + 1, "out": forensics.DISPOSE_OUT_MAX + 1, "step": "done"}
    forensics._write_state(state)
    member = _next_boot()["dispose"]
    assert {k: member[k] for k in ("wal", "out", "step")} == {"wal": "unreadable", "out": "unknown", "step": "done"}, member
    assert set(member) <= {"wal", "out", "step", "took"}, member


# --------------------------------------------------------------------------- #
#  (6) the wiring
# --------------------------------------------------------------------------- #


def test_the_lifespan_writes_the_log_back_after_the_guard_stops_and_before_the_disposal_and_hands_the_answer_on():
    """Read from the parse tree (a comment quoting a call name cannot satisfy it), in the form of ``tests/test_database_verify.py``."""
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(encoding="utf-8"))
    [life] = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"]
    yield_line = next(n.lineno for n in ast.walk(life) if isinstance(n, ast.Yield))
    calls = [n for n in ast.walk(life) if isinstance(n, ast.Call) and n.lineno > yield_line]

    def lines(name: str) -> list[int]:
        return [c.lineno for c in calls if (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == name]

    guard, step, dispose = lines("_stop_storage_guard"), lines("checkpoint_before_dispose"), lines("dispose_engine")
    assert guard and step and dispose, (guard, step, dispose)
    assert guard[0] < step[0] < dispose[0], "the write-back goes after the storage guard stops and before the pool is disposed"
    [writing] = [c for c in calls if getattr(c.func, "id", None) == "record_shutdown_phase" and c.args and getattr(c.args[0], "value", None) == "writing-back"]
    assert guard[0] < writing.lineno < step[0], "the write-back has its own phase stamp, after the guard and before the step (a death inside it reads as such)"
    [stamp] = [c for c in calls if getattr(c.func, "id", None) == "record_shutdown_phase" and c.args and getattr(c.args[0], "value", None) == "dispose-done"]
    facts = next(k.value for k in stamp.keywords if k.arg == "facts")
    assert isinstance(facts, ast.Call) and getattr(facts.func, "id", None) == "dispose_facts", "the dispose phase carries dispose_facts(...)"
    assert [getattr(a, "id", None) for a in facts.args] == ["disposed", "shutdown_checkpoint"], "the disposal's answer and the step's are what it is built from"
