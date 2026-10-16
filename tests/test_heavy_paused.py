"""While the write-ahead log is pinned, a heavy read that would START a scan does not: it answers 503, named, and the scan is never run.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 16 Oct 2026 bundles: the pin reports named the trending-windows and briefing trending scans as the readers keeping the
checkpoint from finishing, and Home's 15 s poll started a new one each time the last ended. Starting no new scan while the log latch
is engaged lets the drain finish. These tests attack the NEGATIVE space: a paused request must not run its compute, must not leave a
flight or a cache entry behind, and must not be a 429 or a degraded payload that a caller mistakes for an answer; and what must NOT
pause (a cached answer, a duplicate of a flight already running, a drive-only latch, a guard that is off) must keep working.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.scheduler.storage_guard as sg
from src.api import heavy, insights
from src.api.heavy import HeavyBusy, HeavyPaused, guarded_read, run_heavy
from src.scheduler.storage_guard import GIB, StorageGuard, storage_guard

GUARD = storage_guard


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """A released latch before and after every test (the guard is process-global), fast waits, an empty read cache."""
    monkeypatch.delenv("OO_STORAGE_GUARD", raising=False)
    monkeypatch.setenv("OO_HEAVY_ACQUIRE_TIMEOUT_S", "0.3")
    monkeypatch.setenv("OO_HEAVY_FOLLOWER_WAIT_S", "0.3")
    monkeypatch.setattr(sg, "supervisor_running", lambda: True)  # the supervisor releases the latch; no thread is started here
    GUARD._reset_for_tests()
    heavy._reset_for_tests()
    insights._read_cache.clear()
    yield
    GUARD._reset_for_tests()
    heavy._reset_for_tests()
    insights._read_cache.clear()


def _observe(g: StorageGuard, *, wal_gib: float = 0.0, free_gib: float = 300.0) -> bool:
    return g.observe(
        wal_bytes=int(wal_gib * GIB), corpus_bytes=10 * GIB, disk_free_bytes=int(free_gib * GIB), disk_total_bytes=500 * GIB
    )


def pin_the_log(g: StorageGuard = GUARD) -> None:
    for _ in range(4):
        _observe(g, wal_gib=3.0)
    assert g.wal_engaged() and g.kind() == "wal"


def drain_the_log(g: StorageGuard = GUARD) -> None:
    for _ in range(4):
        _observe(g, wal_gib=0.0)
    assert not g.wal_engaged()


def fill_the_drive(g: StorageGuard = GUARD) -> None:
    for _ in range(4):
        _observe(g, wal_gib=0.0, free_gib=0.1)
    assert g.kind() == "disk" and not g.wal_engaged()


def _session():
    return sessionmaker(bind=create_engine("sqlite://"))()


class Counter:
    def __init__(self, value="answer"):
        self.calls = 0
        self.value = value

    def __call__(self):
        self.calls += 1
        return self.value


# --------------------------------------------------------------------------- #
#  the accessor: the log latch alone, whatever kind() names first
# --------------------------------------------------------------------------- #
def test_wal_engaged_is_the_log_latch_alone_and_follows_the_switch():
    g = StorageGuard()
    assert not g.wal_engaged()
    pin_the_log(g)
    assert g.wal_engaged()
    for _ in range(4):
        _observe(g, wal_gib=3.0, free_gib=0.1)
    assert g.kind() == "disk" and g.wal_engaged(), "kind() names the drive first; the log latch is still engaged"
    h = StorageGuard()
    fill_the_drive(h)
    assert not h.wal_engaged(), "a drive-only latch is not a pinned log"


def test_wal_engaged_is_false_when_the_guard_is_switched_off(monkeypatch):
    g = StorageGuard()
    pin_the_log(g)
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    assert not g.wal_engaged()


# --------------------------------------------------------------------------- #
#  the pause: no compute, a named 503, nothing left behind
# --------------------------------------------------------------------------- #
def test_a_pinned_log_pauses_a_scan_that_would_start_and_its_compute_is_never_called():
    pin_the_log()
    compute = Counter()
    with pytest.raises(HeavyPaused) as caught:
        run_heavy("k", compute)
    assert compute.calls == 0, "the point: no new scan while the log is pinned"
    exc = caught.value
    assert isinstance(exc, HTTPException) and exc.status_code == 503
    # the wire contract is spelled out here, not imported: the keyword lane's Home back-off reads the marker header
    assert exc.detail == "Paused while the write-ahead log is pinned; resumes by itself."
    assert exc.headers == {"Retry-After": "10", "X-OO-Paused": "wal"}
    status = heavy.status()
    assert status["counters"]["paused"] == 1 and status["counters"]["runs"] == 0
    assert status["in_flight_keys"] == 0, "a pause leaves no flight for followers to wait on"


def test_the_retry_after_is_the_guards_own_drain_cadence(monkeypatch):
    monkeypatch.setattr(sg, "DRAIN_EVERY_S", 7.0)
    pin_the_log()
    with pytest.raises(HeavyPaused) as caught:
        run_heavy("k", Counter())
    assert caught.value.headers["Retry-After"] == "7"


def test_the_pause_ends_by_itself_when_the_log_drains():
    pin_the_log()
    with pytest.raises(HeavyPaused):
        run_heavy("k", Counter())
    drain_the_log()
    compute = Counter(42)
    assert run_heavy("k", compute) == 42 and compute.calls == 1


def test_a_drive_only_latch_does_not_pause_a_scan():
    fill_the_drive()
    compute = Counter()
    assert run_heavy("k", compute) == "answer" and compute.calls == 1


def test_both_latches_pause_a_scan_though_kind_names_the_drive():
    for _ in range(4):
        _observe(GUARD, wal_gib=3.0, free_gib=0.1)
    assert GUARD.kind() == "disk", "the case a kind()==wal comparison would miss"
    compute = Counter()
    with pytest.raises(HeavyPaused):
        run_heavy("k", compute)
    assert compute.calls == 0


def test_the_operators_resume_anyway_forces_collection_and_does_not_unpause_a_scan(monkeypatch):
    pin_the_log()
    monkeypatch.setattr(GUARD, "_readings", lambda: {"wal_bytes": 3 * GIB, "disk_free_bytes": 300 * GIB})
    assert GUARD.override()["overridden"] is True
    assert GUARD.admit() is None, "collection is admitted: that is what the override is for"
    compute = Counter()
    with pytest.raises(HeavyPaused):
        run_heavy("k", compute)
    assert compute.calls == 0


def test_a_latch_nobody_is_sampling_pauses_nothing_because_a_pause_must_not_outlive_its_cause(monkeypatch):
    pin_the_log()
    monkeypatch.setattr(sg, "supervisor_running", lambda: False)
    compute = Counter()
    assert run_heavy("k", compute) == "answer" and compute.calls == 1


def test_a_guard_that_is_off_pauses_nothing(monkeypatch):
    pin_the_log()
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    compute = Counter()
    assert run_heavy("k", compute) == "answer" and compute.calls == 1


# --------------------------------------------------------------------------- #
#  what must keep working
# --------------------------------------------------------------------------- #
def test_a_duplicate_of_a_scan_already_running_shares_it_and_is_not_paused(monkeypatch):
    monkeypatch.setenv("OO_HEAVY_FOLLOWER_WAIT_S", "5")
    inside, go = threading.Event(), threading.Event()

    def slow():
        inside.set()
        assert go.wait(5)
        return "shared"

    out: dict[str, object] = {}
    leader = threading.Thread(target=lambda: out.__setitem__("leader", run_heavy("k", slow)))
    leader.start()
    assert inside.wait(5)
    pin_the_log()  # engaged AFTER the leader started its scan
    follower = threading.Thread(target=lambda: out.__setitem__("follower", run_heavy("k", Counter("never"))))
    follower.start()
    follower.join(0.3)
    assert follower.is_alive(), "the follower waits for the running scan"
    go.set()
    leader.join(5)
    follower.join(5)
    assert out == {"leader": "shared", "follower": "shared"}
    counters = heavy.status()["counters"]
    assert counters["paused"] == 0 and counters["shared"] == 1 and counters["runs"] == 1


def test_a_different_key_is_paused_while_another_scan_runs():
    inside, go = threading.Event(), threading.Event()

    def slow():
        inside.set()
        assert go.wait(5)

    leader = threading.Thread(target=lambda: run_heavy("a", slow))
    leader.start()
    assert inside.wait(5)
    pin_the_log()
    compute = Counter()
    try:
        with pytest.raises(HeavyPaused):
            run_heavy("b", compute)
        assert compute.calls == 0
    finally:
        go.set()
        leader.join(5)


def test_a_cached_answer_is_still_served_while_the_log_is_pinned():
    db = _session()
    compute = Counter({"n": 1})
    first = insights._deadlined(db, "cached-key", compute)
    assert first["cached"] is False and compute.calls == 1
    pin_the_log()
    again = insights._deadlined(db, "cached-key", compute)
    assert again["cached"] is True and again["n"] == 1 and compute.calls == 1, "a cache hit never reaches run_heavy"


# --------------------------------------------------------------------------- #
#  the callers: the pause passes through unchanged, is never a 429 or a degraded payload, and is never cached
# --------------------------------------------------------------------------- #
def test_deadlined_passes_the_pause_through_and_caches_nothing_for_it():
    db = _session()
    pin_the_log()
    compute = Counter({"n": 1})
    degraded = Counter({"degraded": True})
    with pytest.raises(HeavyPaused):
        insights._deadlined(db, "cached-key", compute, on_busy=degraded, on_timeout=degraded)
    assert compute.calls == 0 and degraded.calls == 0, "a pause is not busy: no degraded payload stands in for the answer"
    drain_the_log()
    out = insights._deadlined(db, "cached-key", compute)
    assert out["cached"] is False and out["n"] == 1 and compute.calls == 1, "nothing was cached while it was paused"
    assert insights._deadlined(db, "cached-key", compute)["cached"] is True


def test_guarded_read_passes_the_pause_through_and_calls_neither_fallback():
    db = _session()
    pin_the_log()
    busy, timeout, compute = Counter("busy"), Counter("timeout"), Counter()
    with pytest.raises(HeavyPaused):
        guarded_read(db, "k", compute, on_busy=busy, on_timeout=timeout)
    assert (busy.calls, timeout.calls, compute.calls) == (0, 0, 0)


def test_a_busy_server_is_still_a_429_and_not_a_pause():
    db = _session()

    def raising():
        raise HeavyBusy("busy")

    with pytest.raises(HTTPException) as caught:
        guarded_read(db, "k", raising)
    assert caught.value.status_code == 429 and not isinstance(caught.value, HeavyPaused)


def test_the_router_answers_503_with_the_header_and_the_named_text():
    app = FastAPI()
    db = _session()
    compute = Counter({"ok": True})

    @app.get("/heavy")
    def _route():
        return guarded_read(db, "route", compute)

    client = TestClient(app)
    pin_the_log()
    response = client.get("/heavy")
    assert response.status_code == 503
    assert response.json() == {"detail": "Paused while the write-ahead log is pinned; resumes by itself."}
    assert response.headers["retry-after"] == "10" and response.headers["x-oo-paused"] == "wal"
    assert compute.calls == 0
    drain_the_log()
    assert client.get("/heavy").json() == {"ok": True} and compute.calls == 1


# --------------------------------------------------------------------------- #
#  the background briefing rebuild waits for the guard before it scans
# --------------------------------------------------------------------------- #
def test_the_briefing_rebuild_waits_while_the_guard_is_engaged_and_then_builds_once(monkeypatch):
    import contextlib

    import src.briefing.service as service
    import src.database.session as session_mod
    import src.scheduler.storage_guard as sg

    released, waiting = threading.Event(), threading.Event()
    events: list[str] = []

    class FakeGuard:
        def wait_if_engaged(self, *a, **k):
            events.append("wait")
            waiting.set()
            assert released.wait(5)
            events.append("released")
            return True

    @contextlib.contextmanager
    def scope():
        yield object()

    monkeypatch.setattr(sg, "storage_guard", FakeGuard())
    monkeypatch.setattr(session_mod, "session_scope", scope)
    monkeypatch.setattr(service, "refresh_briefing", lambda session, on_progress=None: events.append("build"))
    worker = threading.Thread(target=service._bg_refresh)
    worker.start()
    assert waiting.wait(5)
    time.sleep(0.2)
    assert events == ["wait"], "no scan starts while the guard is engaged"
    released.set()
    worker.join(5)
    assert events == ["wait", "released", "build"]
    assert service._refresh_status() == {"refreshing": False}
