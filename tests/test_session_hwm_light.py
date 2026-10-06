"""A LIGHT snapshot every 15 s while memory is near the memory guard's line (the #1308 follow-up).

The heavy snapshots are one per new low and one per five minutes on a plateau, because each walks
every thread and can cost 0.3-0.6 s of the liveness thread under a burst. The October kills came
within seconds of the last one. Near the guard's line a lighter record is taken every 15 s: the
kernel's counters, the Python block count and what it gained, and the three threads that spent the
most CPU since the previous light snapshot. It has its own ring and its own file, so it can never
push a heavy snapshot out, and it never walks the heap.
"""

from __future__ import annotations

import gc
import json
import sys
import threading
import time as real_time
import types

import pytest

from src.monitoring import forensics, session_hwm

TOTAL = 5000.0
FLOOR, SHARE = 256.0, 85.0
HEALTHY = {"rss_mb": 900.0, "avail_mb": 3000.0, "total_mb": TOTAL, "swap_used_mb": 0.0}
# 384 MB is 1.5 times the floor: inside it by avail; RSS well under the share
NEAR_AVAIL = {"rss_mb": 1500.0, "avail_mb": 380.0, "total_mb": TOTAL, "swap_used_mb": 0.0}
# 57% of RAM is 1/1.5 of the 85% share: inside it by RSS; memory itself not short
NEAR_RSS = {"rss_mb": 0.58 * TOTAL, "avail_mb": 1500.0, "total_mb": TOTAL, "swap_used_mb": 0.0}
ENGAGED = {"engaged": True, "since": "2026-10-06T03:00:00+00:00", "reason": "only 200 MB", "engagements": 1}
OFF = {"engaged": False, "since": None, "reason": None, "engagements": 1}


@pytest.fixture
def no_heavy(monkeypatch):
    """The heavy triggers' line moved out of reach, so a test sees the light one alone."""
    monkeypatch.setattr(session_hwm, "_PRESSURE_AVAIL_SHARE", 0.0)
    monkeypatch.setattr(session_hwm, "_BURST_BLOCKS", 10**15)


@pytest.fixture
def dd(monkeypatch, tmp_path):
    d = tmp_path / "data"
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    return d


@pytest.fixture
def rig(dd, monkeypatch):
    """A clock, readings and a guard state the test drives, one ``tick`` (5 s: the liveness thread's
    cadence) at a time. The heavy snapshot's line is 15% of RAM (750 MB here), so ``NEAR_AVAIL`` is
    heavy-short as well: a test that wants the light trigger alone asks for ``no_heavy``."""
    session_hwm.reset_for_tests()
    state = {"now": 1000.0, "readings": dict(HEALTHY), "guard": dict(OFF)}
    clock = types.SimpleNamespace(monotonic=lambda: state["now"], perf_counter=real_time.perf_counter)
    monkeypatch.setattr(session_hwm, "time", clock)
    monkeypatch.setattr(session_hwm, "_readings", lambda: dict(state["readings"]))
    monkeypatch.setattr(session_hwm, "_guard_view", lambda: dict(state["guard"]) if state["guard"] else None)
    monkeypatch.setattr(session_hwm, "_guard_line", lambda: (FLOOR, SHARE))
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: [])
    session_hwm.capture_previous()

    def tick(dt: float = 5.0, **change) -> list[dict]:
        state["now"] += dt
        for key, value in change.items():
            state[key] = value
        session_hwm.observe(may_snapshot_threads=True)
        return session_hwm.current().get("pressure_light", [])

    tick.state = state
    yield tick
    session_hwm.reset_for_tests()


def _whys(light):
    return [s["why"] for s in light]


# --- when -----------------------------------------------------------------------------------------


def test_a_machine_far_from_the_line_takes_no_light_snapshot_however_long(rig):
    for _ in range(200):
        got = rig(5.0)
    assert got == [] and "pressure" not in session_hwm.current()


