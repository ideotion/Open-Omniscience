"""A save that waits out the repair or the restore must not land in the file that was set aside (the deep read of E3, B1 and NEW-1).

``dispose_engine()`` closes a pool's IDLE connections; a connection a request has checked out stays open on the OLD inode, and
in WAL mode SQLite does not notice that the name now points elsewhere. Measured by the read: the save waited, reported ok, and
the row was in the damaged file (``<stem>.damaged-*``, which R129 removes thirty days later) while the library read as if it
had never happened. ``library_generation`` stamps every connection of an engine under a lock the swap takes exclusively, and
refuses a statement, a COMMIT and a checkout on a connection from before it.
"""
from __future__ import annotations

import errno
import os
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from src.database import library_generation as gen


def _store(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO notes (body) VALUES ('before')")
    con.commit()
    con.close()


def _bodies(path: Path) -> list[str]:
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT body FROM notes ORDER BY id")]
    finally:
        con.close()


def _engine(live: Path, *, creator=None):
    """An engine over ``live`` whose connections are opened the way the app's are: through the guarded creator."""

    def _open():
        return sqlite3.connect(str(live), check_same_thread=False)

    # a FILE url: the pool is a QueuePool, as the app's is (an in-memory url gets a SingletonThreadPool, which closes checked-out connections)
    engine = create_engine(f"sqlite:///{live}", creator=gen.guarded_creator(creator or _open))
    gen.attach(engine)
    return engine


@pytest.fixture()
def world(tmp_path):
    live = tmp_path / "live.db"
    _store(live)
    engine = _engine(live)
    yield tmp_path, live, engine
    engine.dispose()


def _switch(tmp_path: Path, live: Path) -> Path:
    """What the swap does to the names: a second name for the old file, the new file under the live name."""
    new = tmp_path / "new.db"
    _store(new)
    kept = tmp_path / "live.damaged-20261006T000000Z.db"
    os.link(live, kept)
    for suffix in ("-wal", "-shm"):  # the log goes with the file it belongs to; the live names are cleared before the replace
        old = Path(str(live) + suffix)
        if old.exists():
            if suffix == "-wal":
                os.link(old, Path(str(kept) + suffix))
            old.unlink()
    os.replace(new, live)
    return kept


def _replaced_inside_the_window(tmp_path: Path, live: Path) -> Path:
    """The swap as the app runs it: the window around the change of names, whose ``source`` is gone when the change happened."""
    new = tmp_path / "new.db"
    _store(new)
    kept = tmp_path / "live.damaged-20261006T000000Z.db"
    with gen.swap_window(new):
        os.link(live, kept)
        for suffix in ("-wal", "-shm"):
            old = Path(str(live) + suffix)
            if old.exists():
                if suffix == "-wal":
                    os.link(old, Path(str(kept) + suffix))
                old.unlink()
        os.replace(new, live)
    return kept


# --------------------------------------------------------------------------- #
#  the defect, and the guard
# --------------------------------------------------------------------------- #
def test_without_the_guard_a_save_through_a_checked_out_connection_lands_in_the_kept_file(tmp_path):
    """The defect, reproduced: the evidence that the guard below is what stops it."""
    live = tmp_path / "live.db"
    _store(live)
    engine = create_engine(f"sqlite:///{live}")  # no guard
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM notes")).scalar()
            kept = _switch(tmp_path, live)
            engine.dispose()  # what dispose_engine() does: the checked-out connection stays
            conn.execute(text("INSERT INTO notes (body) VALUES ('saved during the repair')"))
            conn.commit()
        assert "saved during the repair" in _bodies(kept), "the defect did not reproduce: the test proves nothing"
        assert "saved during the repair" not in _bodies(live)
    finally:
        engine.dispose()


def test_a_checked_out_connection_from_before_the_switch_is_refused_and_the_save_lands_nowhere(world):
    tmp_path, live, engine = world
    with engine.connect() as conn:
        conn.execute(text("SELECT count(*) FROM notes")).scalar()
        kept = _replaced_inside_the_window(tmp_path, live)
        engine.dispose()
        with pytest.raises(gen.StaleLibraryError):
            conn.execute(text("INSERT INTO notes (body) VALUES ('saved during the repair')"))
    assert "saved during the repair" not in _bodies(kept) and "saved during the repair" not in _bodies(live)
    # the connection is gone for good, and a new one reads the NEW file and writes to it
    with engine.begin() as fresh:
        fresh.execute(text("INSERT INTO notes (body) VALUES ('saved after')"))
    assert _bodies(live) == ["before", "saved after"] and _bodies(kept) == ["before"]


def test_a_read_on_a_stale_connection_is_refused_too_and_a_connection_made_after_the_window_is_not(world):
    tmp_path, live, engine = world
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar()
        _replaced_inside_the_window(tmp_path, live)
        engine.dispose()
        with pytest.raises(gen.StaleLibraryError):
            conn.execute(text("SELECT count(*) FROM notes"))
    with engine.connect() as fresh:
        assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1
        assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1


def test_the_stale_connection_never_returns_to_the_pool(world):
    tmp_path, live, engine = world
    conn = engine.connect()
    conn.execute(text("SELECT 1")).scalar()
    _replaced_inside_the_window(tmp_path, live)  # the pool was not disposed here: its idle connections would be stale too
    with pytest.raises(gen.StaleLibraryError):
        conn.execute(text("SELECT 1"))
    conn.close()
    with engine.connect() as again:
        assert again.execute(text("SELECT count(*) FROM notes")).scalar() == 1, "a stale connection was handed out again"


# --------------------------------------------------------------------------- #
#  NEW-1 (a): the COMMIT is not a cursor statement
# --------------------------------------------------------------------------- #
def test_a_commit_after_the_switch_is_refused_and_the_row_is_in_neither_file(world):
    """begin, INSERT, bump, commit: the INSERT ran on a valid connection, so only the COMMIT's own guard stops it."""
    tmp_path, live, engine = world
    conn = engine.connect()
    conn.execute(text("INSERT INTO notes (body) VALUES ('half saved')"))  # the transaction is open on the OLD file
    kept = _replaced_inside_the_window(tmp_path, live)
    with pytest.raises(gen.StaleLibraryError):
        conn.commit()
    conn.close()
    assert "half saved" not in _bodies(kept) and "half saved" not in _bodies(live), "a commit on a stale connection landed"
    with engine.connect() as fresh:  # nothing is left behind for the next connection either
        assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1


def test_a_commit_on_a_current_connection_still_commits(world):
    _tmp, live, engine = world
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO notes (body) VALUES ('saved')"))
    assert _bodies(live) == ["before", "saved"]


# --------------------------------------------------------------------------- #
#  the pool: idle connections, several of them
# --------------------------------------------------------------------------- #
def test_idle_pooled_connections_from_before_the_switch_are_not_handed_out(world):
    tmp_path, live, engine = world
    held = [engine.connect() for _ in range(3)]
    for conn in held:
        conn.execute(text("SELECT 1")).scalar()
    for conn in held:
        conn.close()  # three idle connections in the pool, all on the old file
    _replaced_inside_the_window(tmp_path, live)  # NOT disposed: the checkout is what must refuse them
    for _ in range(4):
        with engine.connect() as fresh:
            assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1
            fresh.execute(text("SELECT 1"))
    with engine.begin() as writer:
        writer.execute(text("INSERT INTO notes (body) VALUES ('saved after')"))
    assert _bodies(live) == ["before", "saved after"]


# --------------------------------------------------------------------------- #
#  NEW-1: the open and the swap share one lock
# --------------------------------------------------------------------------- #
def test_a_connection_opened_while_the_swap_waits_for_the_window_is_stamped_before_it_and_is_never_used(tmp_path):
    """A connect that straddles the swap (read the generation, was opening the file) is on the OLD file: it is stamped with the OLD
    generation, the swap waits for it, and the checkout that follows refuses it, so the thread that opened it is given a connection
    to the NEW file instead and nothing ever runs on the old one."""
    live = tmp_path / "live.db"
    _store(live)
    opening, let_go = threading.Event(), threading.Event()
    opened: list[sqlite3.Connection] = []

    def slow_open():
        opening.set()
        assert let_go.wait(10), "the test's own timer did not fire"
        con = sqlite3.connect(str(live), check_same_thread=False)
        opened.append(con)
        return con

    engine = _engine(live, creator=slow_open)
    made: list = []
    swapped = threading.Event()
    # the straddling connection is held after it was opened and stamped, until the swap has happened: without this the thread can finish its
    # checkout and its read in the microseconds between the lock being let go and the bump, and is then (rightly) served by the old file
    event.listen(engine, "connect", lambda *_: swapped.wait(10))

    def connect_in_a_thread() -> None:
        conn = engine.connect()
        made.append(conn.exec_driver_sql("SELECT group_concat(body) FROM notes").scalar())
        conn.close()

    t = threading.Thread(target=connect_in_a_thread)
    t.start()
    try:
        assert opening.wait(10)
        # the swap cannot have its window while a connection is being opened
        with pytest.raises(gen.LibraryBusy), gen.swap_window(tmp_path / "new.db", timeout=0.2):
            raise AssertionError("the window was granted over an open in progress")
        before = gen.current()
        threading.Timer(0.3, let_go.set).start()
        new = tmp_path / "new.db"
        _store(new)
        con = sqlite3.connect(new)
        con.execute("INSERT INTO notes (body) VALUES ('only in the new file')")
        con.commit()
        con.close()
        with gen.swap_window(new, timeout=10):  # waits for the open, then bumps
            assert gen.current() == before + 1
            assert let_go.is_set(), "the window was granted before the open finished"
            for suffix in ("-wal", "-shm"):  # the straddling connection read at creator time, so its log exists: the swap removes the names first
                Path(str(live) + suffix).unlink(missing_ok=True)
            os.replace(new, live)
        swapped.set()
        t.join(10)
        assert not t.is_alive()
        assert made == ["before,only in the new file"], f"the thread was served by the old file: {made}"
        assert len(opened) == 2, "the straddling connection was not replaced"
        with pytest.raises(sqlite3.ProgrammingError):  # the straddling connection was closed unused
            opened[0].execute("SELECT 1")
    finally:
        let_go.set()
        swapped.set()
        t.join(10)
        engine.dispose()


def test_a_busy_window_changes_nothing_and_a_later_swap_still_works(tmp_path):
    live = tmp_path / "live.db"
    _store(live)
    opening, let_go = threading.Event(), threading.Event()

    def slow_open():
        opening.set()
        let_go.wait(10)
        return sqlite3.connect(str(live), check_same_thread=False)

    engine = _engine(live, creator=slow_open)
    t = threading.Thread(target=lambda: engine.connect().close())
    t.start()
    try:
        assert opening.wait(10)
        before = gen.current()
        with pytest.raises(gen.LibraryBusy), gen.swap_window(tmp_path / "new.db", timeout=0.1):
            pass
        assert gen.current() == before, "a window that was refused moved the generation"
    finally:
        let_go.set()
        t.join(10)
        engine.dispose()
    new = tmp_path / "new.db"
    _store(new)
    with gen.swap_window(new, timeout=5):
        os.replace(new, live)


def test_the_thread_that_holds_the_window_opens_connections_of_its_own_and_another_thread_waits(tmp_path):
    live = tmp_path / "live.db"
    _store(live)
    engine = _engine(live)
    new = tmp_path / "new.db"
    _store(new)
    waited: list[float] = []
    try:
        with gen.swap_window(new, timeout=5):
            with engine.connect() as mine:  # the swap folds the log and reads the data version through connections of its own
                assert mine.execute(text("SELECT count(*) FROM notes")).scalar() == 1

            def other() -> None:
                import time

                t0 = time.monotonic()
                with engine.connect() as c:
                    c.execute(text("SELECT 1"))
                waited.append(time.monotonic() - t0)

            t = threading.Thread(target=other)
            t.start()
            t.join(0.3)
            assert t.is_alive(), "another thread opened a connection inside the window"
            os.replace(new, live)
        t.join(10)
        assert waited and waited[0] >= 0.25
    finally:
        engine.dispose()


def test_an_open_that_fails_hands_no_stamp_to_the_next_connection_of_the_thread(tmp_path):
    live = tmp_path / "live.db"
    _store(live)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return sqlite3.connect(str(live), check_same_thread=False)

    engine = _engine(live, creator=flaky)
    try:
        with pytest.raises(Exception):  # noqa: B017 - SQLAlchemy wraps it
            engine.connect()
        assert getattr(gen._local, "stamp", None) is None
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM notes").scalar() == 1
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
#  the first read of a plaintext library is made under the lock (the delta read of E3 fold 2, A)
# --------------------------------------------------------------------------- #
def _app_pragma_engine(live: Path, *, creator=None):
    """:func:`_engine` with the app's own ``connect`` listener (``session._sqlite_pragmas``), the first statement of every plaintext connection."""
    from src.database import session

    engine = _engine(live, creator=creator)
    event.listen(engine, "connect", session._sqlite_pragmas)
    return engine


def _window_is_refused_while(statement_seen: list) -> Callable[[str], None]:
    """A trace callback that, at the FIRST statement a connection runs, asks (from another thread) for the swap window and records the
    statement and whether the window was refused."""

    def trace(statement: str) -> None:
        if statement_seen:
            return
        answer: list[str] = []

        def ask() -> None:
            try:
                with gen.swap_window(Path("/nonexistent/source"), timeout=0.05):
                    answer.append("granted")
            except gen.LibraryBusy:
                answer.append("busy")

        t = threading.Thread(target=ask)
        t.start()
        t.join(10)
        statement_seen.append((statement, answer[0] if answer else "no answer"))

    return trace


def test_the_first_statement_of_a_plaintext_connection_runs_while_the_swap_cannot_have_its_window(tmp_path):
    """A plaintext connection opens the log's names at its first READ, and that read was the pragma listener's, after the lock was let go:
    a swap that landed in between bound the new file's log to the old file and the schema read failed as malformed (which the damage
    hook files as damage). The creator reads once under the lock, so the first statement the listener runs is not the first read."""
    live = tmp_path / "live.db"
    _store(live)
    seen: list = []

    def traced_open():
        con = sqlite3.connect(str(live), check_same_thread=False)
        con.set_trace_callback(_window_is_refused_while(seen))
        return con

    engine = _app_pragma_engine(live, creator=traced_open)
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM notes").scalar() == 1
        assert seen, "the connection ran nothing"
        statement, answer = seen[0]
        assert answer == "busy", f"the first statement on the connection ({statement!r}) ran after the lock was let go"
        assert "sqlite_master" in statement
    finally:
        engine.dispose()


def test_a_connection_whose_first_read_fails_is_closed_and_the_creator_raises(tmp_path):
    live = tmp_path / "live.db"
    _store(live)
    opened: list[sqlite3.Connection] = []

    class Unreadable(sqlite3.Connection):
        def cursor(self, *a, **kw):
            raise sqlite3.DatabaseError("database disk image is malformed")

    def open_it():
        con = sqlite3.connect(str(live), check_same_thread=False, factory=Unreadable)
        opened.append(con)
        return con

    with pytest.raises(sqlite3.DatabaseError):
        gen.guarded_creator(open_it)()
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")  # closed, not leaked
    assert getattr(gen._local, "stamp", None) is None
    assert gen._LOCK._shared == 0 and gen._LOCK._holder is None, "the lock was kept by a creator that raised"


def test_a_library_that_does_not_exist_yet_is_created_and_read_through_the_guarded_creator(tmp_path):
    live = tmp_path / "fresh.db"
    engine = _app_pragma_engine(live)
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
#  when the swap does not happen, the old connections are the library's again
# --------------------------------------------------------------------------- #
def test_a_window_whose_source_still_exists_gives_the_old_connections_their_validity_back(world):
    tmp_path, live, engine = world
    new = tmp_path / "new.db"
    _store(new)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar()
        stamp = conn.connection.info[gen._KEY]
        before = gen.current()
        with gen.swap_window(new):
            assert gen.current() == before + 1
            assert not gen.valid(stamp), "inside the window the old connections must already be refused"
        # the replace did not happen (new.db is still there): the old connection opened the file that is still the library
        assert gen.valid(stamp)
        conn.execute(text("INSERT INTO notes (body) VALUES ('saved after a refused swap')"))
        conn.commit()
    assert "saved after a refused swap" in _bodies(live)


def test_a_connection_the_swap_itself_opens_before_the_replace_is_an_old_connection(world):
    """The data-version read and the log fold open connections inside the window, on the OLD file: they must not be handed out after the
    replace under the new generation (the first version of the lock stamped them with it)."""
    tmp_path, live, engine = world
    new = tmp_path / "new.db"
    _store(new)
    with gen.swap_window(new, timeout=5):
        mine = engine.connect()
        stamp = mine.connection.info[gen._KEY]
        mine.close()  # back to the pool, idle, on the old file
        os.replace(new, live)
    assert not gen.valid(stamp), "a connection opened on the old file inside the window is valid after the replace"
    with engine.connect() as fresh:
        assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1
        assert fresh.connection.info[gen._KEY] == gen.current()


def test_a_window_whose_source_is_gone_leaves_the_old_connections_stale(world):
    tmp_path, live, engine = world
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar()
        _replaced_inside_the_window(tmp_path, live)
        with pytest.raises(gen.StaleLibraryError):
            conn.execute(text("SELECT 1"))


# --------------------------------------------------------------------------- #
#  the restore's swap and the repair's swap are ONE helper
# --------------------------------------------------------------------------- #
def test_the_restores_swap_refuses_a_connection_that_was_checked_out_before_it(world, monkeypatch):
    from src.backup import merge

    tmp_path, live, engine = world
    working = tmp_path / "working.db"
    _store(working)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)  # the app's engine is not this test's
    with engine.connect() as conn:
        conn.execute(text("SELECT count(*) FROM notes")).scalar()
        merge.swap_in_corpus(working, live)
        with pytest.raises(gen.StaleLibraryError):
            conn.execute(text("INSERT INTO notes (body) VALUES ('saved during the restore')"))
    assert "saved during the restore" not in _bodies(live), "a save that waited out the restore landed in the file it replaced"
    with engine.connect() as fresh:  # a connection made after the swap is on the new file and is not refused
        assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1


