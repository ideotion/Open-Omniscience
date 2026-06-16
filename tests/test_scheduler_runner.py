"""
BackgroundScheduler state-machine + round-robin tests (audit PR F).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The scheduler is built to be testable without real waiting: ``run_once_fn`` and
``settings_provider`` are injectable and the inter-pass gap is an instance attr.
These tests drive the loop deterministically via threading.Events (NEVER wall-clock
``sleep`` assertions), covering:

  * continuous mode runs passes back-to-back;
  * legacy/interval mode runs once then IDLES (and stop() still returns promptly);
  * a failing pass is recorded, never crashes the daemon thread;
  * run_now() never overlaps an in-flight run;
  * round_robin_interleave gives every source one turn, within-country order kept.
"""

from __future__ import annotations

import random
import threading
from types import SimpleNamespace

import pytest

from src.scheduler.runner import BackgroundScheduler, round_robin_interleave

# Generous join/wait ceiling — we wait on Events that fire in milliseconds, so a
# real box clears these instantly; the ceiling only bounds a hung thread.
_WAIT = 5.0


@pytest.fixture(autouse=True)
def _isolate_data_dir(monkeypatch, tmp_path):
    # _do_run writes one run-log line via record_run(); keep it in a temp dir.
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


class _FakeSettings:
    """Minimal stand-in for SchedulerSettings (the scheduler reads continuous /
    interval_minutes / mode, and status() calls to_dict())."""

    def __init__(self, continuous: bool, interval_minutes: int = 1, mode: str = "rss"):
        self.continuous = continuous
        self.interval_minutes = interval_minutes
        self.mode = mode

    def to_dict(self) -> dict:
        return {
            "continuous": self.continuous,
            "interval_minutes": self.interval_minutes,
            "mode": self.mode,
        }


def _settings(continuous: bool, interval_minutes: int = 1):
    return lambda: _FakeSettings(continuous, interval_minutes)


def test_continuous_loop_runs_passes_back_to_back():
    calls = []
    two = threading.Event()

    def run_once():
        calls.append(1)
        if len(calls) >= 2:
            two.set()
        return {"stored": 0}

    sch = BackgroundScheduler(run_once_fn=run_once, settings_provider=_settings(True))
    sch._continuous_gap_s = 0.0  # back-to-back, no real waiting
    assert sch.start() is True
    try:
        assert two.wait(_WAIT), "continuous mode should run repeated passes"
        assert sch.is_running() is True
    finally:
        assert sch.stop() is True
    assert sch.is_running() is False
    assert len(calls) >= 2


def test_interval_mode_runs_once_then_idles_and_stops_promptly():
    ran = threading.Event()
    calls = []

    def run_once():
        calls.append(1)
        ran.set()
        return {"stored": 0}

    # interval_minutes=1 -> after the first immediate pass the loop idles 60s.
    sch = BackgroundScheduler(run_once_fn=run_once, settings_provider=_settings(False, 1))
    assert sch.start() is True
    try:
        assert ran.wait(_WAIT), "the first pass runs immediately on start"
        # next_run is set by the loop JUST AFTER the pass returns — poll for it
        # (avoids racing the loop; never a wall-clock sleep assertion).
        next_run = None
        for _ in range(int(_WAIT * 100)):
            next_run = sch.status()["next_run"]
            if next_run:
                break
            threading.Event().wait(0.01)
        assert next_run, "an idling scheduler advertises its next run time"
        assert sch.status()["running"] is True
        assert len(calls) == 1, "interval mode must idle, not loop, after the first pass"
    finally:
        # stop() interrupts the 60s idle wait and returns well under the ceiling.
        assert sch.stop() is True
    assert sch.is_running() is False


def test_failing_pass_is_recorded_not_fatal():
    attempted = threading.Event()

    def run_once():
        attempted.set()
        raise RuntimeError("pass blew up")

    sch = BackgroundScheduler(run_once_fn=run_once, settings_provider=_settings(False, 1))
    assert sch.start() is True
    try:
        assert attempted.wait(_WAIT)
        # The error is captured; the daemon thread survives (still running/idling).
        # Poll status briefly for the recorded error (set just after run_once raises).
        last_error = None
        for _ in range(int(_WAIT * 100)):
            last_error = sch.status().get("last_error")
            if last_error:
                break
            threading.Event().wait(0.01)
        assert last_error and "blew up" in last_error
        assert sch.is_running() is True
    finally:
        assert sch.stop() is True


def test_run_now_never_overlaps_an_in_flight_run():
    gate = threading.Event()
    entered = threading.Event()
    calls = []

    def run_once():
        calls.append(1)
        entered.set()
        gate.wait(_WAIT)  # hold the run open until the test releases it
        return {"stored": 0}

    # Not started — drive run_now() directly so there is no scheduling loop.
    sch = BackgroundScheduler(run_once_fn=run_once, settings_provider=_settings(False, 1))
    assert sch.run_now() is True
    try:
        assert entered.wait(_WAIT), "the first run_now should start a run"
        # A second run_now while the first is still active is refused (no stampede).
        assert sch.run_now() is False
    finally:
        gate.set()
    # Give the worker thread a moment to release _active, then a fresh run is allowed.
    for _ in range(int(_WAIT * 100)):
        if not sch._active:
            break
        threading.Event().wait(0.01)
    assert calls  # at least the first run executed


def test_round_robin_interleave_is_per_country_and_order_preserving():
    src = [
        SimpleNamespace(id=1, country="fr"),
        SimpleNamespace(id=2, country="fr"),
        SimpleNamespace(id=3, country="us"),
        SimpleNamespace(id=4, country=None),  # -> the "unknown" bucket
    ]
    out = round_robin_interleave(src, rng=random.Random(1234))
    assert {s.id for s in out} == {1, 2, 3, 4}, "every source appears exactly once"
    assert len(out) == 4
    # Within a country, the incoming order is preserved (source 1 before source 2).
    ids = [s.id for s in out]
    assert ids.index(1) < ids.index(2)
    assert round_robin_interleave([]) == []
