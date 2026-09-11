"""P6: back the collector off on event-loop lag -- and the measurement that says it won't.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

P4a removed the blanket CPU back-off and recorded one honest cost: the API server shares
this process, so cutting collector permits used to free GIL time for it, and not cutting
them might make the local UI feel slower. P6 is the direct measurement of that concern.

THE MEASUREMENT CAME BACK NEGATIVE -- request latency was flat from 0 workers to 32 on a
4-core box (p50 3.4-3.6 ms, p95 ~4 ms) and loop-lag p95 stayed at or under 11 ms -- so
this control is a net for a case the bench could not produce, not a fix for one it did.
That makes the NEGATIVE SPACE the whole suite: what it refuses to call starvation, and
what it does when its own response turns out not to help. A control that fires on the
measured workload's 210 ms singleton spike, or that descends forever against a cause it
cannot reach, would be worse than no control at all.
"""

from __future__ import annotations

import time

import pytest

from src.monitoring import collect_perf, latency
from src.monitoring.collect_perf import CollectionMonitor, loop_starvation
from src.scheduler.bandwidth import BandwidthGovernor

_IDLE_WRITER = {"waiters": 0, "total_wait_s": 0.0, "peak_waiters": 0}
_HEALTHY = {"cpu_sys_pct": 20.0, "cpu_proc_pct": 10.0, "mem_avail_mb": 4000.0, "rss_mb": 200.0}


@pytest.fixture(autouse=True)
def _clean_lag():
    latency._reset_for_tests()
    yield
    latency._reset_for_tests()


def _inject(samples: list[float]) -> None:
    """Put watchdog readings in the window, at the watchdog's own 0.2 s cadence."""
    now = time.monotonic()
    with latency._LOCK:
        latency._LAG.clear()
        for i, v in enumerate(reversed(samples)):
            latency._LAG.appendleft((now - i * 0.2, v))


# --------------------------------------------------------------------------- #
#  The reading: a fraction, because neither published number can drive a control.
# --------------------------------------------------------------------------- #


def test_an_unsampled_window_is_absent_not_healthy():
    """The refusal the whole design rests on. A missing reading and a quiet loop are
    opposite claims, and a control that reads the first as the second is acting on
    nothing."""
    p = latency.loop_pressure(250.0)
    assert p["measured"] is False
    assert p["fraction"] is None, "an absent fraction must never be 0.0"
    assert p["peak_ms"] is None
    assert "watchdog" in p["reason"]
    assert loop_starvation(p) == (False, None)


def test_one_spike_in_a_healthy_window_is_a_spike_not_starvation():
    """THE measured case, and the reason the reading is a fraction. At 32 collector
    threads the peak reached 210 ms while the p50 stayed at 2 ms. A peak rule calls that
    starvation for the next seven governor ticks, because latency.py's window is 10 s and
    the governor ticks every 1.5 s."""
    _inject([1.0] * 49 + [210.0])
    p = latency.loop_pressure(250.0)
    assert p["measured"] is True
    assert p["peak_ms"] == 210.0, "the peak is still published -- it is just not the rule"
    assert p["fraction"] == 0.0
    assert loop_starvation(p) == (False, 0.0)

    # ...and the same window read against a bar the spike DOES clear stays a spike,
    # because one sample in fifty is a spike whatever the bar is.
    p2 = latency.loop_pressure(50.0)
    assert p2["fraction"] == 0.02
    assert loop_starvation(p2)[0] is False


def test_sustained_lag_is_starvation():
    _inject([400.0] * 30 + [1.0] * 20)
    p = latency.loop_pressure(250.0)
    assert p["fraction"] == 0.6
    lagging, frac = loop_starvation(p)
    assert lagging is True and frac == 0.6


