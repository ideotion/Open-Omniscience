"""The Wikipedia run does not stay dead: the stream is restarted, the drain loop does not end for good.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read from 15 operator bundles (2026-10-06): an instance showed no lane row for 40 hours while
its process was up and online, and its chronology showed the collection Start button pressed
in that time. Three separate holes made a quiet lane stay quiet, and each is pinned here:

* the stream thread ends for good on any refusal by the kill switch and on any unforeseen
  death, and nothing started it again (``revive_stream``);
* the collection Start and Run-now buttons clear the kill switch like the airplane button and
  never gave the lane its go (``_resume_wiki_lane``);
* the drain loop ended for good after three failed drains, with the setting still ``running``
  (it now waits longer, up to a ceiling that says what it protects, and keeps trying).
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ingest import activate_kill_switch, clear_kill_switch
from src.wiki import runner as runner_mod
from src.wiki.runner import FAILING_RETRY_CEILING_S, MAX_CONSECUTIVE_FAILURES, WikiLaneRunner


class _Stream:
    """A stream whose thread lives until released, or ends at once when ``die`` is set."""

    counters = None

    def __init__(self, *, die: bool = False):
        self.die = die
        self.runs = 0
        self.release = threading.Event()

    def run(self, on_change, *, should_stop, max_connections, resume_from, on_position):
        self.runs += 1
        if not self.die:
            self.release.wait(timeout=10)


def _runner(state, stream=None, **kw):
    stream = stream or _Stream()
    runner = WikiLaneRunner(
        adapter=SimpleNamespace(offer=lambda _c: None, note_position=lambda *_a: None),
        stream=stream,
        lane_session=lambda: None,
        state_of=lambda: state["value"],
        hot_sets=dict,
        budget=lambda: None,
        sleep=lambda _s: None,
        **kw,
    )
    return runner, stream


def _join(runner):
    thread = runner._thread
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.fixture(autouse=True)
def _online():
    clear_kill_switch()
    try:
        yield
    finally:
        activate_kill_switch()  # leave the process as every other test expects it


# --------------------------------------------------------------------------- #
# revive_stream: ONE rule for "a thread that was started and is dead".
# --------------------------------------------------------------------------- #
def test_a_stream_that_ended_without_being_stopped_is_started_again():
    state = {"value": "running"}
    runner, stream = _runner(state, _Stream(die=True))
    assert runner.start() is True
    _join(runner)
    assert runner.streaming is False
    stream.die = False
    assert runner.revive_stream() is True
    assert stream.runs == 2 and runner.stream_restarts == 1
    assert runner.last_stream_restart_at is not None
    stream.release.set()
    runner.stop()


def test_a_live_stream_is_left_alone():
    runner, stream = _runner({"value": "running"})
    runner.start()
    assert runner.revive_stream() is False and stream.runs == 1
    stream.release.set()
    runner.stop()


@pytest.mark.parametrize(
    "why",
    ["kill-switch", "halted", "stopped-by-the-operator", "never-started"],
)
def test_it_never_restarts_what_the_operator_or_the_kill_switch_ended(why):
    """The mechanism that made it dead may be the operator's. Only the cause that is gone counts."""
    state = {"value": "running"}
    runner, stream = _runner(state, _Stream(die=True))
    if why != "never-started":
        runner.start()
        _join(runner)
    if why == "kill-switch":
        activate_kill_switch()
    elif why == "halted":
        state["value"] = "halted"
    elif why == "stopped-by-the-operator":
        runner.stop()
    assert runner.revive_stream() is False
    assert stream.runs == (0 if why == "never-started" else 1)
    assert runner.stream_restarts == 0


def test_a_bounded_run_is_not_restarted():
    """``max_connections`` ends the stream on purpose; tests that bound a run rely on it."""
    runner, stream = _runner({"value": "running"}, _Stream(die=True), max_connections=1)
    runner.start()
    _join(runner)
    assert runner.revive_stream() is False and stream.runs == 1


