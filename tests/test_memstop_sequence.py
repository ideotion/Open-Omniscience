"""The clean stop's sequence (B2): ``scheduler.memstop.execute``.

Every external step is replaced by a spy, so the tests read the ORDER of the steps, that the evidence is on disk before the ladder
runs again, that a step that fails leaves the rest running (and is recorded as its class only), that one process stops once, and
that the record read back is bounded, allow-listed and its own session's."""
from __future__ import annotations

import json
import os

import pytest

from src.scheduler import memstop

PASS = "Zq7!stop-key'Nm4"
DECISION = {"due": True, "window_s": 300.0, "floor_mb": 64.0, "samples": 200, "span_s": 299.0, "low_share": 1.0,
            "max_avail_mb": 60.0, "held_share": 0.5, "longest_gap_s": 1.5}


class _Guard:
    def state(self):
        return {"since": "2026-10-15T01:00:00+00:00", "reason": "only 48 MB of system memory available", "engagements": 1,
                "thresholds": {"avail_floor_mb": 256.0},
                "last_reading": {"rss_mb": 1500.0, "mem_avail_mb": 48.0, "mem_total_mb": 3900.0, "proc_swap_mb": 12.0}}

    def last_release(self):
        return {"ok": True, "rss_before_mb": 1900.0, "rss_after_mb": 1500.0, "steps": [{"name": "caches", "ok": True, "freed_mb": 400.0}]}


@pytest.fixture
def stop(monkeypatch, tmp_path):
    from src.monitoring import forensics, session_history, session_hwm
    from src.safety import shutdown
    from src.scheduler import release, runner

    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    memstop.reset_for_tests()
    calls: list[str] = []
    on_disk_at: dict[str, bool] = {}

    def spy(name, result=None):
        def fn(*a, **k):
            calls.append(name)
            on_disk_at[name] = (data / "memory_stop.json").exists()
            return result
        return fn

    monkeypatch.setattr(session_hwm, "observe", spy("snapshot"))
    monkeypatch.setattr(session_hwm, "flush", spy("flush"))
    monkeypatch.setattr(session_history, "record_event", spy("ledger_event"))
    monkeypatch.setattr(session_history, "current_session", lambda: {"session_id": "sess-1", "uptime_s": 3600.0})
    monkeypatch.setattr(release, "release_residents", spy("release_again", {"ok": True, "rss_after_mb": 1400.0}))
    monkeypatch.setattr(runner, "_phase_set", spy("phase"))
    monkeypatch.setattr(runner, "pause_for_exclusive_operation", spy("pause", True))
    monkeypatch.setattr(runner, "exclusive_window_open", lambda: False)
    monkeypatch.setattr(forensics, "record_shutdown_phase", spy("sentinel"))
    monkeypatch.setattr(shutdown, "request_shutdown", spy("shutdown", {"ok": True}))
    yield calls, on_disk_at, data
    memstop.reset_for_tests()


def test_the_steps_run_in_the_order_the_plan_gives(stop):
    calls, _disk, _data = stop
    memstop.execute(DECISION, _Guard())
    assert calls == ["snapshot", "flush", "ledger_event", "release_again", "phase", "pause", "sentinel", "shutdown"]


def test_the_evidence_is_on_disk_before_the_ladder_runs_again(stop):
    calls, disk, data = stop
    memstop.execute(DECISION, _Guard())
    assert disk["release_again"] is True and disk["snapshot"] is False, "the snapshot is the very first act; the record follows it"
    rec = json.loads((data / "memory_stop.json").read_text())
    assert rec["decision"]["low_share"] == 1.0 and rec["guard"]["mem_avail_mb"] == 48.0
    assert rec["release_again"]["rss_after_mb"] == 1400.0 and rec["session_id"] == "sess-1"


def test_the_sentinel_and_the_shutdown_carry_the_reason(stop, monkeypatch):
    from src.monitoring import forensics
    from src.safety import shutdown

    seen = {}
    monkeypatch.setattr(forensics, "record_shutdown_phase", lambda phase, reason=None: seen.update(phase=phase, reason=reason))
    monkeypatch.setattr(shutdown, "request_shutdown", lambda confirm, **k: seen.update(confirm=confirm) or {"ok": True})
    memstop.execute(DECISION, _Guard())
    assert seen == {"phase": "shutting-down", "reason": "memory exhausted", "confirm": True}
    assert memstop.SHUTDOWN_REASON == "memory exhausted"


def test_one_shot_per_process(stop):
    calls, _d, _data = stop
    assert memstop.execute(DECISION, _Guard()) is not None
    n = len(calls)
    assert memstop.execute(DECISION, _Guard()) is None
    assert len(calls) == n