def test_the_fraction_bar_is_configurable_and_zero_disables_the_control(monkeypatch):
    """Off is expressed as off. A threshold set so high it can never be reached would be
    a disabled control that still looks armed -- the shape this project calls fabricated
    security when it appears in a security surface."""
    _inject([400.0] * 30 + [1.0] * 20)
    p = latency.loop_pressure(250.0)
    monkeypatch.setenv("OO_LOOP_LAG_BACKOFF_FRACTION", "0")
    lagging, frac = loop_starvation(p)
    assert lagging is False
    assert frac == 0.6, "disabled must still REPORT the reading it is not acting on"
    monkeypatch.setenv("OO_LOOP_LAG_BACKOFF_FRACTION", "0.9")
    assert loop_starvation(p)[0] is False
    monkeypatch.setenv("OO_LOOP_LAG_BACKOFF_FRACTION", "0.5")
    assert loop_starvation(p)[0] is True


def test_a_garbled_threshold_falls_back_to_the_default_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("OO_LOOP_LAG_BACKOFF_MS", "not-a-number")
    monkeypatch.setenv("OO_LOOP_LAG_BACKOFF_FRACTION", "")
    assert collect_perf.loop_lag_thresholds() == (
        collect_perf._LOOP_LAG_MS,
        collect_perf._LOOP_LAG_FRACTION,
    )


# --------------------------------------------------------------------------- #
#  The governor: a fourth reason, kept distinct from the other three.
# --------------------------------------------------------------------------- #


def test_the_governor_cuts_one_permit_and_names_loop_lag():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    new, reason = g.observe(100.0, loop_lagging=True)
    assert (new, reason) == (19, "loop-lag"), "linear, like the other throughput costs"


def test_a_more_certain_harm_keeps_its_own_name():
    """Four reasons, not one blurred 'contention'. A reader of the perf log has to be
    able to tell which lever moved the permits, because the remedies differ."""
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    assert g.observe(100.0, mem_low=True, loop_lagging=True)[1] == "mem-low"
    g._sem.set_permits(20)
    assert g.observe(100.0, writer_saturated=True, loop_lagging=True)[1] == "writer-saturated"
    g._sem.set_permits(20)
    assert g.observe(100.0, cpu_saturated=True, loop_lagging=True)[1] == "cpu-saturated"
    g._sem.set_permits(20)
    assert g.observe(100.0, loop_lagging=True)[1] == "loop-lag"


def test_the_floor_holds():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(1)
    assert g.observe(100.0, loop_lagging=True) == (1, "loop-lag")


# --------------------------------------------------------------------------- #
#  THE DISCRIMINATION the queue asked for, driven through the real tick.
# --------------------------------------------------------------------------- #


def _pin_cpu_count(monkeypatch, n: int = 4) -> None:
    """Pin the core count these tests reason about.

    ``cpu_contention`` divides the process's CPU percent by the core count, so a vitals
    pair that reads "the machine is full and it is US" on a 4-core box reads "it is
    someone else" on a 16-core runner -- and the tick would then back off for
    cpu-saturation and never reach the property under test. The core count is not what
    these tests are about, so it is fixed rather than inherited from the runner.
    """
    monkeypatch.setattr(collect_perf, "_CPU_COUNT", n)


def _monitor(governor, vitals, tmp_path, *, running_for_s: float = 30.0):
    """A monitor for a pass that has ALREADY been running.

    The tick reads only lag measured since its own pass began, so a monitor constructed
    milliseconds ago would see none of the samples these tests inject -- and a test that
    backdated nothing would be asserting against an empty window rather than against the
    behaviour it names. Production monitors run for minutes; ``running_for_s`` says so out
    loud instead of leaving the tests silently dependent on construction order.
    """
    mon = CollectionMonitor(
        governor=governor,
        pass_id="p6",
        mode="rss",
        rate_fn=lambda: 200.0,
        vitals_fn=lambda: vitals,
        writer_stats_fn=lambda: _IDLE_WRITER,
    )
    mon._started_mono = time.monotonic() - running_for_s
    return mon


