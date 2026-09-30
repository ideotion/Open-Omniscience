"""pool_watch must not keep a row for a connection that is no longer checked out.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Reproduced 2026-09-30 against SQLAlchemy 2.1.1 (rank 12 of the field diagnostics, the "one
API-thread checkout held for the whole process life"): the register was keyed on
``id(dbapi_connection)``, but SQLAlchemy clears ``record.dbapi_connection`` BEFORE it fires
``checkin`` when a connection is invalidated, and a detached connection never checks in at
all. Either left an immortal row whose age grew without bound, and every WAL diagnosis
(the checkpoint record's ``readers``, the storage guard's pin report) then named it as the
oldest holder. The table is now keyed on the connection RECORD and verified at read time.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import create_engine, event

from src.database import pool_watch


@pytest.fixture()
def eng(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 'pw.db'}", future=True)

    @event.listens_for(e, "connect")
    def _p(dbapi, _rec):
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    assert pool_watch.register(e) is True
    yield e
    e.dispose()


def test_a_normal_checkout_is_listed_then_dropped_on_checkin(eng):
    c = eng.connect()
    try:
        rows = pool_watch.checked_out()
        assert [r["thread"] for r in rows] == [threading.current_thread().name]
        assert rows[0]["ident"] == threading.get_ident()
        assert rows[0]["age_s"] >= 0
    finally:
        c.close()
    assert pool_watch.checked_out() == []


def test_an_invalidated_connection_leaves_no_phantom_row(eng):
    c = eng.connect()
    c.exec_driver_sql("SELECT 1")
    assert len(pool_watch.checked_out()) == 1
    c.invalidate()
    c.close()
    assert pool_watch.checked_out() == [], "an invalidated checkout must not stay 'oldest' forever"


def test_a_detached_connection_leaves_no_phantom_row(eng):
    c = eng.connect()
    c.exec_driver_sql("SELECT 1")
    c.detach()
    # a detached connection has left the pool for good: it is not a pooled checkout any more
    assert pool_watch.checked_out() == []
    c.close()
    assert pool_watch.checked_out() == []


def test_a_row_whose_record_is_no_longer_out_is_pruned_at_read_time_and_counted(eng):
    c = eng.connect()
    rec = c.connection._connection_record  # the pool's record for this checkout
    assert len(pool_watch.checked_out()) == 1
    before = pool_watch.pruned_total()
    # Simulate a checkin the listeners never saw (a listener attached late): the record
    # says it is no longer out, while the table still remembers it.
    rec.fairy_ref = None
    assert pool_watch.checked_out() == []
    assert pool_watch.pruned_total() == before + 1
    c.close()


def test_registering_the_same_engine_twice_does_not_double_the_rows(eng):
    assert pool_watch.register(eng) is False, "registration is idempotent per engine"
    c = eng.connect()
    try:
        assert len(pool_watch.checked_out()) == 1
    finally:
        c.close()


def test_stacks_are_captured_on_demand_for_a_live_thread_only(eng):
    def here_marker():
        return pool_watch.stacks_for([threading.get_ident()])

    stacks = here_marker()
    assert any("here_marker" in line for line in stacks[threading.get_ident()])
    assert pool_watch.stacks_for([987654321]) == {}, "an exited thread has no entry"


def test_the_oldest_checkout_comes_first(eng):
    a = eng.connect()
    b = eng.connect()
    try:
        rows = pool_watch.checked_out()
        assert len(rows) == 2
        assert rows[0]["age_s"] >= rows[1]["age_s"]
    finally:
        a.close()
        b.close()