def test_the_drain_loop_starts_a_dead_stream_by_itself_once_the_kill_switch_is_clear():
    state = {"value": "running"}
    runner, stream = _runner(state, _Stream(die=True))
    runner.start()
    _join(runner)
    stream.die = False
    runner.drain = lambda: None  # type: ignore[method-assign]
    runner.refresh_one_pageview_top = lambda: None  # type: ignore[method-assign]
    runner.idle = lambda _s: None  # type: ignore[method-assign]
    runner.run_until_stopped(max_drains=1)
    assert stream.runs == 2 and runner.stream_restarts == 1
    stream.release.set()
    runner.stop()


def test_a_revive_and_a_start_landing_together_make_ONE_stream_thread():
    """The drain thread's revive and the service's start are not serialised by the service lock."""
    import time

    state = {"value": "running"}
    runner, stream = _runner(state, _Stream(die=True))
    runner.start()
    _join(runner)
    stream.die = False
    real = runner._state_of

    def slow_state():
        time.sleep(0.05)  # widen the window between the alive check and the assignment
        return real()

    runner._state_of = slow_state  # type: ignore[assignment]
    gate = threading.Barrier(3)

    def go(fn):
        gate.wait(timeout=5)
        fn()

    workers = [threading.Thread(target=go, args=(f,)) for f in (runner.revive_stream, runner.start)]
    for w in workers:
        w.start()
    gate.wait(timeout=5)
    for w in workers:
        w.join(timeout=5)
    assert stream.runs == 2, "the original stream plus exactly one restart, never two"
    stream.release.set()
    runner.stop()


def test_a_failed_restart_leaves_the_next_tick_able_to_try_again():
    state = {"value": "running"}
    runner, stream = _runner(state, _Stream(die=True))
    runner.start()
    _join(runner)
    stream.die = False
    real = runner._state_of
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 2:  # revive's own read passes; start's read fails once
            raise OSError("database is locked")
        return real()

    runner._state_of = flaky  # type: ignore[assignment]
    with pytest.raises(OSError):
        runner.revive_stream()
    assert runner._thread is not None, "the dead thread stays, so the lane still counts as started"
    assert runner.revive_stream() is True
    stream.release.set()
    runner.stop()


def test_a_restart_that_raises_does_not_end_the_drain_loop():
    state = {"value": "running"}
    runner, _stream = _runner(state)
    runner.revive_stream = lambda: (_ for _ in ()).throw(OSError("busy"))  # type: ignore[method-assign]
    drained = []
    runner.drain = lambda: drained.append(1)  # type: ignore[method-assign]
    runner.refresh_one_pageview_top = lambda: None  # type: ignore[method-assign]
    runner.idle = lambda _s: None  # type: ignore[method-assign]
    runner.run_until_stopped(max_drains=2)
    assert len(drained) == 2


# --------------------------------------------------------------------------- #
# The drain loop: past three failures it keeps going, longer between tries, up to a ceiling.
# --------------------------------------------------------------------------- #
def _failing(state, n):
    runner, _stream = _runner(state)
    waits: list[float] = []
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        if calls["n"] >= n:
            state["value"] = "halted"
        raise RuntimeError("the corpus writer is busy")

    runner.drain = always_fail  # type: ignore[method-assign]
    runner._wait = waits.append  # type: ignore[method-assign]
    return runner, waits, calls


def test_a_lane_that_keeps_failing_is_not_ended_and_its_waits_double_to_the_ceiling():
    state = {"value": "running"}
    runner, waits, calls = _failing(state, MAX_CONSECUTIVE_FAILURES + 5)
    runner.run_until_stopped()
    assert calls["n"] == MAX_CONSECUTIVE_FAILURES + 5, "it kept trying past the third failure"
    interval = runner_mod.DRAIN_INTERVAL_S
    assert waits[:2] == [interval, interval], "the first two failures wait one interval, as before"
    assert waits[2] == 2 * interval and waits[3] == 4 * interval, "then the wait doubles"
    assert max(waits) == FAILING_RETRY_CEILING_S, "and stops at the ceiling"
    assert waits == sorted(waits)


def test_the_status_says_the_lane_is_degraded_and_what_the_ceiling_protects():
    state = {"value": "running"}
    runner, waits, _calls = _failing(state, MAX_CONSECUTIVE_FAILURES + 1)
    runner.run_until_stopped()
    status = runner.drain_status()
    assert status["degraded"] is True
    assert status["retry_in_s"] == waits[-1] <= FAILING_RETRY_CEILING_S
    assert status["retry_ceiling_s"] == FAILING_RETRY_CEILING_S
    assert "sit idle" in status["retry_ceiling_protects"]
    assert "writer" in status["retry_ceiling_protects"]
    assert "busy" in (status["last_error"] or "")


