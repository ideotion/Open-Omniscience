"""A refused collection start leaves the network exactly as it found it (R756, row 208).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``POST /api/scheduler/start`` and ``/run-now`` used to clear the kill switch FIRST and then try to make the collection thread. When the
thread could not be made ("can't start new thread"), the route answered 409 with the switch left cleared: a start that did nothing had
opened the network (the stated limit C8 of the 0.6 plan). R756: on a refusal the switch is in the state it had immediately before the
request, with no moment in between when anything could fetch, and the refusal says what the network is doing now.

The routes now make the thread first, with the thread waiting on a gate, clear the switch only once the thread exists, and open the gate
last. These tests use the REAL kill switch (``src.ingest``), and restore it after each test.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

import src.ingest as ingest

_CANNOT_START = "can't start new thread"


class _Threading:
    """What ``src.scheduler.runner`` sees as ``threading``: the real one, except that its Threads refuse to start."""

    def __init__(self) -> None:
        class Thread(threading.Thread):
            def start(self) -> None:
                raise RuntimeError(_CANNOT_START)

        self.Thread = Thread

    def __getattr__(self, name: str):
        return getattr(threading, name)


@pytest.fixture(autouse=True)
def _restore_the_switch():
    was = ingest.kill_switch_active()
    yield
    if was:
        ingest.activate_kill_switch()
    else:
        ingest.clear_kill_switch()


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)


@pytest.fixture
def refusing_scheduler(monkeypatch):
    """The REAL scheduler, whose threads cannot start, as the process's one; the lane resume recorded instead of run."""
    from src.scheduler import runner

    scheduler = runner.BackgroundScheduler(run_once_fn=lambda: {})
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)
    monkeypatch.setattr(runner, "threading", _Threading())
    monkeypatch.setattr("src.api.scheduler.get_scheduler", lambda: scheduler)
    after: list[str] = []
    monkeypatch.setattr("src.api.scheduler._resume_wiki_lane", lambda: after.append("wiki lane resumed"))
    return scheduler, after


@pytest.mark.parametrize("route", ["/api/scheduler/start", "/api/scheduler/run-now"])
def test_a_refused_start_from_airplane_mode_leaves_airplane_mode_on(client, refusing_scheduler, route):
    """The branch C8 was about: the switch was engaged, the start would have cleared it, and the start was refused."""
    scheduler, after = refusing_scheduler
    ingest.activate_kill_switch()
    r = client.post(route)
    assert r.status_code == 409
    assert ingest.kill_switch_active() is True, "a refused start opened the network"
    detail = r.json()["detail"]
    assert _CANNOT_START in detail["error"], "the visible reason is the refusal's own words"
    assert detail["kill_switch"] == "engaged"
    assert detail["network"] == "Airplane mode is on, as it was before this start."
    assert scheduler.is_running() is False and after == []


@pytest.mark.parametrize("route", ["/api/scheduler/start", "/api/scheduler/run-now"])
def test_a_refused_start_after_the_operator_went_online_leaves_the_network_on(client, refusing_scheduler, route):
    """The other branch: the operator had cleared the switch before (the UI's consent popup presses the airplane button first). A refusal
    does not engage it -- that would undo an online state the operator chose before the click."""
    ingest.clear_kill_switch()
    r = client.post(route)
    assert r.status_code == 409
    assert ingest.kill_switch_active() is False, "a refused start took the operator offline"
    detail = r.json()["detail"]
    assert detail["kill_switch"] == "off"
    assert detail["network"] == "The network stays on, as you had set it before this start."


class _Recording:
    """A scheduler stand-in that makes a REAL gated thread and records what the switch said at each step."""

    def __init__(self) -> None:
        self.seen: dict[str, bool] = {}
        self.ran = threading.Event()

    def _make(self, gate, label: str) -> bool:
        self.seen[f"{label}: while the thread was being made"] = ingest.kill_switch_active()

        def body() -> None:
            self.seen[f"{label}: when the thread ran"] = ingest.kill_switch_active()
            self.ran.set()

        def gated() -> None:
            if gate is None or gate.wait():
                body()

        threading.Thread(target=gated, daemon=True).start()
        return True

    def start(self, gate=None) -> bool:
        return self._make(gate, "start")

    def run_now(self, gate=None) -> bool:
        return self._make(gate, "run now")

    def status(self) -> dict:
        return {"running": True}


