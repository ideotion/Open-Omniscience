"""The polled activity panel is answered from the last good preview, never from the pool.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``GET /api/scheduler/activity`` answered 500 after the pool's 30 s checkout timeout on nine field
instances (2026-09-30 diagnostics, rank 7; 97 of 30,867 polls on one). The preview is a loose
glimpse, so a preview a few seconds old is as true as a fresh one: the poll is now served from
memory, labelled with its age, with at most one background refresh at a time. Not the ruling-gated
429 cap: nothing is rejected.
"""

from __future__ import annotations

import inspect
import threading
import time

from src.scheduler import plan_cache as pc
from src.scheduler.plan_cache import FRESH_S, STALE_S, PlanPreviewCache
from src.scheduler.settings import SchedulerSettings


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _settled(cache: PlanPreviewCache, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while cache.stats()["refreshing"] and time.monotonic() < end:
        time.sleep(0.01)
    assert not cache.stats()["refreshing"]


S = SchedulerSettings()


def test_a_fresh_preview_is_served_without_another_computation():
    clock, calls = Clock(), []
    cache = PlanPreviewCache(clock=clock)

    def compute():
        calls.append(1)
        return {"planned_total": 7, "next_targets": ["a.example"]}

    first = cache.get(S, compute)
    assert first["planned_total"] == 7 and first["state"] == "fresh" and first["age_s"] == 0.0
    clock.t += FRESH_S - 1
    again = cache.get(S, compute)
    assert again["planned_total"] == 7 and again["age_s"] == FRESH_S - 1
    _settled(cache)
    assert len(calls) == 1, "a poll inside the fresh window must not touch the database"


def test_a_stale_preview_is_served_at_once_while_one_refresh_runs():
    clock = Clock()
    cache = PlanPreviewCache(clock=clock)
    cache.get(S, lambda: {"planned_total": 1})
    gate = threading.Event()
    started: list[int] = []

    def slow():  # the pool is exhausted: this is the wait a request thread used to sit in
        started.append(1)
        gate.wait(10)
        return {"planned_total": 2}

    clock.t += FRESH_S + 1
    t0 = time.monotonic()
    out = cache.get(S, slow)
    assert time.monotonic() - t0 < 0.5, "the poll waited on the refresh"
    assert out["planned_total"] == 1 and out["state"] == "refreshing" and out["age_s"] > FRESH_S
    assert out["stale"] is False
    # many more polls while the refresh is stuck: still instant, still ONE refresh
    for _ in range(20):
        assert cache.get(S, slow)["planned_total"] == 1
    assert len(started) == 1
    gate.set()
    _settled(cache)
    assert cache.get(S, slow)["planned_total"] == 2


def test_concurrent_polls_start_a_single_refresh():
    clock = Clock()
    cache = PlanPreviewCache(clock=clock)
    cache.get(S, lambda: {"planned_total": 1})
    clock.t += FRESH_S + 1
    gate, started = threading.Event(), []

    def slow():
        started.append(1)
        gate.wait(10)
        return {"planned_total": 2}

    threads = [threading.Thread(target=cache.get, args=(S, slow)) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(3)
    assert len(started) == 1
    gate.set()
    _settled(cache)


def test_with_nothing_cached_the_poll_waits_a_short_bounded_time_then_says_computing(monkeypatch):
    monkeypatch.setattr(pc, "FIRST_WAIT_S", 0.05)
    cache = PlanPreviewCache(clock=Clock())
    gate = threading.Event()
    t0 = time.monotonic()
    out = cache.get(S, lambda: (gate.wait(10), {"planned_total": 3})[1])
    assert time.monotonic() - t0 < 1.0
    assert out["state"] == "computing" and out["as_of"] is None and "planned_total" not in out
    gate.set()
    _settled(cache)
    assert cache.get(S, lambda: {"planned_total": 99})["planned_total"] == 3


def test_a_preview_for_other_settings_is_never_shown(monkeypatch):
    monkeypatch.setattr(pc, "FIRST_WAIT_S", 0.05)
    cache = PlanPreviewCache(clock=Clock())
    cache.get(SchedulerSettings(max_sources_per_run=5), lambda: {"planned_total": 5})
    gate = threading.Event()
    out = cache.get(
        SchedulerSettings(max_sources_per_run=9), lambda: (gate.wait(10), {"planned_total": 9})[1]
    )
    assert out["state"] == "computing", "the plan the next pass will NOT run must not be shown"
    gate.set()
    _settled(cache)
    assert cache.get(SchedulerSettings(max_sources_per_run=9), lambda: {})["planned_total"] == 9


def test_a_failed_refresh_is_named_and_the_age_keeps_growing():
    clock = Clock()
    cache = PlanPreviewCache(clock=clock)
    cache.get(S, lambda: {"planned_total": 4})

    def broken():
        raise RuntimeError("QueuePool limit of size 12 overflow 0 reached\n[SQL: SELECT secret]")

    clock.t += FRESH_S + 1
    cache.get(S, broken)
    _settled(cache)
    clock.t += STALE_S
    out = cache.get(S, broken)
    _settled(cache)
    assert out["planned_total"] == 4, "the last good preview keeps being served"
    assert out["age_s"] > STALE_S and out["stale"] is True
    err = cache.get(S, broken)["refresh_error"]
    assert err["type"] == "RuntimeError"
    assert "SELECT" not in err["message"], "the SQL belongs nowhere in the payload"
    assert cache.stats()["failures"] >= 1


def test_a_success_clears_the_recorded_error():
    clock = Clock()
    cache = PlanPreviewCache(clock=clock)

    def broken():
        raise RuntimeError("x")

    cache.get(S, broken)
    _settled(cache)
    assert "refresh_error" in cache.get(S, broken)
    _settled(cache)
    clock.t += FRESH_S + 1
    cache.get(S, lambda: {"planned_total": 1})
    _settled(cache)
    assert "refresh_error" not in cache.get(S, lambda: {"planned_total": 1})


# --------------------------------------------------------------------------- #
#  the endpoint and the scheduler: no pool dependency
# --------------------------------------------------------------------------- #
def test_the_endpoint_takes_no_database_dependency():
    from src.api.scheduler import scheduler_activity

    assert list(inspect.signature(scheduler_activity).parameters) == [], (
        "a poll that depends on get_db waits for the pool's 30 s checkout timeout"
    )


def test_a_poll_is_answered_while_the_database_never_answers(monkeypatch):
    """The field failure, reproduced: the refresh (the only thing that touches the database) is
    stuck forever; every poll still answers 200 in well under a second."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.scheduler import runner

    pc.plan_cache._reset_for_tests()
    monkeypatch.setattr(pc, "FIRST_WAIT_S", 0.05)
    gate = threading.Event()
    monkeypatch.setattr(
        runner.BackgroundScheduler, "_compute_plan", lambda self, settings, last: (gate.wait(10), {})[1]
    )
    try:
        with TestClient(app) as client:
            for _ in range(5):
                t0 = time.monotonic()
                r = client.get("/api/scheduler/activity")
                assert r.status_code == 200
                assert time.monotonic() - t0 < 1.5
                assert r.json()["plan"]["state"] == "computing"
    finally:
        gate.set()
        _settled(pc.plan_cache)
        pc.plan_cache._reset_for_tests()


def test_a_caller_with_a_session_still_gets_the_synchronous_uncached_plan(monkeypatch):
    from src.scheduler import runner

    seen = {}
    monkeypatch.setattr(
        runner, "plan_preview", lambda session, settings, *, last_result: seen.setdefault("p", {"planned_total": 11})
    )
    sched = runner.BackgroundScheduler(settings_provider=lambda: SchedulerSettings())
    out = sched.activity(object())
    assert out["plan"] == {"planned_total": 11} and "state" not in out["plan"]


def test_the_preview_label_runs_as_real_code_under_node_in_both_uis():
    """A preview that is not fresh says so, with its age, in the vitals panel, the Queue tab and
    /tasks; nothing is said while it is fresh (tests/plan_preview_node_test.js)."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        ["node", str(root / "tests" / "plan_preview_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks ok" in proc.stdout


def test_nothing_ever_computed_and_a_failing_refresh_is_computing_with_the_error():
    """The coordinator's check of #1289 (S2c): the payload keeps both facts so the page can say the
    attempts are failing (``state == "computing"`` alone reads as "wait a moment" for ever)."""
    cache = PlanPreviewCache(clock=Clock())

    def broken():
        raise RuntimeError("QueuePool limit of size 12 overflow 0 reached")

    cache.get(S, broken)
    _settled(cache)
    out = cache.get(S, broken)
    assert out["state"] == "computing" and out["as_of"] is None and out["age_s"] is None
    assert out["refresh_error"]["type"] == "RuntimeError"
    assert "planned_total" not in out