def test_a_success_clears_the_degraded_state():
    state = {"value": "running"}
    runner, _stream = _runner(state)
    runner.consecutive_failures = MAX_CONSECUTIVE_FAILURES + 2
    runner._retry_wait_s = 120.0
    runner.drain = lambda: None  # type: ignore[method-assign]
    runner.refresh_one_pageview_top = lambda: None  # type: ignore[method-assign]
    runner.run_until_stopped(max_drains=1)
    status = runner.drain_status()
    assert status["degraded"] is False and status["retry_in_s"] is None


def test_a_long_wait_ends_early_when_the_runner_is_stopped():
    runner, _stream = _runner({"value": "running"})
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 2:
            runner._stop.set()

    runner._sleep = sleep
    runner._wait(300.0)
    assert len(slept) == 2, "a stop is noticed within a slice, not after the whole wait"


def test_the_retry_wait_never_overflows_however_long_a_lane_keeps_failing():
    """A float interval times ``2 ** 1024`` raises OverflowError (about 85 h of failing drains at
    the ceiling), inside the except handler, which would end the drain thread silently."""
    runner, _stream = _runner({"value": "running"})
    runner._interval = 30.0
    for failures in (MAX_CONSECUTIVE_FAILURES + 1025, 1026, 5000, 10**6):
        runner.consecutive_failures = failures
        assert runner._failure_wait() == FAILING_RETRY_CEILING_S


def test_a_stop_that_lands_inside_a_revive_is_not_erased():
    """``start`` clears the stop flag; a stop ordered before it used to be lost, leaving a stream
    nobody held. ``stop`` now waits for the revive and then ends what it started."""
    import time

    state = {"value": "running"}
    runner, stream = _runner(state, _Stream(die=True))
    runner.start()
    _join(runner)
    stream.die = False
    real = runner._state_of

    def slow_state():
        time.sleep(0.1)  # widen the window inside revive_stream
        return real()

    runner._state_of = slow_state  # type: ignore[assignment]
    reviver = threading.Thread(target=runner.revive_stream)
    reviver.start()
    time.sleep(0.03)  # the revive is inside its first state read
    stream.release.set()
    runner.stop(timeout=5.0)
    reviver.join(timeout=5)
    assert runner.stopped is True, "the stop survived the revive"
    assert not runner.streaming, "no stream thread was left running after the stop"


def test_the_reason_a_stream_ended_and_a_failed_restart_are_on_the_status():
    class Dying:
        counters = None

        def run(self, *a, **k):
            raise ConnectionResetError("peer reset")

    runner, _ = _runner({"value": "running"}, Dying())
    runner.start()
    _join(runner)
    status = runner.drain_status()
    assert "ConnectionResetError" in status["last_stream_end"] and status["last_stream_end_at"]
    runner.revive_stream = lambda: (_ for _ in ()).throw(OSError("busy"))  # type: ignore[method-assign]
    runner.drain = lambda: None  # type: ignore[method-assign]
    runner.refresh_one_pageview_top = lambda: None  # type: ignore[method-assign]
    runner.idle = lambda _s: None  # type: ignore[method-assign]
    runner.run_until_stopped(max_drains=1)
    assert "OSError" in runner.drain_status()["last_restart_error"]


def test_an_unreadable_setting_ends_the_loop_but_says_why():
    def unreadable():
        raise OSError("settings unreadable")

    runner, _ = _runner({"value": "running"})
    runner._state_of = unreadable  # type: ignore[assignment]
    assert runner._should_stop() is True
    assert "could not be read" in runner.drain_status()["last_error"]


def test_a_failed_drain_says_when_and_when_the_next_try_is_due():
    state = {"value": "running"}
    runner, waits, _calls = _failing(state, MAX_CONSECUTIVE_FAILURES + 1)
    runner.run_until_stopped()
    status = runner.drain_status()
    assert status["last_error_at"] and status["retry_due_at"] and status["degraded"] is True
    assert "not a countdown" in status["retry_in_s_note"]