def test_the_restores_swap_with_an_idle_pooled_connection_hands_out_a_connection_on_the_new_file(world, monkeypatch):
    from src.backup import merge

    tmp_path, live, engine = world
    working = tmp_path / "working.db"
    _store(working)
    con = sqlite3.connect(working)
    con.execute("INSERT INTO notes (body) VALUES ('only in the restored file')")
    con.commit()
    con.close()  # the restored file is whole, its log folded in
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)  # the idle connection is NOT closed
    with engine.connect() as idle:
        idle.execute(text("SELECT count(*) FROM notes")).scalar()
    merge.swap_in_corpus(working, live)
    with engine.connect() as fresh:
        assert [r[0] for r in fresh.execute(text("SELECT body FROM notes ORDER BY id"))] == ["before", "only in the restored file"]


def test_the_swap_helper_runs_its_check_after_the_generation_moved_and_before_anything_changed(world, monkeypatch):
    """The repair's data-version check runs here: a save that lands in the old file can only do so BEFORE the move."""
    from src.backup import merge

    tmp_path, live, engine = world
    working = tmp_path / "working.db"
    _store(working)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)
    seen: dict = {}

    def check() -> None:
        seen["generation"] = gen.current()
        seen["valid_now"] = gen.valid(0)  # a connection from before is already refused
        seen["working_still_there"] = working.exists()

    before = gen.current()
    merge.swap_in_corpus(working, live, check=check)
    assert seen == {"generation": before + 1, "valid_now": False, "working_still_there": True}
    assert not working.exists()


