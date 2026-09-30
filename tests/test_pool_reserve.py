"""D44 = a: the collector may not take the last `_API_MARGIN` pooled connections.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These drive the REAL ``ReservingQueuePool`` (SQLAlchemy's own QueuePool subclass) against an
in-memory creator, so what is asserted is the pool's behaviour, not a mock's. The negative
space matters most: a thread outside the collector role must never be limited, and a slot
must come back on every path a connection can leave by.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from src.config.memory_budget import _API_MARGIN
from src.database.pool_reserve import (
    ReservingQueuePool,
    collector_ceiling,
    collector_role,
    in_collector_role,
)

POOL, OVERFLOW = 2, 4  # 6 in total: the collector's ceiling is 6 - _API_MARGIN


def _engine(timeout: float = 0.3):
    return create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(":memory:", check_same_thread=False),
        poolclass=ReservingQueuePool,
        pool_size=POOL,
        max_overflow=OVERFLOW,
        pool_timeout=timeout,
    )


def test_the_ceiling_is_the_pool_minus_the_margin_and_never_below_one():
    assert collector_ceiling(24, 4) == 20
    assert collector_ceiling(12, 4) == 8
    assert collector_ceiling(3, 4) == 1  # a pool smaller than the margin still lets it run


def test_the_role_is_scoped_reentrant_and_per_thread():
    assert not in_collector_role()
    with collector_role():
        assert in_collector_role()
        with collector_role():
            assert in_collector_role()
        assert in_collector_role()  # the inner exit must not clear the outer marking
        seen = []
        t = threading.Thread(target=lambda: seen.append(in_collector_role()))
        t.start()
        t.join()
        assert seen == [False], "the role must not leak into other threads"
    assert not in_collector_role()


def test_collector_checkouts_stop_at_the_ceiling_and_leave_the_margin_free():
    eng = _engine()
    pool = eng.pool
    ceiling = POOL + OVERFLOW - _API_MARGIN
    held = []
    barrier_done = threading.Event()

    def collector():
        with collector_role():
            held.append(eng.raw_connection())
        barrier_done.wait(5)

    threads = [threading.Thread(target=collector) for _ in range(ceiling)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 3
    while len(held) < ceiling and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(held) == ceiling
    assert pool.reservation()["collector_held"] == ceiling

    # one collector worker past the ceiling is refused with the pool's own error ...
    with collector_role(), pytest.raises(PoolTimeoutError, match="last 4 connections"):
        eng.raw_connection()
    assert pool.reservation()["collector_waits"] >= 1

    # ... while the app (no role) still gets every connection the collector left.
    app = [eng.raw_connection() for _ in range(_API_MARGIN)]
    assert len(app) == _API_MARGIN
    for c in app:
        c.close()
    barrier_done.set()
    for t in threads:
        t.join()
    for c in held:
        c.close()


def test_a_slot_comes_back_when_the_connection_is_returned_and_a_waiter_proceeds():
    eng = _engine(timeout=5)
    ceiling = POOL + OVERFLOW - _API_MARGIN

    conns = []

    def hold():  # one slot per THREAD: a thread that already holds one is a nested checkout
        with collector_role():
            conns.append(eng.raw_connection())

    holders = [threading.Thread(target=hold) for _ in range(ceiling)]
    for h in holders:
        h.start()
    for h in holders:
        h.join()
    assert eng.pool.reservation()["collector_held"] == ceiling
    got = []

    def waiter():
        with collector_role():
            got.append(eng.raw_connection())

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.2)
    assert not got, "the waiter must be queued while every slot is held"
    conns.pop().close()  # checkin releases the slot
    t.join(3)
    assert len(got) == 1
    for c in conns + got:
        c.close()
    assert eng.pool.reservation()["collector_held"] == 0


def test_a_failed_checkout_does_not_leak_its_slot():
    def boom():
        raise RuntimeError("cannot open")

    eng = create_engine(
        "sqlite://", creator=boom, poolclass=ReservingQueuePool,
        pool_size=POOL, max_overflow=OVERFLOW, pool_timeout=0.2,
    )
    with collector_role():
        for _ in range(POOL + OVERFLOW + 3):  # more failures than there are slots
            with pytest.raises(RuntimeError):
                eng.raw_connection()
    assert eng.pool.reservation()["collector_held"] == 0


def test_a_holder_asking_for_a_second_connection_never_waits_for_a_slot():
    """Nested sessions must not deadlock every holder against every other holder."""
    eng = _engine(timeout=0.3)
    ceiling = POOL + OVERFLOW - _API_MARGIN
    with collector_role():
        first = [eng.raw_connection() for _ in range(1)]
        # fill the remaining slots from other threads, then ask for a second here
        others = []

        def take():
            with collector_role():
                others.append(eng.raw_connection())

        ts = [threading.Thread(target=take) for _ in range(ceiling - 1)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert eng.pool.reservation()["collector_held"] == ceiling
        second = eng.raw_connection()  # this thread holds a slot: it goes through
    assert eng.pool.reservation()["collector_nested"] == 1
    for c in first + others + [second]:
        c.close()
    assert eng.pool.reservation()["collector_held"] == 0


def test_threads_outside_the_role_are_never_limited():
    eng = _engine()
    conns = [eng.raw_connection() for _ in range(POOL + OVERFLOW)]
    assert eng.pool.reservation()["collector_held"] == 0
    assert eng.pool.reservation()["collector_waits"] == 0
    for c in conns:
        c.close()


def test_the_real_engine_uses_the_reserving_pool_and_the_collector_wears_the_role():
    """Anchored to sources, not to the shared `app` singleton's routes (a negative-space
    rule of this repo): the engine is built with the class, and the collector pool's worker
    enters the role around its session."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    session_src = (root / "src" / "database" / "session.py").read_text(encoding="utf-8")
    assert "poolclass=ReservingQueuePool" in session_src
    runner_src = (root / "src" / "scheduler" / "runner.py").read_text(encoding="utf-8")
    assert "with collector_role(), session_scope() as worker_session:" in runner_src
    from src.database.session import engine

    assert isinstance(engine.pool, ReservingQueuePool)
