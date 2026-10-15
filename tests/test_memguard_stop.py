"""The clean stop's criterion (B2): ``memguard.stall_decision`` and the guard's stall window, driven by a fake clock.

The criterion is replayed on a series SHAPED like the 2026-09-30 plateau (engaged, then 64 MB or less for more than ten minutes at
1.5 s per reading) and must stay silent on every quiet shape that matters. The series are generated here, numbers only."""
from __future__ import annotations

import pytest

from src.scheduler import memguard
from src.scheduler.memguard import MemoryGuard, stall_decision


def _series(start: float, seconds: float, avail, step: float = 1.5):
    out, t = [], start
    while t <= start + seconds:
        out.append((t, avail(t - start) if callable(avail) else avail))
        t += step
    return out


NOW = 1000.0


def _decide(samples, **kw):
    return stall_decision(samples, kw.pop("now", NOW), rss_mb=kw.pop("rss", 1500.0), total_mb=kw.pop("total", 3900.0), **kw)


def test_a_plateau_at_the_floor_that_holds_the_machines_memory_is_due():
    d = _decide(_series(NOW - 310, 310, 48.0))
    assert d["due"] is True and d["low_share"] == 1.0 and d["held_share"] > 1 / 3


def test_the_window_is_the_last_300_seconds_only():
    d = _decide(_series(NOW - 310, 310, 48.0))
    assert d["window_s"] == 300.0 and d["span_s"] >= 285.0


@pytest.mark.parametrize(
    "name,samples,rss,why",
    [
        # a dip that recovers at 150 s: one reading above twice the floor breaks the plateau
        ("recovers", _series(NOW - 310, 310, lambda s: 48.0 if s < 150 or s > 153 else 400.0), 1500.0, "recovered"),
        # hovering at 70 to 100 MB: above the floor, below the guard's own line
        ("hover", _series(NOW - 310, 310, lambda s: 70.0 + (s % 30)), 1500.0, "at the floor"),
        # the plateau is real but this process holds 10 per cent of the RAM
        ("held elsewhere", _series(NOW - 310, 310, 48.0), 390.0, "held elsewhere"),
        # readings missing for half the window: too few, and the span is short
        ("gap", _series(NOW - 310, 100, 48.0) + _series(NOW - 40, 40, 48.0), 1500.0, "no readings"),
        # only the last 100 s are at the floor
        ("short plateau", _series(NOW - 100, 100, 48.0), 1500.0, "span"),
    ],
)
def test_the_quiet_shapes_stay_silent(name, samples, rss, why):
    d = _decide(samples, rss=rss)
    assert d["due"] is False, (name, d)
    assert why in d["why"], (name, d)


def test_ten_percent_in_the_window_above_the_floor_is_tolerated_but_not_more():
    # 120 MB is above the floor and below twice it: a tenth of the readings may be there (the share is 0.9 or a little over)
    nine_in_ten = _series(NOW - 310, 310, lambda s: 120.0 if int(s / 1.5) % 10 == 0 else 48.0)
    assert _decide(nine_in_ten)["due"] is True
    mostly = _series(NOW - 310, 310, lambda s: 100.0 if int(s / 1.5) % 4 == 0 else 48.0)
    assert _decide(mostly)["due"] is False


def test_a_silent_stretch_at_the_end_is_not_a_plateau():
    d = _decide(_series(NOW - 310, 270, 48.0))  # the last reading is 40 s old
    assert d["due"] is False and "no readings" in d["why"]


def test_fewer_than_ten_readings_is_not_a_plateau():
    d = _decide(_series(NOW - 300, 300, 48.0, step=40.0))
    assert d["due"] is False and "too few readings" in d["why"]


def test_an_unreadable_process_size_never_stops_the_app():
    d = stall_decision(_series(NOW - 310, 310, 48.0), NOW, rss_mb=None, total_mb=None)
    assert d["due"] is False and "could not be read" in d["why"]


def test_the_environment_sets_the_window_and_the_floor(monkeypatch):
    series = _series(NOW - 130, 130, 90.0)
    assert _decide(series, window_s=120.0, floor_mb=100.0)["due"] is True
    assert _decide(series, window_s=120.0, floor_mb=64.0)["due"] is False


# -- the guard's window -------------------------------------------------------------------------------------------------------


class _Clock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t


def _guard(monkeypatch, calls, **kw):
    clock = _Clock()
    monkeypatch.setattr(memguard.time, "monotonic", clock)
    g = MemoryGuard(trip_after=3, resume_after=2, release_fn=lambda: {"ok": True}, stop_fn=lambda d, guard: calls.append(d), **kw)
    return g, clock