def test_a_check_that_refuses_leaves_the_file_alone_and_the_old_connections_valid(world, monkeypatch):
    from src.backup import merge

    tmp_path, live, engine = world
    working = tmp_path / "working.db"
    _store(working)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)

    class Refused(Exception):
        pass

    def check() -> None:
        raise Refused

    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar()
        with pytest.raises(Refused):
            merge.swap_in_corpus(working, live, check=check)
        assert working.exists()
        conn.execute(text("INSERT INTO notes (body) VALUES ('still the library')"))
        conn.commit()
    assert _bodies(live) == ["before", "still the library"]


def test_a_check_that_refuses_leaves_a_connection_that_holds_the_log_valid_and_its_save_is_visible(tmp_path, monkeypatch):
    """The same refusal with the app's connect listener, which reads at connect: the connection holds the log from the start, and nothing was
    removed, so what it saves afterwards is read by the next connection."""
    from src.backup import merge

    live = tmp_path / "live.db"
    _store(live)
    working = tmp_path / "working.db"
    _store(working)
    engine = _app_pragma_engine(live)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)

    class Refused(Exception):
        pass

    def check() -> None:
        raise Refused

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1")).scalar()
            with pytest.raises(Refused):
                merge.swap_in_corpus(working, live, check=check)
            conn.execute(text("INSERT INTO notes (body) VALUES ('saved after the refusal')"))
            conn.commit()
        assert _bodies(live) == ["before", "saved after the refusal"]
    finally:
        engine.dispose()


