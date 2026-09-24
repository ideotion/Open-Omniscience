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
    # The bar is continuous COLLECTION (RR-10): this build records the collection loop,
    # none ran, so the bar is not reached and nothing is counting toward it. The process
    # half of the clause is read beside it, on the process stretches.
    assert s["bar_basis"] == "collection" and s["bar_reached"] is False
    assert s["hours_remaining_on_current_stretch"] is None
    assert s["collection"]["recorded"] is True and s["collection"]["stretches"] == 0
    assert s["process_bar"]["reached"] is False and s["process_bar"]["hours_remaining_on_current_stretch"] == 64.0
    assert s["discontinuous_total_s"] == s["uptime_total_s"]
    assert "CONTINUOUS" in s["method"] and "not the bar" in s["method"]
    gaps = c["gaps"]
    assert len(gaps) == 1 and gaps[0]["seconds"] == 7200 and "cannot know" in gaps[0]["basis"]
    kinds = [e["kind"] for e in c["events"]]
    assert kinds == ["boot", "suspend", "end-unclean", "boot"]


class Clocks:
    """Three COHERENT clocks (2026-09-24). Running advances all three; a suspend advances
    the wall and boot-time clocks; a clock change moves only the wall clock. The earlier
    form of the test below moved only the wall clock to "let 30 hours pass" -- which the
    ledger now correctly reads as a clock change, since nothing else moves one clock
    alone."""

    def __init__(self, monkeypatch, wall: float, *, boottime: bool = True) -> None:
        self.wall, self.mono, self.bt, self.has_bt = float(wall), 1_000.0, 50_000.0, boottime
        monkeypatch.setattr(sh.time, "time", lambda: self.wall)
        monkeypatch.setattr(sh.time, "monotonic", lambda: self.mono)
        monkeypatch.setattr(sh, "boottime", lambda: self.bt if self.has_bt else None)

    def run(self, s: float) -> None:
        self.wall += s
        self.mono += s
        self.bt += s

    def suspend(self, s: float) -> None:
        self.wall += s
        self.bt += s

    def step(self, s: float) -> None:
        self.wall += s


def test_the_bar_is_reached_on_one_collection_stretch_never_on_the_sum(ledger, monkeypatch):
    # three sessions collecting 30 h each, cleanly restarted: 90 h in total, no stretch of 72 h
    c = Clocks(monkeypatch, T0)
    for _ in range(3):
        sh._reset_for_tests()
        sh.record_boot({"state": "clean"})
        sh.record_event("collection", running=True)
        c.run(30 * 3600)
        sh.record_event("collection", running=False, stop_requested=True)
        sh.record_end(clean=True)
        c.run(3600)
    s = ch.chronology(anchor="install")["summary"]
    assert s["collection"]["total_s"] == 90 * 3600 and s["bar_reached"] is False
    assert s["collection"]["longest_stretch"]["seconds"] == 30 * 3600
    assert s["uptime_total_s"] == 90 * 3600
    # ...and one session collecting for 80 h reaches it, at the stretch's start + 72 h
    sh._reset_for_tests()
    sh.record_boot({"state": "clean"})
    start = c.wall
    sh.record_event("collection", running=True)
    c.run(80 * 3600)
    s2 = ch.chronology(anchor="install")["summary"]
    assert s2["bar_reached"] is True
    assert s2["bar_reached_at"] == ch._iso(start + 72 * 3600)
    assert s2["hours_remaining_on_current_stretch"] is None
    assert s2["collection"]["running_now"] is True


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


# --------------------------------------------------------------------------- #
#  The field round (2026-09-24, docs/audit/16_…): RR-5, RR-10, RR-11
# --------------------------------------------------------------------------- #
def test_a_backward_clock_correction_is_recorded_and_every_duration_stays_true(ledger, monkeypatch):
    """RR-5, the NUC: booted with the clock 12 hours fast, corrected by NTP an hour in.
    The chronology read 12 hours short, because the correction left no record and every
    duration was a difference of two wall stamps. Now the tick records the step against
    the boot-time clock, and the boot stamp is moved onto the corrected scale by it."""
    c = Clocks(monkeypatch, T0 + 12 * 3600)
    sh.record_boot(None)
    c.run(3600)
    sh.tick_once()
    c.step(-12 * 3600)
    c.run(60)
    sh.tick_once()
    c.run(60 * 3600)
    sh.tick_once()
    recs = sh.read_records()
    steps = [r for r in recs if r["kind"] == "clock-step"]
    assert len(steps) == 1 and steps[0]["step_s"] == -43200 and steps[0]["direction"] == "backward"
    assert steps[0]["clocks"] == "boot-time" and "not a suspend" in steps[0]["basis"]
    assert not [r for r in recs if r["kind"] == "suspend"], "a correction is not a suspend"
    s = ch.chronology(anchor="install")["summary"]
    true_up = 3600 + 60 + 60 * 3600
    assert s["since_last_restart_s"] == true_up
    assert s["current_stretch"]["seconds"] == true_up
    assert s["anchor_at"] == ch._iso(T0), "the boot, placed on the corrected clock"
    assert s["clock_steps"] == 1 and s["rebased_sessions"] == 0