def _feed(g, clock, seconds, avail, step=1.5, rss=1500.0, total=3900.0):
    for _ in range(int(seconds / step)):
        clock.t += step
        g.observe(rss_mb=rss, mem_avail_mb=avail, mem_total_mb=total)
    join_stop(g)


def join_stop(g):
    """The stop runs on its own named thread (it waits; the sampler must not): wait for it before asserting what it did."""
    t = g._stop_thread
    if t is not None:
        t.join(5)
        assert not t.is_alive()


def test_the_guard_hands_the_process_to_the_stop_once(monkeypatch):
    calls: list = []
    g, clock = _guard(monkeypatch, calls)
    _feed(g, clock, 330, 48.0)
    assert len(calls) == 1 and calls[0]["due"] is True
    _feed(g, clock, 120, 48.0)
    assert len(calls) == 1, "one shot"
    assert g.state()["stop"]["started"] is True


def test_a_recovery_empties_the_window(monkeypatch):
    calls: list = []
    g, clock = _guard(monkeypatch, calls)
    _feed(g, clock, 200, 48.0)
    _feed(g, clock, 6, 900.0)  # healthy with margin: resume_after consecutive samples release the guard
    assert not g.engaged
    assert g.state()["stop"]["last_decision"] is None, "the last answer is about an engagement that ended"
    assert len(g._stall) == 0, "the window the recovery ended is gone"
    # 270 s is under the 285 s the window needs to cover: the readings before the recovery, if they survived, would make it 300+
    _feed(g, clock, 270, 48.0)
    assert calls == [], "the clock started again at the new engagement"


def test_an_operators_reset_empties_the_window(monkeypatch):
    calls: list = []
    g, clock = _guard(monkeypatch, calls)
    _feed(g, clock, 250, 48.0)
    g.reset()
    _feed(g, clock, 100, 48.0)
    assert calls == []


def test_the_stop_is_off_with_the_environment_switch(monkeypatch):
    calls: list = []
    monkeypatch.setenv("OO_MEM_STOP", "0")
    g, clock = _guard(monkeypatch, calls)
    _feed(g, clock, 400, 48.0)
    assert calls == [] and g.engaged and g.state()["stop"]["enabled"] is False


def test_the_guard_off_means_no_stop(monkeypatch):
    calls: list = []
    monkeypatch.setenv("OO_MEM_GUARD", "0")
    g, clock = _guard(monkeypatch, calls)
    _feed(g, clock, 400, 48.0)
    assert calls == []


def test_a_stop_that_raises_leaves_the_pause_in_force(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(memguard.time, "monotonic", clock)

    def boom(d, guard):
        raise RuntimeError("stop failed")

    g = MemoryGuard(trip_after=3, resume_after=2, release_fn=lambda: {}, stop_fn=boom)
    _feed(g, clock, 330, 48.0)
    assert g.engaged


def test_missing_readings_count_nothing(monkeypatch):
    calls: list = []
    g, clock = _guard(monkeypatch, calls)
    for _ in range(300):
        clock.t += 1.5
        g.observe(rss_mb=None, mem_avail_mb=None, mem_total_mb=None)
    assert calls == [] and not g.engaged and len(g._stall) == 0
    # and a stretch of unreadable ones inside an engaged window leaves a gap the criterion refuses to bridge
    _feed(g, clock, 150, 48.0)
    assert g.engaged
    for _ in range(100):
        clock.t += 1.5
        g.observe(rss_mb=None, mem_avail_mb=None, mem_total_mb=None)
    _feed(g, clock, 60, 48.0)
    assert calls == [], "150 s of readings, 150 s of none, 60 s of readings is not a plateau"


def test_the_window_holds_readings_for_its_span_only(monkeypatch):
    calls: list = []
    g, clock = _guard(monkeypatch, calls, )
    monkeypatch.setenv("OO_MEM_STOP_WINDOW_S", "30")
    monkeypatch.setenv("OO_MEM_STOP_AVAIL_MB", "64")
    _feed(g, clock, 120, 200.0)  # engaged (below 256) but above the floor: nothing stalls
    assert calls == [] and len(g._stall) <= 30 / 1.5 + 2


def test_a_window_set_below_the_minimum_is_raised_to_it(monkeypatch):
    """A one-second window (twenty readings 0.05 s apart) would stop the app on a passing dip; the minimum raises it, and says so."""
    calls: list = []
    monkeypatch.setenv("OO_MEM_STOP_WINDOW_S", "1")
    g, clock = _guard(monkeypatch, calls)
    _feed(g, clock, 12, 48.0, step=0.05)
    assert g.engaged and calls == []