def test_a_busy_collector_with_a_responsive_loop_is_not_backed_off(tmp_path, monkeypatch):
    """The case P4a exists to protect: the machine is full BECAUSE we are working, and
    the loop is fine. Nothing may cut permits here -- that was the measured 50-to-1
    collapse."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _pin_cpu_count(monkeypatch)
    _inject([2.0] * 50)  # exactly what 32 workers measured at the median
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    mon = _monitor(g, {**_HEALTHY, "cpu_sys_pct": 99.0, "cpu_proc_pct": 390.0}, tmp_path)
    mon._tick()
    sample = collect_perf.recent_samples(1)[-1]
    assert sample["adjust_reason"] != "loop-lag"
    assert sample["loop"]["measured"] is True
    assert sample["loop_backoff"]["engaged"] is False
    assert g._sem.permits >= 20


def test_a_starving_loop_is_backed_off(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _pin_cpu_count(monkeypatch)
    _inject([400.0] * 50)
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    mon = _monitor(g, {**_HEALTHY, "cpu_sys_pct": 99.0, "cpu_proc_pct": 390.0}, tmp_path)
    mon._tick()
    sample = collect_perf.recent_samples(1)[-1]
    assert sample["adjust_reason"] == "loop-lag"
    assert sample["loop_backoff"]["engaged"] is True
    assert g._sem.permits == 19


def test_the_reading_rides_every_sample_even_when_it_does_not_fire(tmp_path, monkeypatch):
    """A control that measures something and shows nothing leaves an operator unable to
    tell 'we watched and it was fine' from 'nobody looked'. On the measured workload this
    control never fires, so the reading is most of what it delivers."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _inject([1.0] * 50)
    g = BandwidthGovernor(mode="maximum", w_max=50)
    mon = _monitor(g, _HEALTHY, tmp_path)
    mon._tick()
    loop = collect_perf.recent_samples(1)[-1]["loop"]
    assert loop["measured"] is True and loop["fraction"] == 0.0
    assert loop["peak_ms"] == 1.0 and loop["samples"] == 50


