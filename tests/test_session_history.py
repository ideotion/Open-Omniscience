"""The session ledger and the chronology (2026-09-18, maintainer-asked: *"what if I
don't know when the machine stopped?"*).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Driven with INJECTED clocks: a suspend is the difference between two clocks over one
tick, an unclean end is the last minute a dead session was seen, and both are
asserted from the file the next boot reads -- never from a sleep. The negative space
is the point: no seconds for an end that has no time, no cause for a gap, no bar from
a sum of stretches.
"""

from __future__ import annotations

import json
import os

import pytest

from src.monitoring import chronology as ch
from src.monitoring import session_history as sh

T0 = 1_700_000_000.0  # 2023-11-14T22:13:20Z


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    """An isolated data dir, the liveness thread off, the wall clock frozen at T0 for
    boots (ticks take explicit clocks)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: T0)
    yield tmp_path / "data"
    sh._reset_for_tests()


def _boot_at(monkeypatch, epoch: float, prev_state=None):
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: epoch)
    return sh.record_boot(prev_state)


# --------------------------------------------------------------------------- #
#  The ledger
# --------------------------------------------------------------------------- #
def test_a_boot_writes_one_line_and_a_clean_end_its_own(ledger, monkeypatch):
    rec = sh.record_boot(None)
    assert rec["kind"] == "boot" and rec["pid"] == os.getpid()
    assert sh.current_session()["session_id"] == rec["session_id"]
    end = sh.record_end(clean=True, reason="SIGTERM")
    assert end["clean"] is True and end["basis"] == "this session's own shutdown hook"
    kinds = [r["kind"] for r in sh.read_records()]
    assert kinds == ["boot", "end"]
    # the liveness file exists and names this session
    assert sh.read_liveness()["session_id"] == rec["session_id"]


def test_the_next_boot_closes_a_dead_session_from_its_last_liveness_tick(ledger, monkeypatch):
    b1 = sh.record_boot(None)
    sh.tick_once(now_wall=T0 + 3600 * 5, now_mono=sh._STARTED_MONO + 3600 * 5)  # seen at +5 h
    # ...then it dies. The next boot reads forensics' sentinel ("running" = unclean).
    b2 = _boot_at(monkeypatch, T0 + 3600 * 7, {"state": "running"})
    assert b2["previous_closed_by_this_boot"] is True
    recs = sh.read_records()
    end = [r for r in recs if r["kind"] == "end"][0]
    assert end["session_id"] == b1["session_id"]
    assert end["clean"] is False and end["written_by"] == "next-boot"
    assert end["at"] == "2023-11-15T03:13:20Z", "dated from the last liveness tick, not from the new boot"
    assert "liveness" in end["basis"]


def test_a_clean_previous_session_is_closed_from_the_sentinel_when_its_line_is_missing(ledger, monkeypatch):
    sh.record_boot(None)  # no record_end: the sentinel says clean anyway (an older build's shutdown)
    b2 = _boot_at(monkeypatch, T0 + 100, {"state": "clean", "ended_at": "2023-11-14T22:14:00Z"})
    end = [r for r in sh.read_records() if r["kind"] == "end"][0]
    assert end["clean"] is True and end["at"] == "2023-11-14T22:14:00Z" and "sentinel" in end["basis"]
    assert b2["previous_closed_by_this_boot"] is True


def test_a_previous_session_with_neither_sentinel_nor_liveness_gets_an_end_with_no_time(ledger, monkeypatch):
    sh.record_boot(None)
    sh.liveness_path().unlink()  # a lost file
    _boot_at(monkeypatch, T0 + 100, {"state": "running"})
    end = [r for r in sh.read_records() if r["kind"] == "end"][0]
    assert end["at"] is None and end["clean"] is False and "no time" in end["basis"]


def test_a_boot_does_not_close_a_session_that_already_has_an_end(ledger, monkeypatch):
    sh.record_boot(None)
    sh.record_end(clean=True)
    b2 = _boot_at(monkeypatch, T0 + 100, {"state": "clean", "ended_at": "x"})
    assert b2["previous_closed_by_this_boot"] is False
    assert [r["kind"] for r in sh.read_records()] == ["boot", "end", "boot"]


def test_a_suspend_is_the_wall_clock_running_ahead_of_the_monotonic_one(ledger):
    sh.record_boot(None)
    m0 = sh._STARTED_MONO
    assert sh.tick_once(now_wall=T0 + 60, now_mono=m0 + 60) is None, "a normal tick"
    assert sh.tick_once(now_wall=T0 + 60 + 119, now_mono=m0 + 60) is None, "under the threshold"
    s = sh.tick_once(now_wall=T0 + 60 + 119 + 60 + 7200, now_mono=m0 + 120)
    assert s is not None and s["kind"] == "suspend"
    assert s["gap_s"] == 7200, "the gap is this tick's wall advance minus its monotonic advance"
    assert "clock" in s["basis"] and "hibernation" in s["basis"]
    assert [r["kind"] for r in sh.read_records()] == ["boot", "suspend"]


def test_the_ledger_tolerates_a_damaged_line_and_compacts_to_the_newest(ledger):
    sh.record_boot(None)
    with open(sh.ledger_path(), "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
        for i in range(10):
            fh.write(json.dumps({"kind": "event", "event": f"e{i}", "at": "x"}) + "\n")
    recs = sh.read_records()
    assert len(recs) == 11 and recs[-1]["event"] == "e9"
    dropped = sh.compact_if_needed(max_lines=5)
    assert dropped == 7
    assert [r.get("event") for r in sh.read_records()] == ["e5", "e6", "e7", "e8", "e9"]


def test_record_event_carries_its_fields_and_needs_no_session(ledger):
    rec = sh.record_event("network", online=True)
    assert rec["session_id"] is None and rec["online"] is True
    assert sh.read_records()[0]["event"] == "network"


# --------------------------------------------------------------------------- #
#  The chronology
# --------------------------------------------------------------------------- #
@pytest.fixture
def two_sessions(ledger, monkeypatch):
    """Session 1: boots at T0, suspends 6 h after two minutes, is last seen at +30 h
    wall (it died). Session 2: boots at +32 h and is still running at +40 h."""
    sh.record_boot(None)
    m0 = sh._STARTED_MONO
    sh.tick_once(now_wall=T0 + 60, now_mono=m0 + 60)
    sh.tick_once(now_wall=T0 + 120 + 3600 * 6, now_mono=m0 + 120)
    sh.tick_once(now_wall=T0 + 3600 * 30, now_mono=m0 + 3600 * 24)
    _boot_at(monkeypatch, T0 + 3600 * 32, {"state": "running"})
    return T0 + 3600 * 40


def test_the_summary_counts_restarts_stretches_and_the_honest_downtime(two_sessions):
    now = two_sessions
    c = ch.chronology(anchor="install", now=now)
    s = c["summary"]
    assert s["anchor"] == "install" and s["anchor_at"] == "2023-11-14T22:13:20Z"
    assert s["wall_clock_s"] == 40 * 3600
    # stretches: 120 s, then (30 h - 6 h - 120 s) = 86280 s, then the current 8 h
    assert s["stretches"] == 3 and s["uptime_total_s"] == 120 + 86280 + 8 * 3600
    assert s["downtime_s"] == 6 * 3600 + 2 * 3600, "the suspend and the gap, nothing invented"
    assert s["restarts"] == 1 and s["since_last_restart_s"] == 8 * 3600
    assert s["suspends"] == 1 and s["unclean_ends"] == 1 and s["unknown_end_sessions"] == 0
    assert s["longest_stretch"]["seconds"] == 86280 and s["longest_stretch"]["current"] is False
    assert s["current_stretch"]["seconds"] == 8 * 3600
    assert s["bar_reached"] is False and s["hours_remaining_on_current_stretch"] == 64.0
    assert s["discontinuous_total_s"] == s["uptime_total_s"]
    assert "CONTINUOUS" in s["method"] and "not the bar" in s["method"]
    gaps = c["gaps"]
    assert len(gaps) == 1 and gaps[0]["seconds"] == 7200 and "cannot know" in gaps[0]["basis"]
    kinds = [e["kind"] for e in c["events"]]
    assert kinds == ["boot", "suspend", "end-unclean", "boot"]


def test_the_bar_is_reached_on_one_stretch_never_on_the_sum(ledger, monkeypatch):
    # three sessions of 30 h each, cleanly restarted: 90 h in total, no stretch of 72 h
    t = T0
    for _ in range(3):
        _boot_at(monkeypatch, t, {"state": "clean", "ended_at": None})
        monkeypatch.setattr(sh.time, "time", lambda t=t: t + 30 * 3600)
        sh.record_end(clean=True)
        t += 31 * 3600
    s = ch.chronology(anchor="install", now=t)["summary"]
    assert s["uptime_total_s"] == 90 * 3600 and s["bar_reached"] is False
    assert s["longest_stretch"]["seconds"] == 30 * 3600
    # ...and one session of 80 h reaches it, at start + 72 h
    _boot_at(monkeypatch, t, {"state": "clean"})
    s2 = ch.chronology(anchor="install", now=t + 80 * 3600)["summary"]
    assert s2["bar_reached"] is True
    assert s2["bar_reached_at"] == ch._iso(t + 72 * 3600)
    assert s2["hours_remaining_on_current_stretch"] is None


def test_an_end_with_no_time_contributes_nothing_and_is_counted_as_unknown(ledger, monkeypatch):
    sh.record_boot(None)
    sh.liveness_path().unlink()
    _boot_at(monkeypatch, T0 + 3600 * 10, {"state": "running"})
    c = ch.chronology(anchor="install", now=T0 + 3600 * 12)
    s = c["summary"]
    assert s["unknown_end_sessions"] == 1
    assert s["uptime_total_s"] == 2 * 3600, "only the current session's known stretch"
    assert s["downtime_s"] is None, "no downtime figure can be honest with an unknown end"
    assert any("no time" in cv for cv in s["caveats"])
    assert c["gaps"][0]["seconds"] is None


def test_the_run_anchor_uses_the_release_run_start_and_falls_back_honestly(ledger, monkeypatch):
    sh.record_boot(None)
    now = T0 + 3600 * 10
    c = ch.chronology(anchor="run", now=now)
    assert c["summary"]["anchor"] == "install" and "fell back" in c["summary"]["anchor_basis"]
    from src.monitoring.release_run import RELEASE_RUN_SCHEMA, _write_state

    _write_state({"schema": RELEASE_RUN_SCHEMA, "run_id": "r1", "profile": "million",
                  "started_at": ch._iso(T0 + 3600 * 4), "outcome": None, "pid": os.getpid() + 7,
                  "phase": "soak", "phases": [{"name": "preflight", "started_at": ch._iso(T0 + 3600 * 4),
                                               "ended_at": ch._iso(T0 + 3600 * 4 + 10), "status": "measured"}],
                  "heartbeats": [{"at": ch._iso(T0 + 3600 * 5), "rss_mb": 300.0, "elapsed_h": 1.0}],
                  "soak": {"started_at": ch._iso(T0 + 3600 * 4)}, "updated_at": ch._iso(T0 + 3600 * 9)})
    c = ch.chronology(anchor="run", now=now)
    s = c["summary"]
    assert s["anchor"] == "run" and s["anchor_at"] == ch._iso(T0 + 3600 * 4) and "r1" in s["anchor_basis"]
    assert s["wall_clock_s"] == 6 * 3600 and s["uptime_total_s"] == 6 * 3600 and s["restarts"] == 0
    rr = c["release_run"]
    assert rr["run_id"] == "r1" and rr["phases"][-1] == {"name": "soak", "started_at": ch._iso(T0 + 3600 * 4 + 10),
                                                          "ended_at": None, "status": "in-flight"}
    assert rr["heartbeats"] == [{"at": ch._iso(T0 + 3600 * 5), "rss_mb": 300.0, "elapsed_h": 1.0,
                                 "memory_guard_engaged": None}]


def test_the_vitals_summary_is_the_three_numbers_and_never_a_fabricated_count(ledger, monkeypatch):
    ch._VITALS_CACHE.update({"at": 0.0, "value": None})
    empty = ch.for_vitals()
    assert empty["restarts_since_ledger_start"] == 0 and empty["uptime_s"] is None
    sh.record_boot(None)
    monkeypatch.setattr(sh.time, "monotonic", lambda: sh._STARTED_MONO + 90)
    ch._VITALS_CACHE.update({"at": 0.0, "value": None})
    v = ch.for_vitals()
    assert v["uptime_s"] == 90 and v["since_last_restart_s"] == 90 and v["sessions_recorded"] == 1
    assert v["restarts_since_ledger_start"] == 0 and v["previous_session_end"] is None
    assert "ledger" in v["method"]


def test_the_chronology_endpoint_and_the_vitals_carry_it(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    with TestClient(app) as c:
        r = c.get("/api/diagnostics/chronology?anchor=install")
        assert r.status_code == 200
        body = r.json()
        assert body["schema"] == "oo-chronology-1" and "summary" in body and "sessions" in body
        assert body["summary"]["bar_hours"] == 72.0
        v = c.get("/api/system/vitals").json()
        assert "session" in v and "restarts_since_ledger_start" in v["session"]