def test_near_the_floor_by_available_memory_one_every_fifteen_seconds_not_every_tick(rig, no_heavy):
    """MUTATION TARGET: the cadence. The liveness thread reads every 5 s; three reads make one."""
    rig.state["readings"] = dict(NEAR_AVAIL)
    taken = [len(rig(5.0)) for _ in range(12)]  # 60 s
    assert taken == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4], taken


def test_each_way_of_being_near_is_named(rig, no_heavy):
    assert _whys(rig(5.0, readings=dict(NEAR_AVAIL))) == ["available memory near the guard's floor"]
    assert _whys(rig(15.0, readings=dict(NEAR_RSS)))[-1] == "process memory near the guard's share"
    # the guard ENGAGING is the heavy snapshot's own moment and takes that tick; the ticks after it
    # are the light ones, with the guard's state carried
    rig(5.0, readings=dict(HEALTHY), guard=dict(ENGAGED))
    assert _whys(session_hwm.current()["pressure"])[-1] == "memory guard engaged"
    got = rig(15.0)
    assert _whys(got)[-1] == "memory guard engaged" and got[-1]["guard"] == ENGAGED
    before = len(got)
    assert len(rig(15.0, guard=dict(OFF))) == before, "back to healthy: none"


def test_just_outside_the_factor_is_not_near(rig, no_heavy):
    out = dict(HEALTHY, avail_mb=FLOOR * 1.5 + 1.0, rss_mb=0.5 * TOTAL)
    assert rig(5.0, readings=out) == []
    assert _whys(rig(5.0, readings=dict(out, avail_mb=FLOOR * 1.5))) == ["available memory near the guard's floor"]


def test_an_unreadable_guard_line_takes_none_by_readings_and_never_raises(rig, no_heavy, monkeypatch):
    monkeypatch.setattr(session_hwm, "_guard_line", lambda: (None, None))
    assert rig(5.0, readings=dict(NEAR_AVAIL), guard=None) == []
    rig(5.0, readings=dict(HEALTHY), guard=dict(ENGAGED))  # the engagement itself is the heavy one's
    assert _whys(rig(15.0)) == ["memory guard engaged"], "a paused guard needs no line to be near it"


def test_a_heavy_snapshot_takes_the_tick_and_the_heavy_ring_is_never_pushed_out(rig):
    """The light ring is its own: a day of light snapshots must not displace a heavy one. MUTATION
    TARGET: appending light snapshots to the heavy ring."""
    heavy = dict(NEAR_AVAIL)  # 380 MB is under the 750 MB heavy line: the crossing is heavy
    got = rig(5.0, readings=heavy)
    assert got == [] and _whys(session_hwm.current()["pressure"]) == ["memory short"], "the heavy took the tick"
    for _ in range(60):
        got = rig(5.0)
    cur = session_hwm.current()
    assert [s["why"] for s in cur["pressure"]][0] == "memory short", "the crossing is still there"
    assert len(got) == session_hwm._LIGHT_KEEP, "newest eight kept"
    assert len(cur["pressure"]) <= session_hwm._PRESSURE_KEEP
    assert session_hwm._LIGHT_TAKEN > session_hwm._LIGHT_KEEP


# --- what -----------------------------------------------------------------------------------------


class _Workers:
    """Threads that sit in test code (so their innermost frame is not a wait) with CPU times the
    test controls through ``cpu``."""

    def __init__(self, names):
        self.stop = threading.Event()
        self.threads = []
        self.ready = []
        for n in names:
            ev = threading.Event()
            t = threading.Thread(target=self._run, args=(ev,), name=n, daemon=True)
            t.start()
            ev.wait(5)
            self.threads.append(t)
        self.cpu = {t.native_id: 0.0 for t in self.threads}

    def _run(self, ev):
        ev.set()
        # ``time.sleep`` is a C call: the innermost PYTHON frame is this loop, in test code, so the
        # thread is classified as working (an ``Event.wait`` would put it in threading.py: waiting)
        while not self.stop.is_set():
            real_time.sleep(0.01)

    def tid(self, name):
        return next(t.native_id for t in self.threads if t.name == name)

    def close(self):
        self.stop.set()
        for t in self.threads:
            t.join(5)