@pytest.mark.parametrize("failing", ["snapshot", "ledger_event", "release_again", "phase", "pause", "sentinel"])
def test_a_failing_step_leaves_the_rest_running_and_is_recorded_as_its_class(stop, monkeypatch, failing):
    from src.monitoring import forensics, session_history, session_hwm
    from src.scheduler import release, runner

    calls, _d, data = stop
    targets = {"snapshot": (session_hwm, "observe"), "ledger_event": (session_history, "record_event"),
               "release_again": (release, "release_residents"), "phase": (runner, "_phase_set"),
               "pause": (runner, "pause_for_exclusive_operation"), "sentinel": (forensics, "record_shutdown_phase")}
    mod, attr = targets[failing]

    def boom(*a, **k):
        raise RuntimeError(f"engine said {PASS}")

    monkeypatch.setattr(mod, attr, boom)
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)
    rec = memstop.execute(DECISION, _Guard())
    assert "shutdown" in calls, "the shutdown still runs"
    assert rec["steps"][failing] == {"ok": False, "error": "RuntimeError"}
    assert PASS not in (data / "memory_stop.json").read_text(), "the engine's words never reach the record"


def test_the_shutdown_failing_is_recorded_not_raised(stop, monkeypatch):
    from src.safety import shutdown

    monkeypatch.setattr(shutdown, "request_shutdown", lambda **k: (_ for _ in ()).throw(OSError("no")))
    rec = memstop.execute(DECISION, _Guard())
    assert rec["steps"]["shutdown"] == {"ok": False, "error": "OSError"}


def test_the_record_read_back_is_this_sessions_only(stop):
    _c, _d, data = stop
    memstop.execute(DECISION, _Guard())
    got = memstop.read_record("sess-1")
    assert got and got["decision"]["samples"] == 200 and got["bytes_read"] == (data / "memory_stop.json").stat().st_size
    assert memstop.read_record("sess-2") is None and memstop.read_record(None) is None


def test_the_reader_keeps_only_the_allow_list(stop):
    _c, _d, data = stop
    (data / "memory_stop.json").write_text(json.dumps({"session_id": "sess-1", "kind": "memory-stop", "secret": PASS, "steps": {}}))
    got = memstop.read_record("sess-1")
    assert got and "secret" not in got and PASS not in json.dumps(got)


def test_the_record_stays_within_its_stated_size_at_its_largest(stop):
    """What the bundle carries is measured: the largest record this code writes (every step recorded, every field filled) is
    read back at its real size, and that size is under the bound the bundle's member budgets for it."""
    _c, _d, data = stop
    big_guard = _Guard()
    big_guard.state = lambda: {"since": "x" * 40, "reason": "y" * 300, "engagements": 10**6,
                               "thresholds": dict.fromkeys(("rss_pct_of_total", "avail_floor_mb", "trip_after_samples", "resume_after_samples", "resume_rss_pct"), 10 ** 9),
                               "last_reading": dict.fromkeys(("rss_mb", "mem_avail_mb", "mem_total_mb", "proc_swap_mb"), 123456.789)}
    memstop.execute({**DECISION, "extra": "z" * 100}, big_guard)
    got = memstop.read_record("sess-1")
    assert got["bytes_read"] == (data / "memory_stop.json").stat().st_size
    assert got["bytes_read"] <= memstop.RECORD_MAX_BYTES


def test_a_record_over_the_bound_is_not_parsed_and_only_its_size_is_said(stop, monkeypatch):
    _c, _d, data = stop
    (data / "memory_stop.json").write_text(json.dumps({"session_id": "sess-1", "decision": {"pad": "p" * (memstop.RECORD_MAX_BYTES + 10)}}))
    monkeypatch.setattr(memstop.json, "loads", lambda *a, **k: (_ for _ in ()).throw(AssertionError("parsed an oversize file")))
    got = memstop.read_record("sess-1")
    assert got == {"oversize": True, "attributed": False, "bytes_read": 0, "bytes_on_disk": (data / "memory_stop.json").stat().st_size}


def test_huge_or_odd_identity_values_are_not_carried(stop):
    _c, _d, data = stop
    (data / "memory_stop.json").write_text(json.dumps({"session_id": "sess-1", "kind": "x" * 1000, "at": "y" * 1000, "pid": "z" * 1000,
                                                       "uptime_s": [1] * 100}))
    got = memstop.read_record("sess-1")
    assert got["kind"] is None and got["at"] is None and got["pid"] is None and got["uptime_s"] is None
    assert len(json.dumps(got)) < 400


def test_a_record_that_cannot_be_written_is_a_logged_step_not_a_stop(stop, monkeypatch):
    calls, _d, data = stop
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    memstop.execute(DECISION, _Guard())
    assert not (data / "memory_stop.json").exists() and "shutdown" in calls