def test_a_replace_that_could_not_be_made_after_the_log_names_were_removed_refuses_the_old_connections_and_nothing_is_lost(tmp_path, monkeypatch):
    """The measured hazard: a pooled connection holds the log by an inode (it read at connect), the swap removed the log's names, the replace
    failed, and the earlier version of this window gave the connection its validity back. Its save committed into a log no name points at,
    and the next connection read ``disk I/O error``. The connection is refused now, and the library is intact and writable."""
    from src.backup import merge

    live = tmp_path / "live.db"
    _store(live)
    working = tmp_path / "working.db"
    _store(working)
    engine = _app_pragma_engine(live)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)

    def refuse(src, dst):
        raise OSError(errno.EROFS, "read-only file system")  # not a lock: not retried

    monkeypatch.setattr(merge.os, "replace", refuse)
    try:
        conn = engine.connect()
        conn.execute(text("SELECT 1")).scalar()
        with pytest.raises(OSError):
            merge.swap_in_corpus(working, live)
        assert working.exists() and not Path(str(live) + "-wal").exists(), "the test's premise: the names were removed, the replace failed"
        with pytest.raises(gen.StaleLibraryError):
            conn.execute(text("INSERT INTO notes (body) VALUES ('into a log nobody reads')"))
        conn.rollback()
        conn.close()
        assert _bodies(live) == ["before"]
        with engine.connect() as fresh:  # the pool made a connection on the file as it is
            fresh.execute(text("INSERT INTO notes (body) VALUES ('after the failed swap')"))
            fresh.commit()
        assert _bodies(live) == ["before", "after the failed swap"]
    finally:
        engine.dispose()


