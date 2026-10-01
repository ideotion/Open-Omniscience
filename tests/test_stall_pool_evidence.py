"""The stall record files the connection pool as it stands (audit 16, rank 7 item 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A request that waited its 30 s pool timeout was waiting for exactly the holders the pool had
at that moment, and the field bundles could not say whose they were. The stall record now
carries them: thread, route (the request the thread was serving at checkout), age, and whether
it is a collector slot, beside the pool's own size and the reservation's count. Evidence only,
never a statement text or a stack, and an unreadable instrument is a stated gap, never a crash.
"""

from __future__ import annotations

import pytest

from src.database import pool_watch
from src.database import session as dbsession
from src.monitoring import stall_forensics as sf


@pytest.fixture(autouse=True)
def _clean():
    sf._reset_for_tests()
    pool_watch._reset_for_tests()
    yield
    sf._reset_for_tests()
    pool_watch._reset_for_tests()


def test_the_pool_evidence_names_the_holder_with_its_route_age_and_the_pools_own_counts():
    token = pool_watch.set_endpoint("GET /api/things")
    conn = dbsession.engine.connect()
    try:
        ev = sf._pool_evidence()
    finally:
        conn.close()
        pool_watch.reset_endpoint(token)
    assert ev["available"] is True and ev["attached"] is True
    assert ev["checked_out"] >= 1
    holder = next(h for h in ev["holders"] if h["endpoint"] == "GET /api/things")
    assert set(holder) == {"thread", "endpoint", "collector", "age_s"}, "no statement text, no stack"
    assert holder["collector"] is False and holder["age_s"] >= 0
    pool = dbsession.engine.pool
    assert ev["pool_size"] == pool.size() + pool._max_overflow
    assert isinstance(ev["reservation"], dict) and ev["reservation"], "the reservation's own counts ride along"
    assert isinstance(ev["invalidated_total"], int)


def test_only_the_oldest_rows_are_named_and_the_count_of_all_is_carried_beside_them(monkeypatch):
    monkeypatch.setattr(sf, "_POOL_ROWS", 2)
    conns = [dbsession.engine.connect() for _ in range(3)]
    try:
        ev = sf._pool_evidence()
    finally:
        for c in conns:
            c.close()
    assert ev["checked_out"] >= 3 and len(ev["holders"]) == 2


def test_a_pool_that_is_not_watched_says_so_instead_of_an_empty_list(monkeypatch):
    monkeypatch.setattr(pool_watch, "is_registered", lambda: False)
    assert sf._pool_evidence() == {"available": True, "attached": False}


def test_an_unreadable_instrument_is_a_stated_gap_and_never_a_crash(monkeypatch):
    def broken():
        raise RuntimeError("the registry is gone")

    monkeypatch.setattr(pool_watch, "checked_out", broken)
    assert sf._pool_evidence() == {"available": False, "reason": "RuntimeError"}


def test_the_filed_stall_carries_the_pool_evidence(monkeypatch):
    monkeypatch.setattr(sf, "_gate_evidence", lambda: {"available": True, "held": False, "waiters": 0, "max_wait_s": 0.0})
    monkeypatch.setattr(sf, "_loop_evidence", lambda route: {"available": True, "overlapped": False, "n_events_checked": 3})
    monkeypatch.setattr(sf, "_statement_evidence", lambda ms: {"available": True, "slow_statement": None})
    monkeypatch.setattr(sf, "_pool_evidence", lambda: {"available": True, "attached": True, "checked_out": 12, "holders": []})
    rec = sf.note_stall("GET /api/scheduler/activity", 500, 40000.0)
    assert rec is not None
    assert rec["evidence"]["pool"] == {"available": True, "attached": True, "checked_out": 12, "holders": []}
