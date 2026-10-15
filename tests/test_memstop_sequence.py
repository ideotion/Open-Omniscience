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
                               "thresholds": {k: 10**9 for k in ("rss_pct_of_total", "avail_floor_mb", "trip_after_samples", "resume_after_samples", "resume_rss_pct")},
                               "last_reading": {k: 123456.789 for k in ("rss_mb", "mem_avail_mb", "mem_total_mb", "proc_swap_mb")}}
    memstop.execute({**DECISION, "extra": "z" * 100}, big_guard)
    got = memstop.read_record("sess-1")
    assert got["bytes_read"] == (data / "memory_stop.json").stat().st_size
    assert got["bytes_read"] <= memstop.RECORD_MAX_BYTES


def test_a_record_over_the_bound_is_read_with_its_size_and_cut_named(stop):
    _c, _d, data = stop
    (data / "memory_stop.json").write_text(json.dumps({"session_id": "sess-1", "decision": {"pad": "p" * (memstop.RECORD_MAX_BYTES + 10)}}))
    got = memstop.read_record("sess-1")
    assert got["bytes_read"] > memstop.RECORD_MAX_BYTES
    assert got["decision"] == {"cut": "the record was larger than the bound it is written within", "bytes": got["bytes_read"]}


def test_a_record_that_cannot_be_written_is_a_logged_step_not_a_stop(stop, monkeypatch):
    calls, _d, data = stop
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    rec = memstop.execute(DECISION, _Guard())
    assert rec["bytes_written"] is None and "shutdown" in calls


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


def test_an_exclusive_operation_in_flight_is_waited_for_then_the_normal_shutdown_runs(stop, monkeypatch):
    from src.scheduler import runner

    calls, _d, _data = stop
    state = {"open": True, "polls": 0}

    def still_open():
        state["polls"] += 1
        if state["polls"] > 4:
            state["open"] = False
        return state["open"]

    monkeypatch.setattr(runner, "exclusive_window_open", still_open)
    monkeypatch.setattr(memstop.time, "sleep", lambda s: None)
    rec = memstop.execute(DECISION, _Guard())
    assert rec["exclusive"] == {"open_at_start": True, "waited_s": 3.0, "still_open": False}
    assert calls[-2:] == ["sentinel", "shutdown"], "the shutdown comes after the wait"


def test_an_exclusive_operation_that_never_ends_is_waited_for_a_bounded_time_and_recorded(stop, monkeypatch):
    from src.scheduler import runner

    calls, _d, _data = stop
    slept: list[float] = []
    monkeypatch.setattr(runner, "exclusive_window_open", lambda: True)
    monkeypatch.setattr(memstop.time, "sleep", lambda s: slept.append(s))
    rec = memstop.execute(DECISION, _Guard())
    assert sum(slept) == memstop.EXCLUSIVE_WAIT_S
    assert rec["exclusive"] == {"open_at_start": True, "waited_s": memstop.EXCLUSIVE_WAIT_S, "still_open": True}
    assert "shutdown" in calls, "the stop is not held hostage by it"


def test_a_pause_that_timed_out_is_recorded_and_the_stop_goes_on(stop, monkeypatch):
    from src.scheduler import runner

    calls, _d, _data = stop
    monkeypatch.setattr(runner, "pause_for_exclusive_operation", lambda timeout=10.0: False)
    rec = memstop.execute(DECISION, _Guard())
    assert rec["steps"]["pause"]["ok"] is True and rec["scheduler_stopped"] is False and "shutdown" in calls
