"""While the write-ahead log is pinned, the heavy reads on an explicit list do not START a scan: they answer 503, named, and the scan is never run.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 16 Oct 2026 bundles: the pin reports named the trending-windows and briefing trending scans as the readers keeping the
checkpoint from finishing, and Home's 15 s poll started a new one each time the last ended. Starting no new one of THOSE while the
log latch is engaged lets the drain finish. A pin has lasted hours, so everything not on the list (search, the library, link analysis,
the integrity reads) keeps running under its own statement deadline, and a new heavy route is not paused until someone lists it.
These tests attack the NEGATIVE space: a paused request must not run its compute, must not leave a flight or a cache entry behind,
and must not be a 429 or a degraded payload that a caller mistakes for an answer; and what must NOT pause (a name off the list, a
cached answer, a duplicate of a flight already running, a drive-only latch, a guard that is off) must keep working.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

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
ROOT = Path(__file__).resolve().parents[1]

# a name on the list, and names that are real heavy reads that are NOT on it (the keys the routes build, so a rename shows here)
LISTED = "trending-windows"
UNLISTED = "omni|some search"


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


@pytest.fixture()
def client(tmp_path):
    """The real app on an isolated database: the routes the pause is about, not stand-ins for them."""
    from src.api.main import app
    from src.database.models import Base
    from src.database.session import get_db

    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)

    def _db():
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


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
#  the list: explicit, in one place, one reason each; everything else keeps running
# --------------------------------------------------------------------------- #
LIST = {
    "trending-windows", "trending", "map-coverage", "server-locations", "card-audit",
}


def test_the_list_is_what_it_was_ruled_to_be_and_every_entry_says_why_in_one_line():
    assert set(heavy.PAUSED_WHILE_WAL_PINNED) == LIST, "adding or removing a paused compute is a deliberate change to this test too"
    for name, reason in heavy.PAUSED_WHILE_WAL_PINNED.items():
        assert name and "|" not in name and name == name.strip(), name
        assert isinstance(reason, str) and reason.strip() and "\n" not in reason and len(reason) <= 200, name


def test_every_listed_name_is_the_name_a_real_route_gives_its_flight():
    """A name that nothing uses pauses nothing: it is looked for as a literal first argument of ``_ckey(``/``guarded_read(`` in the API."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src/api").rglob("*.py"))
    for name in heavy.PAUSED_WHILE_WAL_PINNED:
        found = re.search(r'(?:_ckey|guarded_read)\(\s*(?:db,\s*)?"' + re.escape(name) + '"', text)
        assert found, f"{name}: no route builds a flight with this name"


@pytest.mark.parametrize("name", sorted(LIST))
def test_a_listed_name_is_paused_whatever_follows_it_in_the_key(name):
    pin_the_log()
    compute = Counter()
    with pytest.raises(HeavyPaused):
        run_heavy(f"{name}|days=7|bind=1", compute)
    assert compute.calls == 0


@pytest.mark.parametrize(
    "key",
    [
        "omni|a search the omnibar sent",
        "library-history:articles:30|bind=1",
        "source-profile|id=3",
        "lunar-correlation|days=30",
        "trending-windows-but-not-quite|x",
        "TRENDING|x",
        "a-new-heavy-route|x",
        "trending:x|y",
        "card-audit-preflight|bind=1",
        "",
    ],
)
def test_a_name_that_is_not_on_the_list_runs_while_the_log_is_pinned(key):
    pin_the_log()
    compute = Counter()
    assert run_heavy(key, compute) == "answer" and compute.calls == 1
    assert heavy.status()["counters"]["paused"] == 0


def test_a_search_during_an_engaged_latch_runs_and_is_not_paused():
    """The omnibar's own read, through the real guard: it must never blank, and a pause is a 503 that would blank it."""
    db = _session()
    pin_the_log()
    compute = Counter({"groups": ["x"]})
    assert guarded_read(db, "omni|some query", compute, on_busy=Counter("d"), on_timeout=Counter("d")) == {"groups": ["x"]}
    assert compute.calls == 1 and heavy.status()["counters"]["paused"] == 0