@pytest.fixture
def workers(monkeypatch):
    w = _Workers(["oo-a", "oo-b", "oo-c", "oo-d"])
    reads = []

    def fake_cpu(tids):
        reads.append(list(tids))
        return {t: w.cpu[t] for t in tids if t in w.cpu}

    monkeypatch.setattr(session_hwm, "_thread_cpu", fake_cpu)
    w.reads = reads
    yield w
    w.close()


def test_the_busiest_threads_by_cpu_since_the_previous_snapshot_with_their_stacks(rig, no_heavy, workers):
    """MUTATION TARGET: ranking by the lifetime total instead of the delta; reporting a first
    reading's total as if it were recent."""
    rig.state["readings"] = dict(NEAR_AVAIL)
    for n, c in (("oo-a", 900.0), ("oo-b", 10.0), ("oo-c", 500.0), ("oo-d", 1.0)):
        workers.cpu[workers.tid(n)] = c
    [first] = rig(5.0)
    assert all("cpu_delta_s" not in t for t in first["threads"]), "no earlier reading: no delta, not a total"
    for n, c in (("oo-a", 900.5), ("oo-b", 40.0), ("oo-c", 502.0), ("oo-d", 21.0)):
        workers.cpu[workers.tid(n)] = c
    got = rig(15.0)
    top = [t for t in got[-1]["threads"] if t["name"].startswith("oo-")]
    assert [t["name"] for t in top] == ["oo-b", "oo-d", "oo-c"], "by the delta (30, 20, 2), not the total"
    assert [t["cpu_delta_s"] for t in top] == [30.0, 20.0, 2.0]
    assert len(got[-1]["threads"]) == session_hwm._LIGHT_THREADS == 3
    assert all(t["stack"] and t["tid"] for t in got[-1]["threads"])
    assert got[-1]["working_threads"] >= 4


def test_a_thread_the_previous_reading_did_not_see_has_no_delta_and_ranks_after(rig, no_heavy, workers):
    """A thread with no earlier reading is not given its lifetime total as if it were recent: it has
    no ``cpu_delta_s``, and it ranks after every thread that has one."""
    rig.state["readings"] = dict(NEAR_AVAIL)
    rig(5.0)  # baseline: every worker at 0.0
    workers.cpu[workers.tid("oo-a")] = 3.0
    workers.cpu[workers.tid("oo-b")] = 2.0
    workers.cpu[workers.tid("oo-c")] = 1.0
    del workers.cpu[workers.tid("oo-d")]
    got = rig(15.0)  # d is not read this time, so it is out of the next baseline
    assert [t["name"] for t in got[-1]["threads"]] == ["oo-a", "oo-b", "oo-c"]
    workers.cpu[workers.tid("oo-d")] = 5000.0  # back, with a huge lifetime total and no baseline
    workers.cpu[workers.tid("oo-a")] = 4.0
    del workers.cpu[workers.tid("oo-b")], workers.cpu[workers.tid("oo-c")]
    got = rig(15.0)
    names = [t["name"] for t in got[-1]["threads"]]
    assert names[:2] == ["oo-a", "oo-d"], names
    d = got[-1]["threads"][1]
    assert "cpu_delta_s" not in d and d["cpu_s"] == 5000.0


def test_the_blocks_gained_are_the_processs_and_say_over_how_long(rig, no_heavy, monkeypatch):
    blocks = {"n": 1_000_000}
    monkeypatch.setattr(sys, "getallocatedblocks", lambda: blocks["n"])
    rig.state["readings"] = dict(NEAR_AVAIL)
    [first] = rig(5.0)
    assert "blocks_gained" not in first, "no earlier snapshot to gain since"
    blocks["n"] += 250_000
    got = rig(15.0)
    assert got[-1]["blocks_gained"] == 250_000 and got[-1]["over_s"] == 15.0
    assert got[-1]["memory"]["py_alloc_blocks"] == 1_250_000