@pytest.mark.parametrize("route, label", [("/api/scheduler/start", "start"), ("/api/scheduler/run-now", "run now")])
def test_the_switch_is_cleared_only_once_the_thread_exists_and_the_thread_runs_after_it(client, monkeypatch, route, label):
    """The atomicity half of R756: while the thread is being made the switch is still as the operator left it (engaged here), and the
    thread's first step runs only after the clear -- so a start that works still runs its first pass online."""
    fake = _Recording()
    monkeypatch.setattr("src.api.scheduler.get_scheduler", lambda: fake)
    monkeypatch.setattr("src.api.scheduler._resume_wiki_lane", lambda: None)
    monkeypatch.setattr("src.api.scheduler._status_payload", lambda: {})
    ingest.activate_kill_switch()
    r = client.post(route)
    assert r.status_code == 200 and r.json()["started"] is True
    assert fake.ran.wait(5), "the gated thread never ran: the route did not open its gate"
    assert fake.seen == {
        f"{label}: while the thread was being made": True,
        f"{label}: when the thread ran": False,
    }
    assert ingest.kill_switch_active() is False


def test_a_start_that_raises_something_else_opens_nothing_either(client, monkeypatch):
    """Not a refusal (the unhandled 500 stays), but the switch is untouched all the same: the clear comes after the start returns."""

    class _Broken:
        def start(self, gate=None) -> bool:
            raise TypeError("not a refusal")

    monkeypatch.setattr("src.api.scheduler.get_scheduler", lambda: _Broken())
    ingest.activate_kill_switch()
    assert client.post("/api/scheduler/start").status_code == 500
    assert ingest.kill_switch_active() is True


def test_the_gate_is_decided_on_every_path_out_of_the_route(monkeypatch):
    """A thread made before a failure further on must never be left waiting: the route decides the gate in a ``finally`` -- and on any
    path but a clean opening it CANCELS it, so the thread returns without running."""
    from src.api import scheduler as scheduler_api

    gates: list = []

    def call(gate) -> bool:
        gates.append(gate)
        return True

    monkeypatch.setattr("src.ingest.note_operator_crossed_online", lambda: (_ for _ in ()).throw(OSError("boom")))
    ingest.activate_kill_switch()
    with pytest.raises(OSError):
        scheduler_api._start_opening_the_network(call, "test")
    assert gates and gates[0]._decided.is_set(), "the gate was left undecided"
    assert gates[0].wait() is False, "a start that did not finish opening the network let its thread run"
    assert ingest.kill_switch_active() is True, "a start that failed after the clear left the network open"


def test_a_crash_between_the_thread_and_the_clear_boots_as_refused():
    """R756's crash clause, by construction: the switch is process memory, never persisted, and the boot engages it unless an operator
    crossed online in THIS process. A process that dies after making the thread and before the clear therefore comes back in airplane
    mode, which is the refused state. Pinned at the source so neither half can drift."""
    import inspect

    from src.api import main

    assert isinstance(ingest._KILL, threading.Event)
    boot = inspect.getsource(main)
    assert "crossed_online_since_boot()" in boot and "activate_kill_switch()" in boot
    from src.api import scheduler as scheduler_api

    src = inspect.getsource(scheduler_api._start_opening_the_network)
    assert src.index("call(gate)") < src.index("clear_kill_switch_unless_engaged_since(epoch)") < src.index("gate.open()")
    for route in (scheduler_api.scheduler_start, scheduler_api.scheduler_run_now):
        assert "clear_kill_switch" not in inspect.getsource(route), "a route clears the switch before its thread exists again"