def test_an_unrecorded_correction_is_rebased_from_the_sessions_own_span(ledger, monkeypatch):
    """The same correction with no tick between it and the reading (or a ledger from the
    build before clock-step records): the boot stamp disagrees with the session's span by
    12 hours, and the span wins, saying so."""
    c = Clocks(monkeypatch, T0 + 12 * 3600)
    sh.record_boot(None)
    c.run(3600)
    c.step(-12 * 3600)
    out = ch.chronology(anchor="install")
    sess = out["sessions"][-1]
    assert sess["rebased"]["moved_s"] == -43200 and "boot stamp disagreed" in sess["rebased"]["basis"]
    assert out["summary"]["since_last_restart_s"] == 3600
    assert out["summary"]["rebased_sessions"] == 1
    assert any("placed from their span" in cv for cv in out["summary"]["caveats"])
    assert "_clock" not in sess, "the internal clock object never leaves the read model"


def test_a_past_session_from_the_old_ledger_format_is_rebased_from_its_uptime(ledger, monkeypatch):
    """A 68b295b ledger: no span, no clock-step records -- only the end's monotonic uptime.
    That is enough to place a session whose boot stamp was 12 hours fast."""
    sh._append({"kind": "boot", "session_id": "old-1", "at": ch._iso(T0 + 12 * 3600), "pid": 1})
    sh._append({"kind": "end", "session_id": "old-1", "at": ch._iso(T0 + 30 * 3600), "clean": False,
                "basis": "the last liveness tick", "uptime_s": 30 * 3600.0, "written_by": "next-boot"})
    out = ch.chronology(anchor="install", now=T0 + 31 * 3600)
    sess = out["sessions"][0]
    assert sess["started_at"] == ch._iso(T0) and sess["uptime_s"] == 30 * 3600
    assert sess["rebased"]["moved_s"] == -43200


def test_the_boot_time_clock_tells_a_suspend_from_a_clock_change(ledger, monkeypatch):
    c = Clocks(monkeypatch, T0)
    sh.record_boot(None)
    c.run(60)
    sh.tick_once()
    c.suspend(7200)
    c.run(30)
    sh.tick_once()
    c.run(60)
    c.step(3 * 3600)
    sh.tick_once()
    recs = sh.read_records()
    assert [r["kind"] for r in recs] == ["boot", "suspend", "clock-step"]
    susp, step = recs[1], recs[2]
    assert susp["gap_s"] == 7200 and susp["clocks"] == "boot-time" and "cannot produce" in susp["basis"]
    assert susp["uptime_before_s"] == 60 and susp["uptime_s"] == 90
    assert step["step_s"] == 10800 and step["direction"] == "forward"
    s = ch.chronology(anchor="install")["summary"]
    assert s["suspends"] == 1 and s["clock_steps"] == 1 and s["stretches"] == 2
    assert s["uptime_total_s"] == 60 + 30 + 60, "running time only: the suspend is a hole, the step moves nothing"
    kinds = [e["kind"] for e in ch.chronology(anchor="install")["events"]]
    assert kinds == ["boot", "suspend", "clock-step"]


def test_without_a_boot_time_clock_a_backward_change_is_still_recorded(ledger):
    """No boot-time clock (macOS, Windows): a forward jump stays ambiguous with a suspend,
    but a BACKWARD one can only be a clock change -- the case that left no record at all."""
    sh.record_boot(None)
    m0 = sh._STARTED_MONO
    sh.tick_once(now_wall=T0 + 60, now_mono=m0 + 60)
    assert sh.tick_once(now_wall=T0 + 120 - 3600, now_mono=m0 + 120) is None
    rec = sh.read_records()[-1]
    assert rec["kind"] == "clock-step" and rec["step_s"] == -3600 and rec["clocks"] == "monotonic-only"
    assert "only a clock change" in rec["basis"]


def test_an_event_is_placed_by_its_uptime_across_a_correction(ledger, monkeypatch):
    c = Clocks(monkeypatch, T0 + 12 * 3600)
    sh.record_boot(None)
    c.run(600)
    sh.record_event("network", online=True)
    c.run(60)
    c.step(-12 * 3600)
    sh.tick_once()
    ev = next(e for e in ch.chronology(anchor="install")["events"] if e["kind"] == "event:network")
    assert ev["at"] == ch._iso(T0 + 600), "the event's stamp was fast; its uptime was not"