# --------------------------------------------------------------------------- #
# The service: every way of going online gives the lane its go, whatever state it is in.
# --------------------------------------------------------------------------- #
class _FakeRunner:
    def __init__(self):
        self.streaming = False
        self.stopped = False
        self.revives = 0
        self.started = 0
        self.block = threading.Event()

    def start(self):
        self.started += 1
        self.streaming = True
        return True

    def revive_stream(self):
        self.revives += 1
        self.streaming = True
        return True

    def run_until_stopped(self, **_k):
        self.block.wait(timeout=10)

    def stop(self, **_k):
        self.stopped = True
        self.streaming = False
        self.block.set()


@pytest.fixture
def service(monkeypatch):
    import src.wiki.service as svc

    built: list[_FakeRunner] = []
    monkeypatch.setattr(svc, "_state_of", lambda: "running")
    monkeypatch.setattr(svc, "_editions", lambda: ("en",))
    monkeypatch.setattr(svc, "_build", lambda: built.append(_FakeRunner()) or built[-1])
    try:
        yield svc, built
    finally:
        svc.stop_wiki_lane(timeout=1.0)


def test_start_restarts_a_dead_stream_beside_its_live_drain_loop_without_a_second_runner(service):
    svc, built = service
    assert svc.start_wiki_lane() is True
    first = built[0]
    first.streaming = False  # the stream thread died; the drain loop is alive
    assert svc.start_wiki_lane() is True
    assert len(built) == 1 and first.revives == 1, "one runner, one drain loop, the stream restarted"


def test_start_tears_down_a_leftover_with_nothing_alive_and_builds_a_new_runner(service):
    svc, built = service
    svc.start_wiki_lane()
    first = built[0]
    first.block.set()  # its drain loop ends
    svc._DRAIN_THREAD.join(timeout=5)
    first.streaming = False
    assert svc.start_wiki_lane() is True
    assert len(built) == 2 and first.stopped is True


def test_start_is_idempotent_for_a_lane_that_is_streaming(service):
    svc, built = service
    svc.start_wiki_lane()
    assert svc.start_wiki_lane() is True and len(built) == 1


def test_start_does_nothing_while_the_kill_switch_holds_a_dead_stream_down(service):
    svc, built = service
    svc.start_wiki_lane()
    built[0].streaming = False
    built[0].revive_stream = lambda: False  # type: ignore[method-assign]
    activate_kill_switch()
    assert svc.start_wiki_lane() is False
    assert len(built) == 1, "a runner whose loop is alive is not rebuilt while it waits"


def test_a_start_waits_for_a_stop_still_joining_the_old_lane(service):
    """No new runner is built beside the tail of the old one."""
    import time

    svc, built = service
    svc.start_wiki_lane()
    first = built[0]
    stopping = threading.Event()
    release = threading.Event()
    real_stop = first.stop

    def slow_stop(**k):
        stopping.set()
        release.wait(timeout=5)
        real_stop(**k)

    first.stop = slow_stop  # type: ignore[method-assign]
    stopper = threading.Thread(target=svc.stop_wiki_lane)
    stopper.start()
    assert stopping.wait(timeout=5)
    starter = threading.Thread(target=svc.start_wiki_lane)
    starter.start()
    time.sleep(0.2)
    assert len(built) == 1, "the start must wait while the old lane is still being joined"
    release.set()
    stopper.join(timeout=5)
    starter.join(timeout=5)
    assert len(built) == 2


def test_the_release_run_pauses_a_lane_whose_drain_loop_is_alive_even_with_the_stream_down(
    monkeypatch,
):
    import src.wiki.service as svc
    from src.monitoring import release_run

    stopped = []
    monkeypatch.setattr(svc, "lane_service_status", lambda: {"streaming": False, "draining": True})
    monkeypatch.setattr(svc, "stop_wiki_lane", lambda **k: stopped.append(k))
    out = release_run._pause_collection()
    assert out["wiki_lane_was_streaming"] is True and stopped


