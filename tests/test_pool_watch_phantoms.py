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
    """A checkin the listeners never saw (a listener attached late, here: detached for the
    return) leaves a row for a record that is back in the pool. The pool's own state is left
    untouched: the connection really is checked in, and the table still remembers it."""
    c = eng.connect()
    assert len(pool_watch.checked_out()) == 1
    before = pool_watch.pruned_total()
    event.remove(eng, "checkin", pool_watch._on_checkin)
    try:
        c.close()
    finally:
        event.listen(eng, "checkin", pool_watch._on_checkin)
    assert len(pool_watch._LIVE) == 1, "fixture: the checkin listener really did not see the return"
    assert pool_watch.checked_out() == []
    assert pool_watch.pruned_total() == before + 1
    assert pool_watch._LIVE == {}


def test_registering_the_same_engine_twice_attaches_each_listener_once(eng):
    def attached(name, fn):
        return sum(1 for f in getattr(eng.pool.dispatch, name) if f is fn)

    assert pool_watch.register(eng) is False, "registration is idempotent per engine"
    assert attached("checkout", pool_watch._on_checkout) == 1
    assert attached("checkin", pool_watch._on_checkin) == 1
    assert attached("detach", pool_watch._on_detach) == 1


def test_a_checkout_hook_that_cannot_weak_reference_the_record_still_records_the_row(eng, monkeypatch):
    """The hook is on the pool's hot path: a failure in it must never fail a checkout."""
    import types

    def no_ref(*_a, **_k):
        raise TypeError("cannot create weak reference")

    # only THIS module's name is swapped: SQLAlchemy itself weak-references through the real one
    monkeypatch.setattr(pool_watch, "weakref", types.SimpleNamespace(ref=no_ref))
    c = eng.connect()
    try:
        rows = pool_watch.checked_out()
        assert len(rows) == 1, "an unverifiable row is kept, never silently dropped"
    finally:
        c.close()
    assert pool_watch.checked_out() == []


def test_stacks_are_captured_on_demand_for_a_live_thread_only(eng):
    def here_marker():
        return pool_watch.stacks_for([threading.get_ident()])

    stacks = here_marker()
    assert any("here_marker" in line for line in stacks[threading.get_ident()])
    assert pool_watch.stacks_for([987654321]) == {}, "an exited thread has no entry"


def test_the_oldest_checkout_comes_first(eng):
    """Two threads check out in a known order; the listing must put the older one first (the
    sort is what makes the top row the WAL pinner's candidate)."""
    import time

    held = {}
    release = threading.Event()

    def holder(name):
        c = eng.connect()
        held[name] = c
        release.wait(5.0)
        c.close()

    older = threading.Thread(target=holder, args=("older",), name="pw-older")
    younger = threading.Thread(target=holder, args=("younger",), name="pw-younger")
    older.start()
    while "older" not in held:
        time.sleep(0.005)
    time.sleep(0.05)
    younger.start()
    while "younger" not in held:
        time.sleep(0.005)
    try:
        names = [r["thread"] for r in pool_watch.checked_out()]
        assert names == ["pw-older", "pw-younger"], names
    finally:
        release.set()
        older.join(5.0)
        younger.join(5.0)
    assert pool_watch.checked_out() == []