def test_a_replace_that_could_not_be_made_leaves_a_connection_of_the_window_s_own_stale_too(world, monkeypatch):
    """The data-version connection the swap opens inside the window is on the old file: when the names were removed and the replace failed,
    its stamp does not become valid afterwards either."""
    from src.backup import merge

    tmp_path, live, engine = world
    working = tmp_path / "working.db"
    _store(working)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)
    stamps: list = []

    def check() -> None:
        stamps.append(gen._WINDOW_STAMP)

    def refuse(src, dst):
        raise OSError(errno.EROFS, "read-only file system")

    monkeypatch.setattr(merge.os, "replace", refuse)
    with pytest.raises(OSError):
        merge.swap_in_corpus(working, live, check=check)
    assert stamps and stamps[0] is not None and not gen.valid(stamps[0])


def test_init_db_after_a_swap_is_not_refused_by_the_window_that_just_ended():
    """The restore and the repair both call ``init_db()`` right after the window: the lock is free and the engine's new connections are
    stamped with the generation the swap moved to."""
    from src.database import session

    session.init_db()
    gen.bump()  # a swap's window ended: every connection from before is stale
    session.engine.dispose()
    session.init_db()
    with session.engine.connect() as conn:
        assert conn.connection.info.get(gen._KEY) == gen.current()
        assert conn.exec_driver_sql("SELECT 1").scalar() == 1


def test_the_session_engine_and_the_snapshot_engine_are_stamped_through_the_guarded_creator():
    from src.database import read_snapshot, session

    session.init_db()
    with session.engine.connect() as conn:
        assert conn.connection.info.get(gen._KEY) == gen.current(), "the corpus engine's connections are not stamped"
    snap = read_snapshot._build_read_engine(str(session.engine.url))
    try:
        with snap.connect() as conn:
            assert conn.connection.info.get(gen._KEY) == gen.current(), "the read-snapshot engine's connections are not stamped"
        conn2 = snap.connect()
        gen.bump()
        try:
            with pytest.raises(gen.StaleLibraryError):
                conn2.execute(text("SELECT 1"))
        finally:
            conn2.close()
    finally:
        snap.dispose()
