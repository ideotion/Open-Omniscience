"""Three promises the start-up sequence made and the first version did not keep.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Found by the coordinator's check of PR #1305:
  * the five-minute warning was logged only AFTER a step returned, so a step that never ends (the
    one the warning exists for) logged nothing;
  * a ``Thread.start()`` that fails ("can't start new thread", what a memory-starved machine raises)
    leaked the build lock, and the boot sequence's wait for the build then never ended;
  * a ``BaseException`` that ended a step was recorded as ``done``.
"""

from __future__ import annotations

import logging
import threading

import pytest

from src.api import boot_sequence as bs


@pytest.fixture(autouse=True)
def _fresh_boot_state():
    bs._reset()
    yield
    with bs._LOCK:
        bs._STATE.update({"warm": "pending", "reindex_pending": None})
    bs._reset()


def test_a_step_that_never_ends_is_logged_while_it_is_still_running(monkeypatch):
    monkeypatch.setattr(bs, "SLOW_STEP_S", 0.05)
    release = threading.Event()
    seen: list[str] = []
    got = threading.Event()

    class Handler(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING and "still running" in record.getMessage():
                seen.append(record.getMessage())
                got.set()

    handler = Handler()
    bs._LOG.addHandler(handler)
    runner = threading.Thread(target=bs._timed, args=("warm-cache", release.wait), kwargs={"holds": "the rollup"})
    try:
        runner.start()
        assert got.wait(5), "a step still running past the limit logged nothing"
        assert runner.is_alive(), "the step must still be running when the warning appears"
    finally:
        release.set()
        runner.join(5)
        bs._LOG.removeHandler(handler)
    assert "warm-cache" in seen[0] and "the rollup waiting behind it" in seen[0]


def test_a_fast_step_cancels_its_warning(monkeypatch, caplog):
    monkeypatch.setattr(bs, "SLOW_STEP_S", 0.2)
    with caplog.at_level(logging.WARNING, logger=bs._LOG.name):
        bs._timed("rollup", lambda: None, holds="the re-index")
        threading.Event().wait(0.5)  # longer than the limit: a timer that was not cancelled fires now
    assert not [r for r in caplog.records if "still running" in r.getMessage()]


def test_a_baseexception_that_ends_a_step_is_not_recorded_as_done():
    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        bs._timed("rollup", interrupted, holds="the re-index")
    rows = {r["step"]: r for r in bs.snapshot()["steps"]}
    assert rows["rollup"]["state"] == "failed"


def _refuse_to_start(self):
    raise RuntimeError("can't start new thread")


def test_a_build_thread_that_cannot_start_does_not_leak_the_rollup_lock(monkeypatch):
    from src.analytics import rollup_serve

    monkeypatch.setattr(threading.Thread, "start", _refuse_to_start)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")
    rollup_serve._trigger_build_async()  # a serve path: it must not raise
    assert not rollup_serve._BUILD_LOCK.locked(), "the lock leaked, so every later build waits forever"
    assert rollup_serve._LAST_OUTCOME["value"] == "failed"


def test_a_build_thread_that_cannot_start_does_not_leak_the_map_lock(monkeypatch):
    from src.analytics import map_serve

    monkeypatch.setattr(threading.Thread, "start", _refuse_to_start)
    map_serve._trigger_build_async()
    assert not map_serve._BUILD_LOCK.locked()


def test_a_machine_that_cannot_start_the_slow_step_timer_does_not_leave_the_step_running(monkeypatch):
    """A starved machine raises RuntimeError("can't start new thread"): the step must still run and end."""
    from src.api import boot_sequence as bs

    class Starved:
        def __init__(self, *a, **kw):
            self.daemon = False

        def start(self):
            raise RuntimeError("can't start new thread")

        def cancel(self):
            pass

    monkeypatch.setattr(bs.threading, "Timer", Starved)
    bs._reset()
    ran = []
    bs._timed("rollup", lambda: ran.append(1), holds="nothing")
    assert ran == [1]
    assert bs._STEPS["rollup"]["state"] == "done", "not stuck in 'running'"
    bs._reset()