def test_start_rebuilds_a_lane_whose_stream_is_alive_but_whose_drain_loop_died(service):
    """A live stream over a dead drain loop fills a bounded buffer nobody stores."""
    svc, built = service
    svc.start_wiki_lane()
    first = built[0]
    first.block.set()  # the drain loop ends; the stream thread (the fake) still says streaming
    svc._DRAIN_THREAD.join(timeout=5)
    assert first.streaming is True
    assert svc.start_wiki_lane() is True
    assert len(built) == 2 and first.stopped is True, "torn down and rebuilt, not reported healthy"


def test_the_service_state_names_the_setting_and_the_kill_switch_and_never_raises(service, monkeypatch):
    from src.monitoring import soak_window as sw

    svc, _built = service
    out = sw._wiki_service()
    assert out["state"] == "running" and "online" in out
    monkeypatch.setattr(svc, "lane_service_status", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    bad = sw._wiki_service()
    assert bad["measured"] is False and "RuntimeError" in bad["reason"]


def test_a_lane_with_no_file_still_carries_its_service_state(tmp_path, monkeypatch):
    """Drains that fail before they create wiki.db leave their reason ONLY in the service block."""
    from src.monitoring import soak_window as sw
    from src.versioned.store import dispose_all

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    dispose_all()
    try:
        out = sw._wiki_lane(72.0)
    finally:
        dispose_all()
    assert out["measured"] is False and "service" in out and out["service"]["runner"] is False


def test_a_lane_file_with_a_header_but_no_tables_is_unread_with_its_service_state(tmp_path, monkeypatch):
    import sqlite3

    from src.monitoring import soak_window as sw
    from src.versioned.store import dispose_all, lane_path

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    dispose_all()
    try:
        path = lane_path("wiki")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA user_version = 1")
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()
        out = sw._wiki_lane(72.0)
    finally:
        dispose_all()
    assert out["measured"] is False and "service" in out, out


def test_the_soak_window_carries_the_service_state(service):
    from src.monitoring.soak_window import _wiki_service

    svc, _built = service
    assert _wiki_service()["runner"] is False, "no runner since boot is not a dead lane"
    assert _wiki_service()["basis"].startswith("this process")


# --------------------------------------------------------------------------- #
# The collection Start and Run-now buttons.
# --------------------------------------------------------------------------- #
@pytest.fixture
def scheduler_client(monkeypatch):
    import src.api.scheduler as sched
    import src.wiki.service as svc

    calls: list[str] = []

    class _FakeScheduler:
        def start(self):
            calls.append("scheduler.start")
            return True

        def run_now(self):
            calls.append("scheduler.run_now")
            return True

        def stop(self):
            calls.append("scheduler.stop")
            return True

        def status(self):
            return {"running": True, "settings": {}}

    monkeypatch.delenv("OO_NO_SCHEDULER", raising=False)
    monkeypatch.setattr(sched, "get_scheduler", lambda: _FakeScheduler())
    monkeypatch.setattr(svc, "start_wiki_lane", lambda: calls.append("lane.start") or True)
    app = FastAPI()
    app.include_router(sched.router)
    return TestClient(app), calls


@pytest.mark.parametrize("route", ["/api/scheduler/start", "/api/scheduler/run-now"])
def test_the_collection_buttons_give_the_lane_its_go_after_clearing_the_kill_switch(
    scheduler_client, route
):
    from src.ingest import kill_switch_active

    client, calls = scheduler_client
    activate_kill_switch()
    assert client.post(route).status_code == 200
    assert kill_switch_active() is False
    assert calls[-1] == "lane.start" and calls[0].startswith("scheduler."), calls


def test_a_lane_hiccup_never_fails_the_start(scheduler_client, monkeypatch):
    import src.wiki.service as svc

    client, _calls = scheduler_client

    def boom():
        raise RuntimeError("the lane could not be built")

    monkeypatch.setattr(svc, "start_wiki_lane", boom)
    assert client.post("/api/scheduler/start").status_code == 200


def test_the_stop_button_does_not_touch_the_lane_beyond_the_kill_switch(scheduler_client):
    """Stop engages the kill switch; the stream refuses by name at its next event and the next
    Start or the loop's own check brings it back. Stopping the lane here would make a Stop then
    Start read as two lane restarts."""
    client, calls = scheduler_client
    assert client.post("/api/scheduler/stop").status_code == 200
    assert "lane.start" not in calls
