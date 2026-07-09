"""The heavy-read admission guard: concurrency cap + single-flight (field test Item 8 P0).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These tests attack the NEGATIVE space (the #591 lesson): the excess request MUST be
refused (not run), a duplicate MUST NOT trigger a second compute, a slow leader MUST NOT
be joined forever, and a different-bind request MUST NOT share a wrong result. They are
deterministic — a background leader signals it is holding the slot / in-compute before the
contending request is issued, so there is no timing race for leadership.
"""

import threading

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.api import heavy
from src.api.heavy import HeavyBusy, flight_key, guarded_read, run_heavy
from src.database.maintenance import StatementTimeout


@pytest.fixture(autouse=True)
def _fast_guard(monkeypatch):
    """Small, fast timeouts + a fresh guard per test (env restored by monkeypatch)."""
    monkeypatch.setenv("OO_HEAVY_CONCURRENCY", "4")
    monkeypatch.setenv("OO_HEAVY_ACQUIRE_TIMEOUT_S", "0.3")
    monkeypatch.setenv("OO_HEAVY_FOLLOWER_WAIT_S", "0.3")
    heavy._reset_for_tests()
    yield
    heavy._reset_for_tests()


def _sqlite_session() -> Session:
    """A real (plain, unencrypted) SQLite session so statement_deadline has a live DBAPI
    connection to attach its progress handler to — no app DB touched."""
    engine = create_engine("sqlite://")
    return sessionmaker(bind=engine)()


# --------------------------------------------------------------------------- #
#  Positive baseline
# --------------------------------------------------------------------------- #


def test_single_request_runs_normally_and_returns_the_real_value():
    assert run_heavy("k", lambda: 42) == 42
    assert heavy.status()["counters"]["runs"] == 1
    assert heavy.status()["in_flight_keys"] == 0  # the flight is retired


# --------------------------------------------------------------------------- #
#  Concurrency cap — the excess MUST be refused, never run (negative space)
# --------------------------------------------------------------------------- #


def test_cap_refuses_the_excess_and_never_runs_it(monkeypatch):
    monkeypatch.setenv("OO_HEAVY_CONCURRENCY", "1")
    heavy._reset_for_tests()

    holding = threading.Event()
    release = threading.Event()
    b_calls = [0]

    def a_compute():
        holding.set()
        release.wait(2)
        return "A"

    def b_compute():
        b_calls[0] += 1  # MUST never happen — the one slot is taken
        return "B"

    res_a = {}
    t_a = threading.Thread(target=lambda: res_a.setdefault("v", run_heavy("A", a_compute)))
    t_a.start()
    assert holding.wait(2), "leader A never took the slot"

    # The single slot is now held by A. A DISTINCT-key request must fast-fail, not pile on.
    with pytest.raises(HeavyBusy):
        run_heavy("B", b_compute)
    assert b_calls[0] == 0, "the refused compute must NEVER run"

    release.set()
    t_a.join(2)
    assert res_a["v"] == "A"
    assert heavy.status()["counters"]["busy"] >= 1


# --------------------------------------------------------------------------- #
#  Single-flight — a duplicate MUST NOT trigger a second compute (negative space)
# --------------------------------------------------------------------------- #


def test_single_flight_collapses_a_duplicate_to_one_compute():
    calls = [0]
    leader_in = threading.Event()
    release = threading.Event()

    def leader_compute():
        calls[0] += 1
        leader_in.set()
        release.wait(2)
        return "R"

    def follower_compute():
        calls[0] += 1  # MUST never run — the leader's result is shared
        return "SHOULD_NOT_RUN"

    res = {}
    t_lead = threading.Thread(target=lambda: res.setdefault("lead", run_heavy("K", leader_compute)))
    t_lead.start()
    assert leader_in.wait(2), "leader never entered compute"

    # The flight for "K" now exists → this is DETERMINISTICALLY a follower.
    def _follow():
        res["follow"] = run_heavy("K", follower_compute)

    t_follow = threading.Thread(target=_follow)
    t_follow.start()
    release.set()  # let the leader finish; the follower shares its result
    t_lead.join(2)
    t_follow.join(2)

    assert res["lead"] == "R"
    assert res["follow"] == "R", "the follower must share the leader's REAL value"
    assert calls[0] == 1, "single-flight must collapse the duplicate to ONE compute"
    assert heavy.status()["counters"]["shared"] >= 1