def test_cpu_is_read_for_a_bounded_number_of_threads_however_many_are_working(rig, no_heavy, workers):
    """Every /proc read waits for the GIL under a burst (``_thread_cpu``), so the cost has a cap."""
    extra = _Workers([f"oo-x{i}" for i in range(40)])
    try:
        rig.state["readings"] = dict(NEAR_AVAIL)
        rig(5.0)
    finally:
        extra.close()
    assert max(len(r) for r in workers.reads) <= session_hwm._LIGHT_CPU_CANDIDATES


def test_a_light_snapshot_never_walks_the_heap_and_says_what_it_cost(dd, monkeypatch):
    """The real helpers, no fakes: counters and stacks only, and the instrument reports its own cost."""
    session_hwm.reset_for_tests()
    walked = []
    for name in ("get_objects", "get_referrers", "get_referents"):
        monkeypatch.setattr(gc, name, lambda *a, _n=name, **k: walked.append(_n) or [])
    walks = []
    real = session_hwm.composition
    monkeypatch.setattr(
        session_hwm, "composition", lambda *, walk_heap=True: walks.append(walk_heap) or real(walk_heap=walk_heap)
    )
    monkeypatch.setattr(session_hwm, "_readings", lambda: dict(NEAR_AVAIL))
    monkeypatch.setattr(session_hwm, "_guard_view", lambda: dict(OFF))
    monkeypatch.setattr(session_hwm, "_guard_line", lambda: (FLOOR, SHARE))
    monkeypatch.setattr(session_hwm, "_PRESSURE_AVAIL_SHARE", 0.0)
    session_hwm.capture_previous()
    session_hwm.observe(may_snapshot_threads=True)
    [snap] = session_hwm.current()["pressure_light"]
    assert walked == [] and walks and not any(walks)
    assert isinstance(snap["took_ms"], float) and snap["took_ms"] < 2000.0
    assert "py_alloc_blocks" in snap["memory"] and "threads" in snap
    session_hwm.reset_for_tests()


def test_the_collectors_monitor_never_takes_one(rig, no_heavy):
    rig.state["readings"] = dict(NEAR_AVAIL)
    session_hwm.observe()  # may_snapshot_threads defaults to False: the monitor that feeds the guard
    assert "pressure_light" not in session_hwm.current()


# --- where it is kept -------------------------------------------------------------------------------


def test_they_are_written_through_to_their_own_file_and_reach_the_next_boot(rig, no_heavy, dd):
    rig.state["readings"] = dict(NEAR_AVAIL)
    rig(5.0)
    rig(15.0)
    doc = json.loads((dd / "session_pressure_light.json").read_text(encoding="utf-8"))
    assert doc["taken"] == 2 and len(doc["snapshots"]) == 2 and "INFERENCE" in doc["method"]
    assert not (dd / "session_pressure.json").exists(), "the heavy file is untouched"
    # the next boot reads them back, only when they are the SAME session's
    got = session_hwm._read_record()
    assert got["pressure_light_taken"] == 2 and len(got["pressure_light"]) == 2
    doc["pid"] = (doc["pid"] or 0) + 1
    (dd / "session_pressure_light.json").write_text(json.dumps(doc), encoding="utf-8")
    assert "pressure_light" not in session_hwm._read_record(), "another session's file is never read"
    # and a new session starts without the old file
    session_hwm.capture_previous()
    assert not (dd / "session_pressure_light.json").exists()


