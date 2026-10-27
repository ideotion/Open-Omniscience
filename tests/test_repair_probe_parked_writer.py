"""The repair's data-version read inside the swap window, against a writer parked behind that window (the WAL thread, 27 Oct 2026).

THE QUESTION (coordinator item 2 of 20:42Z). ``repair._swap`` hands ``swap_in_corpus`` a ``check`` that runs INSIDE the swap window, before
anything changes on disk: ``_Probe.moved()``, which takes SQLite's write lock (``BEGIN IMMEDIATE``, on a connection opened with a 30 s busy
timeout, ``repair._probe_open``) to ask whether any other connection committed since the copy began. Can a writer hold that lock while it is
itself blocked in ``connecting()`` behind the window the probe runs in? Then neither can move: the probe waits for the lock, the writer waits for
the window, and the window ends when the probe gives up.

WHAT THE TWO TESTS HOLD.

* ``test_a_thread_that_opens_a_second_connection_under_its_write_lock_makes_the_probe_wait_out_its_busy_timeout`` FORCES it: a writer holds the
  lock on a connection made before the window, and asks the guarded engine for a second one after the window opened. The second connection is not
  made while the window is held (the creator has run once, for the first, when the probe fails), the probe fails with ``database is locked``
  (the repair turns any failure of it into ``Declined("writer-busy")``, ``repair.py`` ``written_to_since``: the copy and its sidecar stay, nothing
  is switched), the window ends, and only then does the writer's second connection open, on the live file. The wait is the probe's busy timeout:
  30.085 s with the production 30 s (measured with the same shape on the app's own engine, 27 Oct 2026); this test gives the probe 0.5 s.
* ``test_a_thread_that_touches_its_connection_again_lets_go_and_the_probe_goes_through`` is the CONTROL, the case the design counts on: the
  writer's next statement on a connection made before the window is refused as stale, the error unwinds, the connection rolls back, the lock is
  free, and the probe's ``BEGIN IMMEDIATE`` goes through at once (measured 0.33 s of which 0.3 s was the writer's own delay).

WHY IT IS A LIMIT AND NOT A DEFECT. A thread holds SQLite's write lock only inside a transaction that wrote. The gated writers (every ORM flush,
ORM-issued DML and textual write, the explicit ``write_lock()`` sites) cannot be in that state when the repair's window opens: the repair holds
the single-writer gate for the whole repair, a gated writer takes its connection BEFORE the gate (``writer.connection_first``), and the gate is
released only at its commit or rollback, so a gate holder waited for by ``write_lock()`` has already ended its transaction. What can reach the
probe's wait is a writer the gate does not see (a Core or raw-driver write transaction) that then asks the guarded engine for a SECOND
connection. In ``src/`` the corpus writers the gate does not see are the settings saves (``kv_store``: one raw connection, opened outside the
guard, no second connection under its transaction) and the ``init_db`` DDL steps (run at launch and at unlock, before the boot steps, of which the
repair is one; that no other thread runs one during a repair is read from the call sites, not proved); ``scheduler/hygiene.py`` and
``release.py`` open a raw connection for a checkpoint (under the gate) and for ``shrink_memory``, neither a row write. A sweep of the whole test suite for a nested open made while the first connection had written (136,587 checkouts, 103,477 of
them by a thread that already held another, 668 of those with the held connection inside a transaction that had changed rows) found every one
held by an ORM session and none by Core or raw code. The restore has no such read: its window waits for no SQLite lock.

WHAT IT DOES NOT COVER. Windows, where the restore's file steps wait (up to ``_SWAP_HANDLE_WAIT_S``, 300 s) for every handle on the live file to
close: a thread parked in ``connecting()`` with a connection checked out holds its handle, whether or not it wrote. That is the shape the rollup
build's boundary check avoids on purpose (``rollup_serve._require_library_unchanged`` never waits for the window), and it is not exercised here
(``_retry_while_locked`` retries only a Windows sharing violation).

No test here reads a clock for its verdict: the ORDER is asserted (the creator had not run for the second connection when the probe failed; it
had when the window was over), and the 0.5 s is the probe's own busy timeout, which the property does not depend on.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.backup.merge import swap_in_corpus
from src.database import library_generation as gen
from src.database import repair
from tests.wallclock_helpers import HANG_GUARD_S

#: The probe's busy timeout in the forced case (production: 30 s). The property is the ORDER around it, not the figure.
_PROBE_BUSY_S = 0.5


def _store(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO notes (body) VALUES ('before')")
    con.commit()
    con.close()


class _World:
    """A library file, an engine over it whose connections are opened the way the app's are (through the guarded creator, with the generation
    guard attached), a stand-in for the copy the swap would put in place (never reached: the check raises or the probe goes through first), and
    the repair's data-version probe on the live file."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, busy_s: float) -> None:
        self.live = tmp_path / "live.db"
        _store(self.live)
        self.opened: list[int] = []  # one entry per connection the creator really made, in order

        def _open() -> sqlite3.Connection:
            self.opened.append(len(self.opened) + 1)
            return sqlite3.connect(str(self.live), check_same_thread=False)

        # A file URL: the pool is a QueuePool, as the app's is (``test_library_generation._engine``).
        self.engine = create_engine(f"sqlite:///{self.live}", creator=gen.guarded_creator(_open))
        gen.attach(self.engine)
        self.working = tmp_path / "working.db"
        self.working.write_bytes(b"a copy the swap never reaches")
        # ``swap_in_corpus`` disposes the APP's engine inside the window; here that is this test's engine, so its idle connections are closed as
        # the app's are and a new connection must be made, through the creator, behind the window.
        monkeypatch.setattr("src.database.session.dispose_engine", self.engine.dispose)
        monkeypatch.setattr(
            repair, "_probe_open", lambda p: sqlite3.connect(str(p), check_same_thread=False, timeout=busy_s)
        )
        self.probe = repair._Probe(self.live)
        self.before = (self.live.stat().st_ino, self.live.read_bytes())

    def close(self) -> None:
        self.probe.close()
        self.engine.dispose()

    def untouched(self) -> bool:
        return (
            (self.live.stat().st_ino, self.live.read_bytes()) == self.before
            and self.working.read_bytes() == b"a copy the swap never reaches"
        )