def test_slow_leader_makes_a_follower_degrade_not_recompute(monkeypatch):
    monkeypatch.setenv("OO_HEAVY_FOLLOWER_WAIT_S", "0.2")
    heavy._reset_for_tests()
    calls = [0]
    leader_in = threading.Event()
    release = threading.Event()

    def leader_compute():
        calls[0] += 1
        leader_in.set()
        release.wait(2)  # slower than the follower's patience
        return "R"

    res = {}
    t_lead = threading.Thread(target=lambda: res.setdefault("lead", run_heavy("K", leader_compute)))
    t_lead.start()
    assert leader_in.wait(2)

    # Follower waits 0.2 s, the leader is still busy → HeavyBusy, NOT a second compute.
    with pytest.raises(HeavyBusy):
        run_heavy("K", lambda: calls.__setitem__(0, calls[0] + 1))
    assert calls[0] == 1, "a follower that gives up must NOT recompute"

    release.set()
    t_lead.join(2)
    assert res["lead"] == "R"


# --------------------------------------------------------------------------- #
#  Error propagation — the leader's failure reaches the follower, not a wrong value
# --------------------------------------------------------------------------- #


def test_leader_error_propagates_and_is_shared_not_swallowed():
    leader_in = threading.Event()
    release = threading.Event()

    def leader_compute():
        leader_in.set()
        release.wait(2)
        raise ValueError("boom")

    res = {}
    t_lead = threading.Thread(
        target=lambda: res.__setitem__("lead", _capture(lambda: run_heavy("K", leader_compute)))
    )
    t_lead.start()
    assert leader_in.wait(2)

    res_follow = {}

    def _follow():
        res_follow["v"] = _capture(lambda: run_heavy("K", lambda: "SHOULD_NOT"))

    t_follow = threading.Thread(target=_follow)
    t_follow.start()
    release.set()
    t_lead.join(2)
    t_follow.join(2)

    assert isinstance(res["lead"], ValueError)
    assert isinstance(res_follow["v"], ValueError), "the follower must see the leader's failure"


def _capture(fn):
    try:
        return fn()
    except BaseException as exc:  # noqa: BLE001 - test helper: return the exception to assert on
        return exc


# --------------------------------------------------------------------------- #
#  Bind safety — a flight over one DB is never shared with a request on another
# --------------------------------------------------------------------------- #


def test_flight_key_is_bind_qualified():
    s1 = _sqlite_session()
    s2 = _sqlite_session()
    assert flight_key(s1, "k") != flight_key(s2, "k"), "different DBs must not share a flight key"
    assert flight_key(s1, "k") == flight_key(s1, "k"), "same DB → stable key"
    assert flight_key(None, "k").endswith("bind=nobind")


# --------------------------------------------------------------------------- #
#  guarded_read — busy → 429, timeout → 503, and the honest degrade hooks
# --------------------------------------------------------------------------- #


def test_guarded_read_maps_busy_to_429(monkeypatch):
    monkeypatch.setenv("OO_HEAVY_CONCURRENCY", "1")
    heavy._reset_for_tests()
    holding = threading.Event()
    release = threading.Event()

    # Occupy the single slot with a background leader (a plain run_heavy key).
    t = threading.Thread(target=lambda: run_heavy("held", lambda: (holding.set(), release.wait(2))))
    t.start()
    assert holding.wait(2)

    session = _sqlite_session()
    called = [0]
    with pytest.raises(HTTPException) as ei:
        guarded_read(session, "k", lambda: called.__setitem__(0, 1))
    assert ei.value.status_code == 429
    assert called[0] == 0, "a busy request must not run the compute"

    # on_busy hook → an honest degraded payload (200), never cached.
    out = guarded_read(session, "k", lambda: 1, on_busy=lambda exc: {"busy": True})
    assert out == {"busy": True}

    release.set()
    t.join(2)


def test_guarded_read_maps_deadline_to_503_and_honors_on_timeout():
    session = _sqlite_session()

    def _boom():
        raise StatementTimeout("exceeded the 60s deadline")

    with pytest.raises(HTTPException) as ei:
        guarded_read(session, "k", _boom)
    assert ei.value.status_code == 503

    out = guarded_read(session, "k2", _boom, on_timeout=lambda exc: {"degraded": True})
    assert out == {"degraded": True}


def test_guarded_read_returns_the_real_value_when_healthy():
    session = _sqlite_session()
    assert guarded_read(session, "k", lambda: {"ok": 1}) == {"ok": 1}