def test_an_unreadable_loop_never_reads_as_a_breach(tmp_path, monkeypatch):
    """Instrumentation must not be able to fail the thing it measures, and a broken read
    must not act. Both directions in one tick."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def _boom(*_a, **_kw):
        raise RuntimeError("no loop here")

    monkeypatch.setattr(latency, "loop_pressure", _boom)
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    mon = _monitor(g, _HEALTHY, tmp_path)
    mon._tick()  # must not raise
    sample = collect_perf.recent_samples(1)[-1]
    assert sample["loop"]["measured"] is False
    assert "no loop here" in sample["loop"]["reason"]
    assert sample["loop_backoff"]["engaged"] is False
    assert sample["adjust_reason"] != "loop-lag"
    # Not `== 20`: a healthy machine in maximum mode RAMPS, so the property is that a
    # broken reading never CUT, not that the tick did nothing.
    assert g._sem.permits >= 20


# --------------------------------------------------------------------------- #
#  A PASS MUST NOT BE CHARGED FOR A STALL THAT PREDATES IT.
# --------------------------------------------------------------------------- #


def test_lag_recorded_before_the_pass_began_is_not_this_pass_contention(tmp_path, monkeypatch):
    """The defect this pins was shipped and then found by its symptom.

    ``latency._LAG`` is process-global over a ten-second wall-clock window, so a collect
    pass starting shortly after an unrelated synchronous burst read that burst as its own
    contention and cut workers for it. It surfaced as two collect-monitor tests that
    failed ONLY when an app-starting suite ran before them — which, under CI's random
    ordering, is a coin flip rather than a curiosity.
    """
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _pin_cpu_count(monkeypatch)
    _inject([400.0] * 50)  # a genuine stall, recorded BEFORE this pass exists

    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    mon = _monitor(g, _HEALTHY, tmp_path, running_for_s=0.0)  # the pass starts NOW
    mon._tick()

    sample = collect_perf.recent_samples(1)[-1]
    assert sample["adjust_reason"] != "loop-lag"
    assert sample["loop"]["measured"] is False
    assert sample["loop_backoff"]["engaged"] is False
    assert g._sem.permits >= 20, "workers were cut for a stall that predates the pass"


def test_the_pass_mark_is_on_the_same_timeline_as_the_lag_stamps(tmp_path, monkeypatch):
    """``CollectionMonitor`` takes an injectable ``now_fn``, and two of its own tests use
    one — so taking the pass mark from it rather than from the real clock would compare a
    fake timeline against ``latency``'s real ``time.monotonic`` stamps. With a fake clock
    starting at 0 every sample ever recorded looks like it came after the pass began, and
    the scoping this file exists to pin is silently gone.

    Written because that mutant survived the matrix: the two clocks agree by default, so
    nothing else could tell them apart.
    """
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _pin_cpu_count(monkeypatch)
    _inject([400.0] * 50)  # real-monotonic stamps, all before the pass

    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    mon = CollectionMonitor(
        governor=g,
        pass_id="p6",
        mode="rss",
        rate_fn=lambda: 200.0,
        vitals_fn=lambda: _HEALTHY,
        writer_stats_fn=lambda: _IDLE_WRITER,
        now_fn=lambda: 0.0,  # a clock that is not time.monotonic
    )
    assert mon._started_mono > 1.0, "the pass mark came from the injected clock"
    mon._tick()
    sample = collect_perf.recent_samples(1)[-1]
    assert sample["loop"]["measured"] is False
    assert sample["adjust_reason"] != "loop-lag"
    assert g._sem.permits >= 20


def test_a_fraction_over_too_few_samples_is_refused_not_rounded():
    """The same refusal at the other end. Scoping to the pass makes the first seconds of
    every window thin, and three readings are not a fraction — so it reports ABSENT with
    a reason rather than a number computed from too little. ``latency``'s own snappy
    verdict already draws that line as "low-n"; this is the same line."""
    _inject([400.0] * 3)
    p = latency.loop_pressure(250.0)
    assert p["measured"] is False
    assert p["samples"] == 3 and p["fraction"] is None
    assert "below the" in p["reason"]
    assert loop_starvation(p) == (False, None)

    _inject([400.0] * latency._LOOP_MIN_SAMPLES)
    ok = latency.loop_pressure(250.0)
    assert ok["measured"] is True and ok["fraction"] == 1.0


def test_since_and_the_window_are_both_applied():
    """Two independent filters, and dropping either one is a different bug: the window
    keeps a reading current, ``since`` keeps it about the right piece of work."""
    now = time.monotonic()
    with latency._LOCK:
        latency._LAG.clear()
        for i in range(30):
            latency._LAG.append((now - 20.0 + i * 0.1, 400.0))   # old: outside the window
        for i in range(30):
            latency._LAG.append((now - 2.0 + i * 0.05, 1.0))     # recent and quiet

    inside = latency.loop_pressure(250.0)
    assert inside["measured"] is True and inside["fraction"] == 0.0, (
        "the stale burst leaked past the 10 s window"
    )
    # `since` = now is later than every sample above, so nothing survives it.
    later = latency.loop_pressure(250.0, since=now)
    assert later["measured"] is False and later["samples"] == 0, (
        "a `since` later than every sample must read as unmeasured, not as quiet"
    )
    # ...and a `since` that reaches back past the stale burst still does not resurrect
    # it, because the 10 s window has already dropped it: the two filters compose.
    reaching_back = latency.loop_pressure(250.0, since=now - 3600.0)
    assert reaching_back["measured"] is True and reaching_back["fraction"] == 0.0


# --------------------------------------------------------------------------- #
#  P4a's lesson as a MECHANISM: stop cutting when cutting is not helping.
# --------------------------------------------------------------------------- #


def test_the_backoff_stands_down_when_its_cuts_do_not_ease_the_lag(tmp_path, monkeypatch):
    """A synchronous call on the event loop blocks it BY ITSELF, and no number of
    collector permits handed back will move that. Descending anyway is exactly the
    failure P4a removed -- so this control checks its own work and gives up, rather than
    carrying a comment that promises it would."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(40)
    mon = _monitor(g, _HEALTHY, tmp_path)

    for _ in range(collect_perf._LOOP_LAG_PATIENCE + 4):
        _inject([400.0] * 50)  # unmoved by every cut
        mon._tick()

    assert mon._loop_lag_abandoned is True
    cuts = mon._loop_lag_ticks
    assert cuts == collect_perf._LOOP_LAG_PATIENCE, (
        f"it kept cutting: {cuts} cuts for a cause the cuts could not reach"
    )
    assert g._sem.permits == 40 - collect_perf._LOOP_LAG_PATIENCE

    summary = mon._write_summary(None)["bottleneck"]
    assert summary["loop_lag_backoff_abandoned"] is True
    assert "did not ease it" in summary["loop_lag_note"]
    assert "other than the collector" in summary["loop_lag_note"]