def test_a_record_that_would_pass_the_bound_is_cut_as_it_is_written_and_says_so(stop):
    """The writer measures what it writes: an inflated record is cut to the bound and names what it left out."""
    _c, _d, data = stop
    record = {"kind": "memory-stop", "session_id": "sess-1", "steps": {}, "guard": {"pad": "g" * 6000},
              "release_at_engage": {"pad": "r" * 6000}, "release_again": {"ok": True}}
    written = memstop._write(record)
    raw = (data / "memory_stop.json").read_bytes()
    assert written == len(raw) <= memstop.RECORD_MAX_BYTES
    got = memstop.read_record("sess-1")
    assert got["cut"]["left_out"] == ["release_at_engage", "release_again", "guard"] and "guard" not in got


def test_the_guards_sentence_is_cut_to_what_it_protects(stop):
    _c, _d, data = stop
    guard = _Guard()
    guard.state = lambda: {"reason": "y" * 5000, "last_reading": {}}
    rec = memstop.execute(DECISION, guard)
    assert len(rec["guard"]["reason"]) <= memstop.GUARD_REASON_CHARS


class _FakeTime:
    """Sleep advances the clock the wait is counted on, so a 60 s bound runs in no real time."""

    def __init__(self, monkeypatch):
        self.now = 1000.0
        self.slept: list[float] = []
        monkeypatch.setattr(memstop, "_clock", lambda: self.now)
        monkeypatch.setattr(memstop.time, "sleep", self.sleep)

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def _quiet(monkeypatch, **over):
    state = {"exclusive_window": False, "scheduler_hold": False, "leases": [], "gate_held": False, "gate_held_for_s": None}
    state.update(over)
    monkeypatch.setattr(memstop, "in_flight", lambda own_hold=True: {k: v for k, v in state.items() if own_hold or k != "scheduler_hold"})
    return state


def test_an_exclusive_operation_in_flight_is_waited_for_then_the_normal_shutdown_runs(stop, monkeypatch):
    calls, _d, _data = stop
    clock = _FakeTime(monkeypatch)
    state = _quiet(monkeypatch, exclusive_window=True)

    def end_after_four(_s):
        clock.now += _s
        clock.slept.append(_s)
        if len(clock.slept) >= 4:
            state["exclusive_window"] = False

    monkeypatch.setattr(memstop.time, "sleep", end_after_four)
    rec = memstop.execute(DECISION, _Guard())
    assert rec["in_flight_at_start"]["exclusive_window"] is True
    assert rec["exclusive"]["waited_s"] == 4.0 and rec["exclusive"]["still_in_flight"]["exclusive_window"] is False
    assert calls[-2:] == ["sentinel", "shutdown"], "the shutdown comes after the wait"


@pytest.mark.parametrize("what", [{"exclusive_window": True}, {"scheduler_hold": True}, {"leases": ["restore"]}, {"gate_held": True, "gate_held_for_s": 3.0}])
def test_anything_in_flight_is_recorded_at_start_and_waited_for_a_bounded_time(stop, monkeypatch, what):
    calls, _d, _data = stop
    clock = _FakeTime(monkeypatch)
    _quiet(monkeypatch, **what)
    rec = memstop.execute(DECISION, _Guard())
    for k, v in what.items():
        assert rec["in_flight_at_start"][k] == v
    if "scheduler_hold" in what:
        # the stop's own pause sets that hold: after the pause it is not a reason to wait
        assert rec["exclusive"]["waited_s"] == 0.0
    else:
        assert sum(clock.slept) == memstop.EXCLUSIVE_WAIT_S and rec["exclusive"]["waited_s"] == memstop.EXCLUSIVE_WAIT_S
    assert "shutdown" in calls, "the stop is not held hostage by it"


class _Sched:
    def __init__(self, held):
        self.held = held

    def holds_exclusive(self):
        return self.held

    def is_running(self):
        return True


@pytest.mark.parametrize("before", [False, True])
def test_the_scheduler_hold_is_read_before_the_stops_own_pause(stop, monkeypatch, before):
    """The pause sets the scheduler's hold itself. The start snapshot must show what was held BEFORE it: False when nothing was (the
    stop's own hold is not mistaken for an operation's), True when a restore or a move held it. Fails if the snapshot moves
    after the pause."""
    from src.scheduler import runner

    sched = _Sched(before)
    monkeypatch.setattr(runner, "get_scheduler", lambda: sched)
    monkeypatch.setattr(runner, "pause_for_exclusive_operation", lambda timeout=10.0: setattr(sched, "held", True) or True)
    rec = memstop.execute(DECISION, _Guard())
    assert rec["in_flight_at_start"]["scheduler_hold"] is before
    assert rec["loop_still_running"] is True, "a loop still alive after the pause is recorded as alive"