def test_the_report_names_them_and_says_the_pairing_is_an_inference(rig, no_heavy, workers):
    rig.state["readings"] = dict(NEAR_AVAIL)
    for n, c in (("oo-a", 5.0), ("oo-b", 1.0), ("oo-c", 1.0), ("oo-d", 1.0)):
        workers.cpu[workers.tid(n)] = c
    rig(5.0)
    workers.cpu[workers.tid("oo-a")] += 7.5
    got = rig(15.0)
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": {
        "available": True, "pressure_light": got, "pressure_light_taken": 9}}})
    assert "near the memory guard's line, 2 snapshot(s) of 9 taken, the newest kept" in txt
    assert "which thread allocated the blocks gained is an inference" in txt
    assert "oo-a (+7.5 s of CPU)" in txt and "took " in txt
    # a record with the count but no file says so, as the heavy ones do
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": {
        "available": True, "pressure_light_taken": 4}}})
    assert "4 light snapshot(s) were taken, but their file (session_pressure_light.json) was not found" in txt


def test_the_bundles_method_text_says_what_the_light_snapshots_are(dd, monkeypatch):
    monkeypatch.setattr(session_hwm, "previous", lambda: {"pid": 1, "pressure_light": []})
    out = forensics._previous_peaks()
    assert "pressure_light" in out["method"] and "inference" in out["method"]


# --- the one bundle member (the slot contract of the single Diagnostics zip) ---------------------------


def test_the_member_carries_this_sessions_tail_and_the_previous_ones_with_the_method(rig, no_heavy, dd):
    rig.state["readings"] = dict(NEAR_AVAIL)
    rig(5.0)
    rig(15.0)
    # the next boot (a new process has loaded nothing yet): this session's file becomes the previous tail
    session_hwm._PREV_LOADED, session_hwm._PREV = False, None
    session_hwm.capture_previous()
    rig.state["readings"] = dict(NEAR_AVAIL)
    rig(5.0)
    out = session_hwm.diagnostics_member(200_000)
    assert "error" not in out and "INFERENCE" in out["method"] and out["interval_s"] == 15.0
    assert out["previous_session"]["found"] is True
    assert out["previous_session"]["taken"] == 2 and len(out["previous_session"]["snapshots"]) == 2
    assert out["this_session"]["taken"] == 1 and len(out["this_session"]["snapshots"]) == 1
    assert out["previous_session"]["dropped_oldest_to_fit"] == 0
    json.dumps(out)  # a member is JSON


def test_a_member_over_its_budget_keeps_the_newest_and_says_how_many_it_cut(rig, no_heavy):
    rig.state["readings"] = dict(NEAR_AVAIL)
    for _ in range(6):
        rig(15.0)
    ring = session_hwm.current()["pressure_light"]
    assert len(ring) == 6
    one = len(json.dumps(ring[-1], separators=(",", ":")))
    out = session_hwm.diagnostics_member(1024 + 2 * (2 * one + 10))
    mine = out["this_session"]
    assert mine["snapshots"] and mine["dropped_oldest_to_fit"] == 6 - len(mine["snapshots"]) > 0
    assert mine["snapshots"][-1]["at"] == ring[-1]["at"], "the NEWEST is what stays"
    assert len(json.dumps(mine["snapshots"], separators=(",", ":"))) <= (1024 + 2 * (2 * one + 10) - 1024) // 2


def test_the_member_never_raises_and_a_boot_with_no_record_is_said_not_blank(monkeypatch):
    monkeypatch.setattr(session_hwm, "previous", lambda: None)
    monkeypatch.setattr(session_hwm, "current", lambda: {})
    out = session_hwm.diagnostics_member(50_000)
    assert out["previous_session"]["found"] is False and out["previous_session"]["snapshots"] == []
    assert session_hwm.diagnostics_member(-5)["method"], "a nonsense budget is raised to the smallest, not an error"
    monkeypatch.setattr(session_hwm, "current", lambda: (_ for _ in ()).throw(RuntimeError("boom\nsecond line")))
    assert session_hwm.diagnostics_member(50_000) == {"error": "RuntimeError: boom"}