def test_a_backoff_that_IS_working_keeps_going(tmp_path, monkeypatch):
    """The other half, or the mechanism above would just be a cap on how much this
    control may ever do."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(40)
    mon = _monitor(g, _HEALTHY, tmp_path)

    n = collect_perf._LOOP_LAG_PATIENCE + 4
    for i in range(n):
        over = max(1, 50 - i)  # the lag eases as workers are cut
        _inject([400.0] * over + [1.0] * (50 - over))
        mon._tick()

    assert mon._loop_lag_abandoned is False
    assert mon._loop_lag_ticks == n
    assert g._sem.permits == 40 - n


def test_a_healthy_tick_re_arms_a_stood_down_backoff(tmp_path, monkeypatch):
    """Standing down is per-episode, not for the pass. Latching it permanently would
    mean one blocked-loop episode disarms the control for hours."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(40)
    mon = _monitor(g, _HEALTHY, tmp_path)

    for _ in range(collect_perf._LOOP_LAG_PATIENCE + 2):
        _inject([400.0] * 50)
        mon._tick()
    assert mon._loop_lag_abandoned is True

    _inject([1.0] * 50)  # the loop recovers
    mon._tick()
    assert mon._loop_lag_abandoned is False and mon._loop_lag_streak == 0

    _inject([400.0] * 50)  # ...and a NEW episode is acted on
    before = g._sem.permits
    mon._tick()
    assert g._sem.permits == before - 1


def test_lag_is_reported_even_when_the_control_is_switched_off(tmp_path, monkeypatch):
    """The reading is an OBSERVATION, and keeping it only when the control chose to act
    would lose it in the two cases a reader most needs it: the back-off disabled by
    configuration, and lag that stayed under the bar. Both would then look like a pass
    with no lag at all, which is a different fact."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_LOOP_LAG_BACKOFF_FRACTION", "0")  # off
    _inject([400.0] * 50)
    g = BandwidthGovernor(mode="maximum", w_max=50)
    g._sem.set_permits(20)
    mon = _monitor(g, _HEALTHY, tmp_path)
    for _ in range(3):
        mon._tick()

    assert mon._loop_lag_ticks == 0, "switched off must mean it did not act"
    b = mon._write_summary(None)["bottleneck"]
    assert b["loop_lag_max_fraction"] == 1.0, "...but the pass still SAW a blocked loop"
    assert "blocked for 100% of a sampling window" in b["loop_lag_note"]
    assert "switched off" in b["loop_lag_note"]


def test_a_healthy_pass_carries_no_loop_note(tmp_path, monkeypatch):
    """Negative space, matching the memory-headroom note beside it: a line reporting
    '0 loop-lag ticks' on every healthy pass trains a reader to skip the section where
    the real one will appear."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _inject([1.0] * 50)
    g = BandwidthGovernor(mode="maximum", w_max=50)
    mon = _monitor(g, _HEALTHY, tmp_path)
    for _ in range(3):
        mon._tick()
    b = mon._write_summary(None)["bottleneck"]
    assert b["loop_lag_ticks"] == 0
    assert b["loop_lag_max_fraction"] == 0.0
    assert b["loop_lag_note"] is None, "a zero reading is not news; a non-zero one is"
    assert b["loop_lag_backoff_abandoned"] is False