def test_the_real_routes_a_listed_name_is_paused_and_a_search_or_an_unlisted_read_is_not(client):
    pin_the_log()
    for path in ("/api/insights/trending-windows", "/api/insights/trending", "/api/insights/map-coverage", "/api/insights/server-locations"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert response.headers["x-oo-paused"] == "wal" and response.headers["retry-after"] == "10", path
        assert response.json() == {"detail": "Paused while the write-ahead log is pinned; resumes by itself."}, path
    search = client.get("/api/search/omni", params={"q": "quantum"})
    assert search.status_code == 200 and "degraded" not in search.json(), "the omnibar answers while the log is pinned"
    assert client.get("/api/insights/top").status_code == 200, "a heavy read that is not on the list keeps running"
    drain_the_log()
    assert client.get("/api/insights/trending-windows").status_code == 200, "the pause ended by itself"


# --------------------------------------------------------------------------- #
#  the pause: no compute, a named 503, nothing left behind
# --------------------------------------------------------------------------- #
def test_a_pinned_log_pauses_a_scan_that_would_start_and_its_compute_is_never_called():
    pin_the_log()
    compute = Counter()
    with pytest.raises(HeavyPaused) as caught:
        run_heavy(LISTED, compute)
    assert compute.calls == 0, "the point: no new scan while the log is pinned"
    exc = caught.value
    assert isinstance(exc, HTTPException) and exc.status_code == 503
    # the wire contract is spelled out here, not imported: the header is for a client to tell the pause from a failure (nothing in this tree reads it yet)
    assert exc.detail == "Paused while the write-ahead log is pinned; resumes by itself."
    assert exc.headers == {"Retry-After": "10", "X-OO-Paused": "wal"}
    status = heavy.status()
    assert status["counters"]["paused"] == 1 and status["counters"]["runs"] == 0
    assert status["in_flight_keys"] == 0, "a pause leaves no flight for followers to wait on"


def test_the_retry_after_is_the_guards_own_drain_cadence(monkeypatch):
    monkeypatch.setattr(sg, "DRAIN_EVERY_S", 7.0)
    pin_the_log()
    with pytest.raises(HeavyPaused) as caught:
        run_heavy(LISTED, Counter())
    assert caught.value.headers["Retry-After"] == "7"


def test_the_pause_ends_by_itself_when_the_log_drains():
    pin_the_log()
    with pytest.raises(HeavyPaused):
        run_heavy(LISTED, Counter())
    drain_the_log()
    compute = Counter(42)
    assert run_heavy(LISTED, compute) == 42 and compute.calls == 1


def test_a_drive_only_latch_does_not_pause_a_scan():
    fill_the_drive()
    compute = Counter()
    assert run_heavy(LISTED, compute) == "answer" and compute.calls == 1


def test_both_latches_pause_a_scan_though_kind_names_the_drive():
    for _ in range(4):
        _observe(GUARD, wal_gib=3.0, free_gib=0.1)
    assert GUARD.kind() == "disk", "the case a kind()==wal comparison would miss"
    compute = Counter()
    with pytest.raises(HeavyPaused):
        run_heavy(LISTED, compute)
    assert compute.calls == 0


def test_the_operators_resume_anyway_forces_collection_and_does_not_unpause_a_scan(monkeypatch):
    pin_the_log()
    monkeypatch.setattr(GUARD, "_readings", lambda: {"wal_bytes": 3 * GIB, "disk_free_bytes": 300 * GIB})
    assert GUARD.override()["overridden"] is True
    assert GUARD.admit() is None, "collection is admitted: that is what the override is for"
    compute = Counter()
    with pytest.raises(HeavyPaused):
        run_heavy(LISTED, compute)
    assert compute.calls == 0


def test_a_latch_nobody_is_sampling_pauses_nothing_because_a_pause_must_not_outlive_its_cause(monkeypatch):
    pin_the_log()
    monkeypatch.setattr(sg, "supervisor_running", lambda: False)
    compute = Counter()
    assert run_heavy(LISTED, compute) == "answer" and compute.calls == 1


def test_a_guard_that_is_off_pauses_nothing(monkeypatch):
    pin_the_log()
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    compute = Counter()
    assert run_heavy(LISTED, compute) == "answer" and compute.calls == 1


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
    leader = threading.Thread(target=lambda: out.__setitem__("leader", run_heavy(LISTED, slow)))
    leader.start()
    assert inside.wait(5)
    pin_the_log()  # engaged AFTER the leader started its scan
    follower = threading.Thread(target=lambda: out.__setitem__("follower", run_heavy(LISTED, Counter("never"))))
    follower.start()
    follower.join(0.3)
    assert follower.is_alive(), "the follower waits for the running scan"
    go.set()
    leader.join(5)
    follower.join(5)
    assert out == {"leader": "shared", "follower": "shared"}
    counters = heavy.status()["counters"]
    assert counters["paused"] == 0 and counters["shared"] == 1 and counters["runs"] == 1


def test_a_different_listed_name_is_paused_while_another_scan_runs():
    inside, go = threading.Event(), threading.Event()

    def slow():
        inside.set()
        assert go.wait(5)

    leader = threading.Thread(target=lambda: run_heavy("some-other-scan", slow))
    leader.start()
    assert inside.wait(5)
    pin_the_log()
    compute = Counter()
    try:
        with pytest.raises(HeavyPaused):
            run_heavy("trending", compute)
        assert compute.calls == 0
    finally:
        go.set()
        leader.join(5)


def test_a_cached_answer_is_still_served_while_the_log_is_pinned():
    db = _session()
    compute = Counter({"n": 1})
    first = insights._deadlined(db, "trending-windows|cached", compute)
    assert first["cached"] is False and compute.calls == 1
    pin_the_log()
    again = insights._deadlined(db, "trending-windows|cached", compute)
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
        insights._deadlined(db, "trending-windows|cached", compute, on_busy=degraded, on_timeout=degraded)
    assert compute.calls == 0 and degraded.calls == 0, "a pause is not busy: no degraded payload stands in for the answer"
    drain_the_log()
    out = insights._deadlined(db, "trending-windows|cached", compute)
    assert out["cached"] is False and out["n"] == 1 and compute.calls == 1, "nothing was cached while it was paused"
    assert insights._deadlined(db, "trending-windows|cached", compute)["cached"] is True


def test_guarded_read_passes_the_pause_through_and_calls_neither_fallback():
    db = _session()
    pin_the_log()
    busy, timeout, compute = Counter("busy"), Counter("timeout"), Counter()
    with pytest.raises(HeavyPaused):
        guarded_read(db, "card-audit", compute, on_busy=busy, on_timeout=timeout)
    assert (busy.calls, timeout.calls, compute.calls) == (0, 0, 0)


def test_a_busy_server_is_still_a_429_and_not_a_pause():
    db = _session()

    def raising():
        raise HeavyBusy("busy")

    with pytest.raises(HTTPException) as caught:
        guarded_read(db, "card-audit", raising)
    assert caught.value.status_code == 429 and not isinstance(caught.value, HeavyPaused)


def test_the_router_answers_503_with_the_header_and_the_named_text():
    app = FastAPI()
    db = _session()
    compute = Counter({"ok": True})

    @app.get("/heavy")
    def _route():
        return guarded_read(db, "card-audit", compute)

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
#  the one condition every pause asks
# --------------------------------------------------------------------------- #
def test_log_pause_in_force_is_the_log_latch_and_a_running_supervisor_and_nothing_else(monkeypatch):
    assert sg.log_pause_in_force() is False
    pin_the_log()
    assert sg.log_pause_in_force() is True
    monkeypatch.setattr(sg, "supervisor_running", lambda: False)
    assert sg.log_pause_in_force() is False, "nobody is sampling: a pause must not outlive its cause"
    monkeypatch.setattr(sg, "supervisor_running", lambda: True)
    drain_the_log()
    fill_the_drive()
    assert sg.log_pause_in_force() is False, "a full drive does not hurt a read"
    pin_the_log()
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    assert sg.log_pause_in_force() is False, "a guard that is off pauses nothing"


def test_a_call_that_saw_a_flight_running_cannot_start_a_scan_if_that_flight_ends_before_it_registers(monkeypatch):
    """The two-hold race: the old code read 'is a flight running' under one hold of the lock and registered under a second. A call that
    found a flight running skipped the pause; if the flight ended between the holds it became a leader and started a scan on a pinned
    log. The decision and the registration are one hold now, so the call is either a follower (and starts nothing) or a leader that was
    asked the pause, and a hook that ends the flight between any two holds changes neither."""
    real = heavy._LOCK
    leader_go, leader_done = threading.Event(), threading.Event()
    follower_name = "the-follower"
    entries = {"n": 0}

    class EndTheFlightBetweenHolds:
        def __enter__(self):
            if threading.current_thread().name == follower_name:
                entries["n"] += 1
                if entries["n"] == 2:  # the follower's SECOND hold: only the old code has one
                    leader_go.set()
                    leader_done.wait(5)
            return real.__enter__()

        def __exit__(self, *exc):
            return real.__exit__(*exc)

    inside = threading.Event()

    def slow():
        inside.set()
        assert leader_go.wait(5)
        return "the leader's result"

    def lead():
        run_heavy(LISTED, slow)
        leader_done.set()

    monkeypatch.setattr(heavy, "_LOCK", EndTheFlightBetweenHolds())
    monkeypatch.setenv("OO_HEAVY_FOLLOWER_WAIT_S", "5")
    leader = threading.Thread(target=lead, name="the-leader")
    leader.start()
    assert inside.wait(5)
    pin_the_log()
    compute = Counter("a new scan")
    out: dict[str, object] = {}

    def follow():
        try:
            out["got"] = run_heavy(LISTED, compute)
        except Exception as exc:  # noqa: BLE001 - recorded, asserted below
            out["raised"] = type(exc)

    follower = threading.Thread(target=follow, name=follower_name)
    follower.start()
    time.sleep(0.2)
    leader_go.set()  # the flight ends whichever way the follower is waiting
    follower.join(10)
    leader.join(10)
    assert compute.calls == 0, "no scan was started on a pinned log by a call that had seen one running"


# --------------------------------------------------------------------------- #
#  the background briefing rebuild stands aside while the log is pinned, and the view says so
# --------------------------------------------------------------------------- #
def _drive_the_rebuild(monkeypatch, *, built=None):
    """Start the real background rebuild with the real guard (pinned or not by the test); the scan itself is replaced by a recorder.
    Returns the list of events."""
    import contextlib

    import src.briefing.service as service
    import src.database.session as session_mod

    events: list[str] = []

    @contextlib.contextmanager
    def scope():
        yield object()

    def build(session, on_progress=None):
        events.append("build")
        if built is not None:
            built.wait(5)

    monkeypatch.setattr(session_mod, "session_scope", scope)
    monkeypatch.setattr(service, "refresh_briefing", build)
    monkeypatch.setitem(service._refresh_state, "refreshing", False)
    monkeypatch.setitem(service._refresh_state, "paused", "")
    service._ensure_background_refresh()
    return events


def _until(condition, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_a_rebuild_while_the_log_is_pinned_scans_nothing_ends_at_once_and_the_view_says_paused(monkeypatch):
    import src.briefing.service as service

    pin_the_log()
    events = _drive_the_rebuild(monkeypatch)
    assert _until(lambda: not service._refresh_state["refreshing"]), "the thread ends: nothing is parked behind a pin that lasts hours"
    assert events == [], "no scan starts while the log is pinned"
    # additive: ``refreshing`` stays the key the UI already reads, and it is false so the Refresh button works and Home stops its fast poll
    assert service._refresh_status() == {"refreshing": False, "paused": "wal"}


def test_the_refresh_button_works_again_at_once_and_the_rebuild_runs_when_the_pin_has_drained(monkeypatch):
    import src.briefing.service as service

    pin_the_log()
    events = _drive_the_rebuild(monkeypatch)
    assert _until(lambda: not service._refresh_state["refreshing"])
    drain_the_log()
    assert service._refresh_status() == {"refreshing": False}, "the field is read against the guard each time: it never outlives the pin"
    service._ensure_background_refresh()  # the next poll that finds the cache stale
    assert _until(lambda: events == ["build"] and not service._refresh_state["refreshing"])
    assert service._refresh_status() == {"refreshing": False}


def test_a_drive_only_latch_does_not_hold_the_rebuild_back(monkeypatch):
    import src.briefing.service as service

    fill_the_drive()
    events = _drive_the_rebuild(monkeypatch)
    assert _until(lambda: events == ["build"] and not service._refresh_state["refreshing"])
    assert service._refresh_status() == {"refreshing": False}, "a full drive does not hurt a read, so there is nothing to say"


def test_a_pinned_log_with_no_supervisor_does_not_hold_the_rebuild_back(monkeypatch):
    import src.briefing.service as service

    pin_the_log()
    monkeypatch.setattr(sg, "supervisor_running", lambda: False)
    events = _drive_the_rebuild(monkeypatch)
    assert _until(lambda: events == ["build"] and not service._refresh_state["refreshing"])


def test_a_rebuild_that_runs_says_progress_and_never_paused(monkeypatch):
    import src.briefing.service as service

    release = threading.Event()
    events = _drive_the_rebuild(monkeypatch, built=release)
    assert _until(lambda: events == ["build"])
    assert service._refresh_status() == {"refreshing": True, "progress": {"done": 0, "total": 0}}
    release.set()
    assert _until(lambda: not service._refresh_state["refreshing"])


def test_a_stale_paused_name_is_not_shown_once_the_pin_has_ended_or_while_a_rebuild_runs_unpaused(monkeypatch):
    import src.briefing.service as service

    monkeypatch.setitem(service._refresh_state, "paused", "wal")
    monkeypatch.setitem(service._refresh_state, "refreshing", True)
    assert "paused" not in service._refresh_status(), "the guard says the log is not pinned"
    assert service._refresh_state["paused"] == "", "and the stale name is dropped, not merely hidden"


def test_a_guard_that_cannot_be_read_pauses_nothing_and_the_view_still_answers(monkeypatch):
    import src.briefing.service as service

    def broken():
        raise RuntimeError("the guard failed")

    monkeypatch.setattr(sg, "log_pause_in_force", broken)
    pin_the_log()
    events = _drive_the_rebuild(monkeypatch)
    assert _until(lambda: events == ["build"] and not service._refresh_state["refreshing"])
    assert service._refresh_status() == {"refreshing": False}
