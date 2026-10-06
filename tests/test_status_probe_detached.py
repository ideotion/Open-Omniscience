"""The /status data-version probe holds no slot of the pool, and dies with its engine.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics rank 12 (2026-09-30): "one API-thread checkout held for the whole process life"
on all 16 instances. Hands-on on the real app it named itself -- ``GET /api/articles`` ->
``_browse_total_cached`` -> ``insights._data_version`` -> ``engine.raw_connection()`` -- the pinned
probe connection that ``PRAGMA data_version`` needs (the value only tracks OTHER connections'
commits on a long-lived connection). It is idle and does not pin the WAL, but it held one pool
slot for ever and nothing counted it: on the small tier (6 + 6, API margin 4) the app had three
slots for API requests, not four.

It is now detached from the pool. Two consequences are pinned here against a REAL pool (the
repo's own ``ReservingQueuePool``) and a real SQLite file, no mocks: the slot is free while the
probe lives, and -- because ``Engine.dispose()`` only closes checked-IN connections -- the probe is
closed by the engine's own ``engine_disposed`` event, so an unlock, a restore's file swap or a
shutdown never leaves a handle on the replaced file.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest
from sqlalchemy import create_engine, event, text

from src.api import insights
from src.database import pool_watch
from src.database.pool_reserve import ReservingQueuePool


@pytest.fixture()
def eng(tmp_path):
    insights._reset_status_probe_for_tests()
    e = create_engine(
        f"sqlite:///{tmp_path / 'probe.db'}",
        future=True,
        poolclass=ReservingQueuePool,
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,
    )

    @event.listens_for(e, "connect")
    def _wal(dbapi, _rec):
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    with e.begin() as c:
        c.execute(text("CREATE TABLE t(x INTEGER)"))
    pool_watch.register(e)
    pool_watch._reset_for_tests()
    yield e
    insights._reset_status_probe_for_tests()
    e.dispose()


def test_the_probe_takes_no_slot_from_the_pool(eng):
    v = insights._data_version(eng)
    assert v is not None
    assert eng.pool.checkedout() == 0, "a detached probe is not one of the pool's checkouts"
    assert [r for r in pool_watch.checked_out() if r["ident"] == threading.get_ident()] == [], (
        "and is not listed as a standing holder (this thread's rows only: the registry is "
        "process-wide)"
    )
    # the whole pool (2 slots) is usable while the probe lives: with the probe pooled, the
    # second of these would wait pool_timeout (1 s) and raise
    held = [eng.connect(), eng.connect()]
    try:
        assert eng.pool.checkedout() == 2
    finally:
        for c in held:
            c.close()


def test_the_probe_still_sees_other_connections_commits(eng):
    v0 = insights._data_version(eng)
    with eng.begin() as c:
        c.execute(text("INSERT INTO t VALUES (1)"))
    v1 = insights._data_version(eng)
    assert v0 is not None and v1 is not None and v1 != v0
    assert insights._data_version(eng) == v1, "stable while nothing is written"


def test_disposing_the_engine_closes_the_probe_and_the_next_read_rebuilds_it(eng):
    insights._data_version(eng)
    old = insights._PROBE_CONNS[id(eng)]
    raw = old.dbapi_connection  # the DRIVER's own handle: the wrapper above it proves nothing
    assert raw is not None
    raw.execute("SELECT 1")  # open before the dispose
    eng.dispose()
    assert id(eng) not in insights._PROBE_CONNS and id(eng) not in insights._PROBE_ENGINES
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        raw.execute("SELECT 1")
    assert insights._data_version(eng) is not None, "a new probe is built on the next read"
    assert insights._PROBE_CONNS[id(eng)] is not old


def test_the_dispose_listener_is_attached_once_however_often_the_probe_is_rebuilt(eng):
    for _ in range(4):
        insights._data_version(eng)
        eng.dispose()
    assert len(list(eng.dispatch.engine_disposed)) == 1


def test_a_probe_read_in_flight_does_not_hang_a_dispose(eng, monkeypatch):
    """A dispose must never block on a probe read: it waits a bounded time, then drops the
    entry so the next read rebuilds (never a read through the stale handle)."""
    insights._data_version(eng)
    monkeypatch.setattr(insights, "_PROBE_CLOSE_WAIT_S", 0.05)
    insights._PROBE_LOCK.acquire()  # simulate a read in flight on another thread
    done = threading.Event()

    def dispose():
        eng.dispose()
        done.set()

    t = threading.Thread(target=dispose)
    t.start()
    try:
        assert done.wait(3.0), "dispose hung behind the probe lock"
    finally:
        insights._PROBE_LOCK.release()
        t.join(3.0)
    assert id(eng) not in insights._PROBE_CONNS


@pytest.mark.parametrize("pool_name", ["StaticPool", "SingletonThreadPool"])
def test_an_in_memory_engine_keeps_its_database_when_the_probe_reads(pool_name):
    """#1289 detached the probe from EVERY pool and broke eleven tests in four files: a ``StaticPool`` (and a
    ``SingletonThreadPool``) owns one connection that IS the in-memory database, so detaching it
    left the pool with no record and the next checkout opened a new, empty ``:memory:`` database
    ("no such table"). Only a pool of interchangeable connections may give the probe up."""
    from sqlalchemy import pool as sa_pool

    insights._reset_status_probe_for_tests()
    e = create_engine(
        "sqlite://",
        future=True,
        poolclass=getattr(sa_pool, pool_name),
        connect_args={"check_same_thread": False},
    )
    try:
        with e.begin() as c:
            c.execute(text("CREATE TABLE t(x INTEGER)"))
            c.execute(text("INSERT INTO t VALUES (7)"))
        assert insights._data_version(e) is not None
        with e.connect() as c:
            assert c.execute(text("SELECT x FROM t")).scalar() == 7
    finally:
        insights._reset_status_probe_for_tests()
        e.dispose()


def test_only_queue_and_null_pools_are_detachable(tmp_path):
    from sqlalchemy import pool as sa_pool

    for cls, expected in (
        (sa_pool.QueuePool, True),
        (sa_pool.NullPool, True),
        (ReservingQueuePool, True),
        (sa_pool.StaticPool, False),
        (sa_pool.SingletonThreadPool, False),
        # the allow-list's one real difference from a deny-list: a pool nobody listed is kept pooled
        (sa_pool.AssertionPool, False),
    ):
        e = create_engine(f"sqlite:///{tmp_path / (cls.__name__ + '.db')}", future=True, poolclass=cls)
        try:
            assert insights._detachable(e) is expected, cls.__name__
        finally:
            e.dispose()


def test_a_bind_with_no_pool_is_kept_pooled_not_an_error():
    """The ``except`` in ``_detachable``: an object with no ``.pool`` (a test double, a future engine
    type) answers False, the safe pooled behaviour, instead of raising into the status probe."""

    class _NoPool:
        pass

    assert insights._detachable(_NoPool()) is False