def test_the_ui_says_what_the_network_is_doing_after_a_refusal_in_every_language():
    """The Start and Run now buttons append the server's sentence, translated; each sentence is a key in all 12 locales."""
    import json
    from pathlib import Path

    from src.api import scheduler as scheduler_api

    root = Path(__file__).resolve().parent.parent
    js = (root / "src" / "static" / "app-sources.js").read_text(encoding="utf-8")
    assert js.count('_startRefusalMsg("Start failed: {error}", e, t9)') == 1
    assert js.count('_startRefusalMsg("Run now failed: {error}", e, t9)') == 1
    for path in sorted((root / "src" / "static" / "locales").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        for sentence in [*scheduler_api._NETWORK_AFTER_REFUSAL.values(), scheduler_api._STOPPED_DURING_START, scheduler_api._STOP_KEPT]:
            assert table.get(sentence), f"{path.name} has no translation of {sentence!r}"


class _StopsDuringStart(_Recording):
    """A stand-in whose thread is made while a Stop engages the switch (the window between the thread and the clear)."""

    def _make(self, gate, label):
        made = super()._make(gate, label)
        ingest.activate_kill_switch()  # the Stop button, the airplane toggle or a panic, landing right here
        return made


@pytest.mark.parametrize("route", ["/api/scheduler/start", "/api/scheduler/run-now"])
@pytest.mark.parametrize("engaged_before", [True, False])
def test_a_stop_during_the_start_wins_and_the_network_stays_closed(client, monkeypatch, route, engaged_before):
    """Both security reads of row 208 found it: with the clear moved after the thread, a Stop landing between them would have been
    undone by the clear. The clear now happens only if the switch was not engaged since the request began."""
    fake = _StopsDuringStart()
    monkeypatch.setattr("src.api.scheduler.get_scheduler", lambda: fake)
    resumed: list[str] = []
    monkeypatch.setattr("src.api.scheduler._resume_wiki_lane", lambda: resumed.append("x"))
    if engaged_before:
        ingest.activate_kill_switch()
    else:
        ingest.clear_kill_switch()
    r = client.post(route)
    assert r.status_code == 409
    assert ingest.kill_switch_active() is True, "a start undid a Stop pressed while it was starting"
    detail = r.json()["detail"]
    assert detail["kill_switch"] == "engaged"
    assert detail["error"] == "Collection was stopped while it was starting, so the network was not opened."
    assert detail["network"] == "Airplane mode is on: the Stop is kept.", "never 'as it was before' when the switch was off before"
    assert resumed == []
    assert not fake.ran.wait(0.5), "the thread ran under a switch the route did not clear (security read 1, second pass)"


class _NoThread:
    def start(self, gate=None) -> bool:
        return False

    run_now = start

    def status(self) -> dict:
        return {"running": False}


@pytest.mark.parametrize("route", ["/api/scheduler/start", "/api/scheduler/run-now"])
def test_a_start_that_makes_no_thread_opens_nothing(client, monkeypatch, route):
    """``False`` (already running, a run in flight, an exclusive hold): no thread was made, so the switch is left as found -- a pass still
    winding down after a Stop is not handed the network back."""
    monkeypatch.setattr("src.api.scheduler.get_scheduler", lambda: _NoThread())
    monkeypatch.setattr("src.api.scheduler._resume_wiki_lane", lambda: None)
    monkeypatch.setattr("src.api.scheduler._status_payload", lambda: {})
    ingest.activate_kill_switch()
    r = client.post(route)
    assert r.status_code == 200 and r.json()["started"] is False
    assert ingest.kill_switch_active() is True


def test_the_conditional_clear_refuses_after_any_engagement_and_clears_otherwise():
    ingest.activate_kill_switch()
    epoch = ingest.kill_switch_epoch()
    assert ingest.clear_kill_switch_unless_engaged_since(epoch) is True and not ingest.kill_switch_active()
    epoch = ingest.kill_switch_epoch()
    ingest.activate_kill_switch()
    assert ingest.clear_kill_switch_unless_engaged_since(epoch) is False and ingest.kill_switch_active()


def test_a_cancelled_loop_thread_exits_without_running_and_the_scheduler_is_not_left_running(monkeypatch):
    """The real scheduler: a cancelled gate ends the loop thread before its first step, so status does not say running after a 409."""
    from src.scheduler import runner

    ran: list[str] = []
    scheduler = runner.BackgroundScheduler(run_once_fn=lambda: ran.append("pass") or {})
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)
    monkeypatch.setattr(scheduler, "_loop", lambda: ran.append("loop"))
    monkeypatch.setattr(runner, "_ledger_collection", lambda *a, **k: ran.append("ledger"))
    gate = runner.StartGate()
    assert scheduler.start(gate=gate) is True
    gate.cancel()
    scheduler._thread.join(5)
    assert scheduler.is_running() is False and ran == []


def test_the_same_patched_loop_does_run_when_the_gate_opens(monkeypatch):
    """The control for the test above: with the same patches, an OPENED gate runs the loop and writes the ledger pair, so the empty
    record there is the cancel's doing and not a patch that never ran."""
    from src.scheduler import runner

    ran: list[str] = []
    scheduler = runner.BackgroundScheduler(run_once_fn=lambda: {})
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)
    monkeypatch.setattr(scheduler, "_loop", lambda: ran.append("loop"))
    monkeypatch.setattr(runner, "_ledger_collection", lambda *a, **k: ran.append("ledger"))
    gate = runner.StartGate()
    assert scheduler.start(gate=gate) is True
    gate.open()
    scheduler._thread.join(5)
    assert ran == ["ledger", "loop", "ledger"]
