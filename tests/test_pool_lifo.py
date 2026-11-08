"""The pool hands out the connection that was returned last (R470, D1 of the 07 Nov cache/pool/checkpoint measurements).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A SQLite connection's page cache belongs to the connection. With the pool's default first-in-first-out order, a flush lands on the
connection some OTHER flush used last, so its cache is warm for somebody else's pages: on a 4.4 GB encrypted store 0 of 84 flushes
read from a warm cache, against 50 to 54 of 84 with the last returned connection handed out first. What must hold:

* the engine is built with it (``pool_use_lifo=True``) and its pool is still the reserving one;
* a connection that has just been returned is the next one handed out (and under the default order it is NOT, which is why the
  assertion is not vacuous);
* the collector's reservation (D44) counts the same under either order: a slot comes back when its connection is returned, and the
  ceiling still stops a collector at the pool minus the API's margin.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from src.config.memory_budget import _API_MARGIN
from src.database.pool_reserve import ReservingQueuePool, collector_ceiling, collector_role
from tests.wallclock_helpers import HANG_GUARD_S

POOL, OVERFLOW = 3, 3


def _engine(**kwargs):
    return create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(":memory:", check_same_thread=False),
        poolclass=ReservingQueuePool,
        pool_size=POOL,
        max_overflow=OVERFLOW,
        pool_timeout=0.3,
        **kwargs,
    )


def _checkout_return(eng, count: int) -> list[int]:
    """Open ``count`` connections at once, give them all back, and say which DBAPI object each one was."""
    fairies = [eng.raw_connection() for _ in range(count)]
    ids = [id(f.dbapi_connection) for f in fairies]
    for f in fairies:
        f.close()
    return ids


def test_the_real_engine_is_built_with_it_and_keeps_the_reserving_pool():
    from src.database.session import engine

    assert isinstance(engine.pool, ReservingQueuePool)
    assert engine.pool._pool.use_lifo is True


def test_the_connection_just_returned_is_the_next_one_handed_out():
    eng = _engine(pool_use_lifo=True)
    try:
        _checkout_return(eng, 3)  # three connections now sit idle in the pool
        last = None
        for _ in range(5):
            f = eng.raw_connection()
            now = id(f.dbapi_connection)
            f.close()
            if last is not None:
                assert now == last, "returned and taken again: the same connection, with its page cache"
            last = now
    finally:
        eng.dispose()


def test_the_default_order_rotates_so_the_assertion_above_means_something():
    eng = _engine()
    try:
        _checkout_return(eng, 3)
        seen = set()
        for _ in range(6):
            f = eng.raw_connection()
            seen.add(id(f.dbapi_connection))
            f.close()
        assert len(seen) == 3, "first in, first out hands every idle connection a turn"
    finally:
        eng.dispose()


def test_the_collector_ceiling_and_its_slots_count_the_same_under_it():
    eng = _engine(pool_use_lifo=True)
    ceiling = collector_ceiling(POOL + OVERFLOW, _API_MARGIN)
    conns: list = []

    def hold():  # one slot per THREAD: a thread that already holds one is a nested checkout (pool_reserve.py)
        with collector_role():
            conns.append(eng.raw_connection())

    try:
        holders = [threading.Thread(target=hold) for _ in range(ceiling)]
        for h in holders:
            h.start()
        for h in holders:
            h.join(HANG_GUARD_S)
        assert len(conns) == ceiling
        assert eng.pool.reservation()["collector_held"] == ceiling
        with collector_role(), pytest.raises(PoolTimeoutError, match="may not take the last"):
            eng.raw_connection()
        for f in conns:
            f.close()
        assert eng.pool.reservation()["collector_held"] == 0, "every slot came back with its connection"
    finally:
        for f in conns:
            f.close()
        eng.dispose()