def test_a_process_up_for_days_with_its_collector_stopped_does_not_reach_the_bar(ledger, monkeypatch):
    """RR-10, Lenn: the process ran five days after a cancelled run while the collector
    was stopped (SCHED-1), and the chronology read "bar reached"."""
    c = Clocks(monkeypatch, T0)
    sh.record_boot(None)
    sh.record_event("collection", running=True)
    c.run(2 * 3600)
    sh.record_event("collection", running=False, stop_requested=True)
    c.run(5 * 24 * 3600)
    s = ch.chronology(anchor="install")["summary"]
    assert s["bar_basis"] == "collection" and s["bar_reached"] is False
    assert s["hours_remaining_on_current_stretch"] is None, "collection is not running, so nothing counts toward it"
    assert s["process_bar"]["reached"] is True, "the process half of the clause, beside the bar"
    assert s["collection"]["running_now"] is False
    assert s["collection"]["longest_stretch"]["seconds"] == 7200
    assert s["collection"]["longest_stretch"]["ended_by"] == "collection stopped"


def test_a_suspend_cuts_the_collection_stretch_too(ledger, monkeypatch):
    c = Clocks(monkeypatch, T0)
    sh.record_boot(None)
    sh.record_event("collection", running=True)
    c.run(40 * 3600)
    sh.tick_once()
    c.suspend(600)
    c.run(10)
    sh.tick_once()
    c.run(40 * 3600)
    s = ch.chronology(anchor="install")["summary"]
    assert s["collection"]["stretches"] == 2, "80 h of collection with a sleep in it is two stretches"
    assert s["bar_reached"] is False
    assert s["collection"]["current_stretch"]["seconds"] == 40 * 3600


def test_a_build_that_recorded_no_collection_leaves_the_bar_unknown(ledger, monkeypatch):
    """A session from before the collection events has no answer; it is never read as
    "collection never ran"."""
    sh._append({"kind": "boot", "session_id": "old-1", "at": ch._iso(T0), "pid": 1})
    out = ch.chronology(anchor="install", now=T0 + 100 * 3600)
    s = out["summary"]
    assert s["bar_reached"] is None and s["bar_basis"] == "not recorded"
    assert s["collection"]["recorded"] is False
    assert any("cannot be read" in cv for cv in s["caveats"])


def test_the_run_note_says_when_the_run_never_reached_its_soak(ledger, monkeypatch):
    from src.monitoring.release_run import RELEASE_RUN_SCHEMA, _write_state

    sh.record_boot(None)
    _write_state({"schema": RELEASE_RUN_SCHEMA, "run_id": "r9", "profile": "release-scale",
                  "started_at": ch._iso(T0), "outcome": "cancelled", "pid": os.getpid() + 7, "phase": None,
                  "phases": [{"name": "preflight", "status": "measured", "started_at": ch._iso(T0), "ended_at": ch._iso(T0 + 5)},
                             {"name": "p0_validation", "status": "cancelled"},
                             {"name": "soak", "status": "skipped"}]})
    s = ch.chronology(anchor="run", now=T0 + 3600)["summary"]
    assert s["run_note"] and "cancelled before its soak" in s["run_note"]
    assert s["run_note"] in s["caveats"]


def test_the_session_before_the_ledger_is_seeded_from_the_sentinel(ledger, monkeypatch):
    """RR-11: the ledger began with the PR #1162 build's first boot, so it read "0 unclean
    ends" on four machines whose forensics sentinel said the session before had died."""
    from src.monitoring import session_hwm

    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "session_hwm.json").write_text(json.dumps({
        "pid": 4242, "started_at": "2023-11-14T10:00:00+00:00", "last_ts": "2023-11-14T20:00:05+00:00",
        "rss_max_mb": 3500.0, "avail_min_mb": 76.0, "swap_used_max_mb": 8225.0, "phase": "collect"}),
        encoding="utf-8")
    session_hwm.reset_for_tests()
    b = sh.record_boot({"state": "running", "started_at": "2023-11-14T10:00:00+00:00", "pid": 4242})
    recs = sh.read_records()
    assert [r["kind"] for r in recs] == ["boot", "end", "boot"]
    seeded_boot, seeded_end = recs[0], recs[1]
    assert seeded_boot["source"] == "forensics-sentinel" and seeded_boot["at"] == "2023-11-14T10:00:00Z"
    assert seeded_boot["session_id"].startswith("pre-ledger-") and seeded_boot["pid"] == 4242
    assert seeded_end["clean"] is False and seeded_end["at"] == "2023-11-14T20:00:05Z"
    assert "high-water" in seeded_end["basis"]
    assert seeded_end["previous_peaks"]["swap_used_max_mb"] == 8225.0
    assert b["previous_closed_by_this_boot"] is True
    s = ch.chronology(anchor="install", now=T0 + 60)["summary"]
    assert s["unclean_ends"] == 1 and s["pre_ledger_sessions"] == 1 and s["restarts"] == 1
    assert any("before the ledger existed" in cv for cv in s["caveats"])
    # never seeded twice: the next boot finds a ledger and closes only its predecessor
    _boot_at(monkeypatch, T0 + 120, {"state": "clean", "started_at": ch._iso(T0), "ended_at": ch._iso(T0 + 100)})
    assert [r.get("source") for r in sh.read_records()].count("forensics-sentinel") == 2