def test_the_wait_is_counted_in_elapsed_time_not_in_polls(stop, monkeypatch):
    """A slow poll (each sleep overshoots to 25 s) must end the 60 s bound after three polls, not after sixty."""
    calls, _d, _data = stop
    clock = _FakeTime(monkeypatch)
    monkeypatch.setattr(memstop.time, "sleep", lambda s: (clock.slept.append(s), setattr(clock, "now", clock.now + 25.0)))
    _quiet(monkeypatch, gate_held=True)
    rec = memstop.execute(DECISION, _Guard())
    assert len(clock.slept) == 3 and rec["exclusive"]["waited_s"] == 75.0 and "shutdown" in calls


def test_a_record_still_over_the_bound_after_the_first_cut_is_cut_to_its_identity_and_says_so(stop):
    _c, _d, data = stop
    record = {"kind": "memory-stop", "session_id": "sess-1", "pid": 1, "at": "t", "uptime_s": 1.0,
              "decision": {"n": 1}, "steps": {f"s{i}": {"ok": True, "pad": "p" * 100} for i in range(200)},
              "in_flight_at_start": {"pad": "q" * 3000}}
    written = memstop._write(record)
    assert written <= memstop.RECORD_MAX_BYTES
    got = memstop.read_record("sess-1")
    assert {"steps", "in_flight_at_start"} <= set(got["cut"]["left_out"]) and "steps" not in got and got["decision"] == {"n": 1}


def test_a_record_that_cannot_be_statted_or_parsed_reads_as_unreadable_not_absent(stop, monkeypatch):
    _c, _d, data = stop
    assert memstop.read_record("sess-1") is None, "no file: absent"
    (data / "memory_stop.json").write_text("{not json")
    assert memstop.read_record("sess-1") == {"unreadable": True, "error": "JSONDecodeError", "attributed": False}
    real = type(memstop._path())

    def denied(self, *a, **k):
        raise PermissionError("secret path text")

    monkeypatch.setattr(real, "stat", denied)
    got = memstop.read_record("sess-1")
    assert got == {"unreadable": True, "error": "PermissionError", "attributed": False}


def test_a_file_that_grew_after_the_stat_is_read_for_at_most_the_bound_plus_one_byte(stop, monkeypatch):
    _c, _d, data = stop
    f = data / "memory_stop.json"
    f.write_text("x" * (memstop.RECORD_MAX_BYTES * 20))
    real_stat = type(f).stat

    class _S:
        st_size = 10

    monkeypatch.setattr(type(f), "stat", lambda self, *a, **k: _S() if self.name == "memory_stop.json" else real_stat(self, *a, **k))
    asked: list = []
    real_open = open

    class _Spy:
        def __init__(self, fh):
            self._fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._fh.close()

        def read(self, n=-1):
            asked.append(n)
            return self._fh.read(n)

    monkeypatch.setattr(memstop, "open", lambda *a, **k: _Spy(real_open(*a, **k)), raising=False)
    got = memstop.read_record("sess-1")
    assert asked == [memstop.RECORD_MAX_BYTES + 1], "never an unbounded read"
    assert got["oversize"] is True and got["bytes_on_disk"] == 10 and got["grew_while_reading"] is True and got["bytes_read"] == 0


def test_a_loop_that_stopped_is_recorded_as_stopped(stop, monkeypatch):
    from src.scheduler import runner

    sched = _Sched(False)
    sched.is_running = lambda: False
    monkeypatch.setattr(runner, "get_scheduler", lambda: sched)
    rec = memstop.execute(DECISION, _Guard())
    assert rec["loop_still_running"] is False


def test_the_forced_snapshot_that_was_not_taken_is_not_recorded_as_ok(stop, monkeypatch):
    from src.monitoring import session_hwm

    monkeypatch.setattr(session_hwm, "observe", lambda *a, **k: None)
    rec = memstop.execute(DECISION, _Guard())
    assert rec["steps"]["snapshot"] == {"ok": False, "error": "RuntimeError"}


def test_an_unreadable_part_of_the_in_flight_snapshot_says_none_not_false(stop, monkeypatch):
    from src.database import corpus_lease

    monkeypatch.setattr(corpus_lease, "active_leases", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert memstop.in_flight()["leases"] is None


def test_a_pause_that_timed_out_is_recorded_and_the_stop_goes_on(stop, monkeypatch):
    from src.scheduler import runner

    calls, _d, _data = stop
    monkeypatch.setattr(runner, "pause_for_exclusive_operation", lambda timeout=10.0: False)
    rec = memstop.execute(DECISION, _Guard())
    assert rec["steps"]["pause"]["ok"] is True and rec["scheduler_stopped"] is False and "shutdown" in calls
