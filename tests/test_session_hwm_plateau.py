"""A machine that STAYS short is recorded, not only the slide into it.

The 091717 instance sat at 44-60 MB available for 17 minutes with the memory guard engaged
and was then killed. The slide into it had been snapshotted (one per new low); the plateau,
where whatever held the memory could still be read, was not, by design. Two more triggers:
the moment the memory guard engages, and a re-snapshot every ``_PLATEAU_INTERVAL_S`` while the
machine is still below the line or the guard is still engaged.
"""

from __future__ import annotations

import gc
import json
import time as real_time
import types

import pytest

from src.monitoring import forensics, session_hwm

TOTAL = 4000.0
LINE = TOTAL * 0.15  # 600 MB
SHORT = {"rss_mb": 3300.0, "avail_mb": 60.0, "total_mb": TOTAL, "swap_used_mb": 1024.0}
HEALTHY = {"rss_mb": 900.0, "avail_mb": 3000.0, "total_mb": TOTAL, "swap_used_mb": 0.0}
ENGAGED = {"engaged": True, "since": "2026-09-30T18:50:50+00:00", "reason": "only 168 MB", "engagements": 1}
OFF = {"engaged": False, "since": None, "reason": None, "engagements": 1}


@pytest.fixture
def dd(monkeypatch, tmp_path):
    d = tmp_path / "data"
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    return d


@pytest.fixture
def rig(dd, monkeypatch):
    """A clock, memory readings and a guard state the test drives, one ``tick`` at a time."""
    session_hwm.reset_for_tests()
    state = {"now": 1000.0, "readings": dict(SHORT), "guard": dict(OFF)}
    monkeypatch.setattr(
        session_hwm,
        "time",
        types.SimpleNamespace(monotonic=lambda: state["now"], perf_counter=real_time.perf_counter),
    )
    monkeypatch.setattr(session_hwm, "_readings", lambda: dict(state["readings"]))
    monkeypatch.setattr(session_hwm, "_guard_view", lambda: dict(state["guard"]) if state["guard"] else None)
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: [])
    session_hwm.capture_previous()

    def tick(dt: float = 5.0, **change) -> list[str]:
        """Advance the clock, apply ``change`` (readings / guard), observe once as the liveness
        thread does, and return every snapshot's reason so far."""
        state["now"] += dt
        for key, value in change.items():
            state[key] = value
        session_hwm.observe(may_snapshot_threads=True)
        return [s["why"] for s in session_hwm.current().get("pressure", [])]

    yield tick
    session_hwm.reset_for_tests()


def test_a_plateau_under_the_line_is_recorded_every_five_minutes_not_every_tick(rig):
    """MUTATION TARGET. The slide is one snapshot per new low and a plateau got none, however
    long; now it gets one per ``_PLATEAU_INTERVAL_S`` and no more."""
    assert rig(0) == ["memory short"], "the crossing"
    for _ in range(10):  # 50 s on the plateau: nothing
        got = rig(5.0)
    assert got == ["memory short"]
    assert rig(session_hwm._PLATEAU_INTERVAL_S - 50.0 - 1.0) == ["memory short"], "one second early"
    assert rig(1.0) == ["memory short", "memory still short"], "five minutes after the last one"
    assert rig(session_hwm._PLATEAU_INTERVAL_S - 1.0) == ["memory short", "memory still short"]
    assert rig(1.0)[-1] == "memory still short" and len(session_hwm.current()["pressure"]) == 3


def test_a_machine_with_memory_to_spare_and_no_guard_records_nothing_however_long(rig):
    assert rig(0, readings=dict(HEALTHY)) == []
    for _ in range(100):
        got = rig(session_hwm._PLATEAU_INTERVAL_S)
    assert got == [], "the plateau trigger is for a machine that is short or paused, not any machine"


def test_the_guard_engaging_is_its_own_snapshot_and_says_so(rig):
    """MUTATION TARGET. The guard engages at its own, lower line, usually between two slide
    snapshots; the moment itself is recorded, with the guard's own reason."""
    assert rig(0, readings=dict(HEALTHY)) == []
    assert rig(5.0) == []
    got = rig(5.0, guard=dict(ENGAGED))
    assert got == ["memory guard engaged"]
    [snap] = session_hwm.current()["pressure"]
    assert snap["guard"] == ENGAGED
    assert rig(5.0) == ["memory guard engaged"], "still engaged, not a new engagement"
    # engaged with memory fine (an RSS trip): the plateau trigger follows the guard, not the line
    assert rig(session_hwm._PLATEAU_INTERVAL_S) == ["memory guard engaged", "memory still short"]
    assert session_hwm.current()["pressure"][-1]["guard"]["engaged"] is True
    # released: no more, however long
    assert rig(5.0, guard=dict(OFF)) == ["memory guard engaged", "memory still short"]
    assert rig(10 * session_hwm._PLATEAU_INTERVAL_S) == ["memory guard engaged", "memory still short"]


def test_the_engagement_is_not_reported_twice_when_another_trigger_took_the_tick(rig):
    """MUTATION TARGET. The guard's baseline is read on EVERY tick; evaluated only when no
    other trigger fires it goes stale, and the next tick reports a pause that is five seconds
    old as a new engagement."""
    assert rig(0, guard=dict(ENGAGED)) == ["memory short"], "the crossing takes the tick"
    [snap] = session_hwm.current()["pressure"]
    assert snap["guard"]["engaged"] is True, "and still says the pause was in force"
    assert rig(5.0) == ["memory short"], "the next tick is the same pause, not a new one"