def test_a_clean_sentinel_seeds_a_clean_end_and_no_start_seeds_nothing(ledger, monkeypatch):
    sh.record_boot({"state": "clean", "started_at": "2023-11-14T10:00:00+00:00",
                    "ended_at": "2023-11-14T11:00:00+00:00", "pid": 7})
    end = [r for r in sh.read_records() if r["kind"] == "end"][0]
    assert end["clean"] is True and end["at"] == "2023-11-14T11:00:00Z" and "clean-shutdown" in end["basis"]
    sh._reset_for_tests()
    sh.ledger_path().unlink()
    sh.record_boot({"state": "running"})
    assert [r["kind"] for r in sh.read_records()] == ["boot"], "a sentinel with no start cannot be placed"


def test_a_death_during_teardown_is_dated_from_the_teardown_stamp(ledger, monkeypatch):
    from src.monitoring import session_hwm

    session_hwm.reset_for_tests()
    sh.record_boot({"state": "shutting-down", "started_at": "2023-11-14T10:00:00+00:00",
                    "shutdown_phase_at": "2023-11-14T12:00:00+00:00", "pid": 9})
    end = [r for r in sh.read_records() if r["kind"] == "end"][0]
    assert end["clean"] is False and end["at"] == "2023-11-14T12:00:00Z" and "teardown" in end["basis"]


def test_a_gap_says_whether_the_machine_itself_rebooted(ledger, monkeypatch):
    monkeypatch.setattr(sh, "machine_boot_id", lambda: "boot-A")
    sh.record_boot(None)
    sh.record_end(clean=True)
    monkeypatch.setattr(sh, "machine_boot_id", lambda: "boot-B")
    _boot_at(monkeypatch, T0 + 3600, {"state": "clean"})
    g = ch.chronology(anchor="install", now=T0 + 7200)["gaps"][0]
    assert g["machine"] == "rebooted" and "kernel boot id changed" in g["basis"]
    monkeypatch.setattr(sh, "machine_boot_id", lambda: "boot-B")
    sh.record_end(clean=True)
    _boot_at(monkeypatch, T0 + 9000, {"state": "clean"})
    g2 = ch.chronology(anchor="install", now=T0 + 9600)["gaps"][1]
    assert g2["machine"] == "same boot" and "app alone" in g2["basis"]


def test_the_in_flight_phase_starts_where_the_LAST_finished_phase_ended():
    """The loop this replaced walked the list backwards without stopping, so the NUC's
    soak read as having started at the preflight."""
    state = {"run_id": "r", "outcome": None, "phase": "soak", "phases": [
        {"name": "preflight", "started_at": "a", "ended_at": "2026-09-19T19:29:21+02:00", "status": "measured"},
        {"name": "online_probes", "started_at": "b", "ended_at": "2026-09-19T08:35:06+02:00", "status": "measured"}]}
    assert ch._release_run_block(state)["phases"][-1]["started_at"] == "2026-09-19T08:35:06+02:00"
    state["phase_started_at"] = "2026-09-19T08:35:07+02:00"
    assert ch._release_run_block(state)["phases"][-1]["started_at"] == "2026-09-19T08:35:07+02:00"


def test_the_scheduler_loop_records_its_own_start_and_exit(ledger, monkeypatch):
    """The bar's evidence comes from the loop's own thread: every way collection starts
    or stops passes through it, and only it knows when the loop actually exited."""
    from src.scheduler import runner
    from src.scheduler.settings import SchedulerSettings

    sh.record_boot(None)
    monkeypatch.setattr(runner.BackgroundScheduler, "_loop", lambda self: self._stop.wait(10))
    sched = runner.BackgroundScheduler(settings_provider=lambda: SchedulerSettings())
    assert sched.start() is True
    sched.stop(timeout=5)
    evs = [r for r in sh.read_records() if r.get("event") == "collection"]
    assert [e["running"] for e in evs] == [True, False], evs
    assert evs[1]["stop_requested"] is True and "failure" not in evs[1]
    assert evs[0]["uptime_s"] is not None