@pytest.fixture
def forced(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch, _PROBE_BUSY_S)
    yield world
    world.close()


@pytest.fixture
def control(tmp_path, monkeypatch):
    world = _World(tmp_path, monkeypatch, HANG_GUARD_S)  # a probe that is let through waits only as long as the writer takes
    yield world
    world.close()


def test_a_thread_that_opens_a_second_connection_under_its_write_lock_makes_the_probe_wait_out_its_busy_timeout(forced):
    world = forced
    holding, window_open, requested = threading.Event(), threading.Event(), threading.Event()
    seen: dict[str, object] = {}

    def writer() -> None:
        c1 = world.engine.connect()
        c1.execute(text("INSERT INTO notes (body) VALUES ('written under the lock')"))  # pysqlite opens the transaction here
        seen["in_transaction"] = c1.connection.driver_connection.in_transaction
        holding.set()
        window_open.wait(HANG_GUARD_S)
        requested.set()
        try:
            c2 = world.engine.connect()  # a connection made after the window opened: parks in ``connecting()`` until it ends
        except BaseException as exc:  # noqa: BLE001 - handed to the test
            seen["second"] = exc
        else:
            seen["second"] = "opened"
            seen["second_sees"] = [r[0] for r in c2.execute(text("SELECT body FROM notes ORDER BY id"))]
            c2.close()
        c1.rollback()  # the window has ended: the first connection is valid again and gives the lock back
        c1.close()

    thread = threading.Thread(target=writer, name="writer", daemon=True)
    thread.start()
    assert holding.wait(HANG_GUARD_S)

    def check() -> None:
        window_open.set()
        assert requested.wait(HANG_GUARD_S)
        try:
            world.probe.moved()
        except sqlite3.OperationalError as exc:
            seen["probe"] = str(exc)
            seen["creator_runs_when_the_probe_failed"] = len(world.opened)
            raise

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        swap_in_corpus(world.working, world.live, check=check)
    thread.join(HANG_GUARD_S)
    assert not thread.is_alive()

    assert seen["in_transaction"] is True, "the writer must hold SQLite's write lock for this to be the case under test"
    assert "locked" in str(seen["probe"])
    # While the window was held the writer's second connection was not made: the creator had run once (the first connection) when the probe failed.
    assert seen["creator_runs_when_the_probe_failed"] == 1
    # Once the window was over it was, on the live file, and the lock holder's uncommitted row was not in it.
    assert seen["second"] == "opened"
    assert world.opened == [1, 2]
    assert seen["second_sees"] == ["before"]
    # A failed check switches nothing and gives the earlier connections their validity back.
    assert world.untouched()


def test_a_thread_that_touches_its_connection_again_lets_go_and_the_probe_goes_through(control):
    world = control
    holding, window_open, released = threading.Event(), threading.Event(), threading.Event()
    seen: dict[str, object] = {}

    def writer() -> None:
        c1 = world.engine.connect()
        c1.execute(text("INSERT INTO notes (body) VALUES ('written under the lock')"))
        holding.set()
        window_open.wait(HANG_GUARD_S)
        try:
            c1.execute(text("SELECT 1"))  # the next statement on a connection made before the window
        except gen.StaleLibraryError as exc:
            seen["touched"] = type(exc).__name__
        else:
            seen["touched"] = "ran"
        c1.rollback()
        c1.close()
        released.set()

    thread = threading.Thread(target=writer, name="writer", daemon=True)
    thread.start()
    assert holding.wait(HANG_GUARD_S)
    moved: list[bool] = []

    def check() -> None:
        window_open.set()
        moved.append(world.probe.moved())  # waits only for the writer to let go
        raise repair.Declined("test-stop", "the check ends the swap here, so the file is not replaced")

    with pytest.raises(repair.Declined):
        swap_in_corpus(world.working, world.live, check=check)
    thread.join(HANG_GUARD_S)
    assert released.is_set()

    assert seen["touched"] == "StaleLibraryError"
    assert moved == [False], "the writer rolled back, so nothing was committed and the file did not move"
    assert world.untouched()