def test_a_flapping_guard_cannot_make_a_snapshot_a_second(rig):
    gap = session_hwm._PRESSURE_MIN_INTERVAL_S
    assert gap > 1.0
    rig(0, readings=dict(HEALTHY), guard=dict(OFF))
    assert rig(1.0, guard=dict(ENGAGED)) == ["memory guard engaged"]
    rig(1.0, guard=dict(OFF))
    assert rig(1.0, guard=dict(ENGAGED)) == ["memory guard engaged"], "inside the interval: none"
    rig(1.0, guard=dict(OFF))
    got = rig(gap, guard=dict(ENGAGED))
    assert got == ["memory guard engaged", "memory guard engaged"], "after the interval: one"


def test_an_unreadable_or_disabled_guard_changes_nothing(rig):
    assert rig(0, readings=dict(HEALTHY), guard=None) == []
    assert rig(session_hwm._PLATEAU_INTERVAL_S * 3) == []
    assert rig(5.0, readings=dict(SHORT)) == ["memory short"], "the line still works without it"
    assert "guard" not in session_hwm.current()["pressure"][0]


def test_the_recorder_never_walks_the_heap_objects(dd, monkeypatch):
    """The recorder runs when memory is nearly gone and the heap holds tens of millions of
    objects: it may read counters (``sys.getallocatedblocks``, the kernel's /proc), never list
    the objects."""
    session_hwm.reset_for_tests()
    walked = []
    for name in ("get_objects", "get_referrers", "get_referents"):
        monkeypatch.setattr(gc, name, lambda *a, _n=name, **k: walked.append(_n) or [])
    monkeypatch.setattr(session_hwm, "_readings", lambda: dict(SHORT))
    monkeypatch.setattr(session_hwm, "_guard_view", lambda: dict(ENGAGED))
    walks = []
    real = session_hwm.composition
    monkeypatch.setattr(
        session_hwm, "composition", lambda *, walk_heap=True: walks.append(walk_heap) or real(walk_heap=walk_heap)
    )
    session_hwm.capture_previous()
    session_hwm.observe(may_snapshot_threads=True)  # the real thread_snapshot, the real stacks
    [snap] = session_hwm.current()["pressure"]
    assert snap["threads"] and "py_alloc_blocks" in snap["memory"]
    assert walked == [] and walks and not any(walks), "no heap walk, no object listing"
    session_hwm.reset_for_tests()


def test_a_snapshot_is_bounded_by_the_existing_stack_caps(dd, monkeypatch):
    """The stacks are the existing helper's, with its caps: ``_STACK_APP_FRAMES`` app frames and
    at most ``_STACK_WALK_MAX`` frames walked per thread, however deep the stack."""
    session_hwm.reset_for_tests()

    def deep(n, ev):
        if n == 0:
            ev.wait(10)
            return
        deep(n - 1, ev)

    import threading

    ev = threading.Event()
    t = threading.Thread(target=deep, args=(400, ev), name="oo-fake-deep", daemon=True)
    t.start()
    try:
        by_name = {e["name"]: e for e in session_hwm.thread_snapshot()}
    finally:
        ev.set()
        t.join(5)
    assert len(by_name["oo-fake-deep"]["stack"]) <= session_hwm._STACK_APP_FRAMES + 2
    session_hwm.reset_for_tests()


def test_the_new_snapshots_reach_the_next_boot_and_the_report_names_them(rig, dd):
    rig(0, guard=dict(ENGAGED))
    rig(session_hwm._PLATEAU_INTERVAL_S)
    rig(session_hwm._PLATEAU_INTERVAL_S)
    doc = json.loads((dd / "session_pressure.json").read_text(encoding="utf-8"))
    assert doc["taken"] == 3 and [s["why"] for s in doc["snapshots"]] == [
        "memory short", "memory still short", "memory still short",
    ]
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": {
        "available": True, "pressure": doc["snapshots"], "pressure_taken": doc["taken"]}}})
    assert "1 when memory ran short below 600.0 MB available; 2 while memory stayed short" in txt
    assert "memory still short (memory guard engaged since 2026-09-30T18:50:50+00:00)" in txt
    engaged = {"at": "t", "why": "memory guard engaged", "guard": ENGAGED, "avail_mb": 168.0}
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": {
        "available": True, "pressure": [engaged], "pressure_taken": 1}}})
    assert "1 when the memory guard engaged" in txt


def test_the_guard_view_is_four_fields_and_never_raises(monkeypatch):
    from src.scheduler import memguard

    class Fake:
        def __init__(self, st):
            self._st = st

        def state(self):
            if isinstance(self._st, Exception):
                raise self._st
            return self._st

        def reset(self, **_kw):  # the suite's isolation fixture resets the singleton
            return None

    full = {"enabled": True, "engaged": True, "since": "s", "reason": "r", "engagements": 2,
            "thresholds": {"avail_floor_mb": 256.0}, "last_reading": {"rss_mb": 1.0}}
    monkeypatch.setattr(memguard, "memory_guard", Fake(full))
    assert session_hwm._guard_view() == {"engaged": True, "since": "s", "reason": "r", "engagements": 2}
    monkeypatch.setattr(memguard, "memory_guard", Fake(dict(full, enabled=False)))
    assert session_hwm._guard_view() is None, "a disabled guard is not a paused one"
    monkeypatch.setattr(memguard, "memory_guard", Fake(RuntimeError("boom")))
    assert session_hwm._guard_view() is None
