"""
Tests for the bandwidth governor: the rate-target -> worker-count controller.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure, deterministic (time is injected via ``now=``), no real waiting.
"""

from __future__ import annotations

import threading

from src.scheduler.bandwidth import DEFAULT_SEED, MAXIMUM_START, BandwidthGovernor, _AdjustableSemaphore


def test_seed_is_capped_by_w_max_in_target_mode():
    assert BandwidthGovernor(mode="target", w_max=50).permits == min(DEFAULT_SEED, 50)
    assert BandwidthGovernor(mode="target", w_max=4).permits == 4  # seed never exceeds ceiling


def test_maximum_mode_starts_low_and_an_explicit_seed_still_wins():
    assert BandwidthGovernor(mode="maximum", w_max=50).permits == MAXIMUM_START  # a place to climb from, not the ceiling
    assert BandwidthGovernor(mode="maximum", w_max=3).permits == 3  # never above the ceiling
    assert BandwidthGovernor(mode="maximum", w_max=50, seed=2).permits == 2  # a learned seed (scheduler.capacity) wins
    assert BandwidthGovernor(mode="maximum", w_max=50, seed=40).permits == 40


WINDOW_S = 240.0


def _windows(g, rates, *, start=0.0, window_s=WINDOW_S, ticks=10, sources=100, a0=0, s0=0, **flags):
    """Feed ``g`` one window per entry of ``rates`` (articles stored per MINUTE; ``ticks`` observations each, the last one closing
    the window), with the pass's running article and source-completion counts; returns the (permits, reason) each window ended
    with. ``sources`` completions per window."""
    out = []
    t, a, s = start, a0, s0
    for rate in rates:
        stored = rate * window_s / 60.0
        for k in range(ticks):
            f = k / (ticks - 1)
            r = g.observe(
                0.0, now=t + f * window_s, articles_total=int(a + stored * f), sources_total=int(s + sources * f), **flags
            )
        out.append(r)
        t, a, s = t + window_s + 0.01, int(a + stored), s + sources
    return out


def test_maximum_mode_climbs_one_permit_per_window_while_the_rate_rises_and_holds_when_it_stops():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    got = _windows(g, [100.0, 130.0, 170.0, 171.0, 172.0])
    assert got[0] == (start + 1, "hill-up")  # the first window has nothing to compare with
    assert got[1] == (start + 2, "hill-up") and got[2] == (start + 3, "hill-up")
    assert got[3] == (start + 3, "hold") and got[4] == (start + 3, "hold")  # inside the margin: the rate has stopped rising


def test_maximum_mode_never_climbs_on_a_window_that_stored_nothing_and_takes_no_baseline_from_it():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    got = _windows(g, [0.0, 0.0])
    assert got == [(start, "no-articles"), (start, "no-articles")]
    # the first window that stored something has nothing to compare with, as at the start
    assert _windows(g, [50.0], start=1000.0)[0] == (start + 1, "hill-up")


def test_a_window_that_stored_nothing_leaves_the_last_real_rate_as_the_baseline():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    got = _windows(g, [100.0, 0.0, 105.0])
    assert got[0] == (start + 1, "hill-up") and got[1] == (start + 1, "no-articles")
    # 105 against the 100 before the empty window is inside the margin: a hold. Against a baseline of 0 it would be a climb.
    assert got[2] == (start + 1, "hold")


def test_a_rate_in_one_unit_is_never_compared_with_a_rate_in_another():
    """A window read from the article count and the next from the collector's bytes (the count went away) do not compare: the
    second has no baseline, as at the start."""
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    assert _windows(g, [100.0])[0] == (start + 1, "hill-up")
    t = 1000.0
    for k in range(10):
        r = g.observe(0.0, window_rate=1.0, now=t + k * WINDOW_S / 9)  # no article count: 1 kbit/s, a fall of 99 % by value
    assert r == (start + 2, "hill-up") and g.last_window["prev_rate"] is None


def test_maximum_mode_steps_back_once_after_a_climb_that_did_not_pay_and_then_holds():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    got = _windows(g, [100.0, 130.0, 100.0, 70.0])
    assert got[1] == (start + 2, "hill-up")
    assert got[2] == (start + 1, "hill-back")  # fell by more than the margin right after a climb
    assert got[3] == (start + 1, "hold")  # once: a second fall with no climb behind it does not walk to the floor


def test_maximum_mode_stops_at_the_ceiling_and_names_which_one():
    g = BandwidthGovernor(mode="maximum", w_max=5)
    got = _windows(g, [10.0, 20.0, 40.0, 80.0])
    assert got[-1] == (5, "at-ceiling")
    learned = BandwidthGovernor(mode="maximum", w_max=50, seed=3, ramp_ceiling=3)
    assert _windows(learned, [10.0, 20.0])[-1] == (3, "at-learned-ceiling")


def test_a_window_is_read_only_once_it_holds_enough_source_completions_and_says_thin_until_then():
    """A stored count moves in lumps, so a window of few completions cannot be read (the number is MAXIMUM_WINDOW_SOURCES). The
    window is not thrown away: the completions keep accumulating into it, and it is read the tick it has enough."""
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    assert g.observe(0.0, now=0.0, articles_total=0, sources_total=0) == (start, "settling")
    assert g.observe(0.0, now=300.0, articles_total=300, sources_total=40) == (start, "thin")  # long enough, 40 of 100
    assert g.observe(0.0, now=600.0, articles_total=600, sources_total=99) == (start, "thin")
    assert g.observe(0.0, now=660.0, articles_total=700, sources_total=100) == (start + 1, "hill-up")
    lw = g.last_window
    # the whole accumulated window is what was read: 700 articles over 660 s, 100 completions
    assert lw["articles"] == 700 and lw["sources"] == 100 and lw["elapsed_s"] == 660.0 and lw["rate"] == round(700 * 60 / 660, 1)


def test_the_climb_reads_stored_articles_not_the_collectors_bytes_rate():
    """R180: more bytes per second is not more articles. The collector's kbps rides along in the window record only."""
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    # bytes triple window over window while the stored count does not move: no climb after the first window
    t, a, s = 0.0, 0, 0
    reasons = []
    for kbps in (1000.0, 3000.0, 9000.0):
        for k in range(10):
            f = k / 9
            r = g.observe(0.0, window_rate=kbps, now=t + f * WINDOW_S, articles_total=int(a + 400 * f), sources_total=int(s + 100 * f))
        reasons.append(r)
        t, a, s = t + WINDOW_S + 0.01, a + 400, s + 100
    assert reasons == [(start + 1, "hill-up"), (start + 1, "hold"), (start + 1, "hold")]
    assert g.last_window["collector_kbps"] == 9000.0 and g.last_window["signal"] == "articles/min"


def test_without_an_article_count_the_signal_falls_back_to_the_collectors_rate_and_says_so():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    t = 0.0
    for k in range(10):
        r = g.observe(10_000.0, window_rate=5.0, now=t + k * WINDOW_S / 9)  # the process is busy elsewhere; the collector's rate is 5
    assert r == (start + 1, "hill-up")
    assert g.last_window["signal"] == "collector kbps" and g.last_window["rate"] == 5.0 and g.last_window["articles"] is None


def test_a_saturated_tick_is_not_a_cut_in_maximum_mode_but_a_mostly_saturated_window_takes_one():
    """Lab cell G1: a cut on every tick against a climb once per window held the count at one permit (45 art/min against 58).
    Writer saturation is counted per tick and decided once per window, and the cut takes the place of that window's climb."""
    g = BandwidthGovernor(mode="maximum", w_max=50)
    start = g.permits
    for k in range(5):
        assert g.observe(100.0, writer_saturated=True, now=float(k)) == (start, "settling")  # no per-tick cut
    assert g.observe(100.0, writer_saturated=True, now=WINDOW_S) == (start - 1, "writer-saturated")  # the tick that closes the window
    # a window with saturation on fewer than half of its ticks climbs as usual
    g2 = BandwidthGovernor(mode="maximum", w_max=50)
    s2 = g2.permits
    for k in range(10):
        r = g2.observe(0.0, writer_saturated=(k < 4), now=k * WINDOW_S / 9, articles_total=k * 40, sources_total=k * 12)
    assert r == (s2 + 1, "hill-up")
    # CPU saturation is folded the same way and named as itself
    g3 = BandwidthGovernor(mode="maximum", w_max=50)
    assert _windows(g3, [100.0], cpu_saturated=True)[0] == (g3.permits, "cpu-saturated")


def test_maximum_mode_never_cuts_below_one_on_saturation():
    g = BandwidthGovernor(mode="maximum", w_max=50, seed=1)
    assert _windows(g, [100.0, 100.0], writer_saturated=True)[-1][0] == 1


def test_memory_and_loop_lag_stay_immediate_in_maximum_mode_and_restart_the_window():
    g = BandwidthGovernor(mode="maximum", w_max=50, seed=20, min_adjust_interval_s=999.0)
    assert g.observe(100.0, mem_low=True, now=1.0) == (10, "mem-low")  # halved at once
    assert g.observe(100.0, loop_lagging=True, now=1.1) == (9, "loop-lag")  # one at once, inside any interval
    assert g.observe(100.0, loop_lagging=True, writer_saturated=True, now=1.2) == (8, "loop-lag")
    # the window the cut interrupted is thrown away: nothing is compared across the change
    assert g.last_window is None and g.observe(100.0, now=2.0) == (8, "settling")


def test_the_window_decision_is_published_for_the_perf_log():
    g = BandwidthGovernor(mode="maximum", w_max=50)
    _windows(g, [100.0, 130.0], writer_saturated=False)
    lw = g.stats()["last_window"]
    assert lw["decision"] == "hill-up" and lw["rate"] == 130.0 and lw["prev_rate"] == 100.0 and lw["ticks"] == 10
    assert lw["signal"] == "articles/min" and lw["articles"] == 520 and lw["sources"] == 100 and lw["elapsed_s"] == 240.0
    assert lw["writer_saturated_share"] == 0.0 and lw["cpu_saturated_share"] == 0.0


def test_target_mode_increases_below_and_decreases_above_with_damping():
    g = BandwidthGovernor(mode="target", target_kbps=500, w_max=50, min_adjust_interval_s=3.0)
    start = g.permits
    # Below 90% of target -> additive increase (+1).
    assert g.observe(100.0, now=10.0) == (start + 1, "below-target")
    # Within the damping interval -> no change, "settling".
    assert g.observe(100.0, now=11.0) == (start + 1, "settling")
    # After the interval, still below -> increase again.
    assert g.observe(100.0, now=14.0) == (start + 2, "below-target")
    # Above 110% of target -> decrease.
    assert g.observe(900.0, now=18.0) == (start + 1, "above-target")
    # In band [0.9, 1.1] -> hold.
    assert g.observe(500.0, now=22.0) == (start + 1, "in-band")


def test_contention_backs_off_immediately_regardless_of_interval():
    g = BandwidthGovernor(mode="target", target_kbps=500, w_max=20, seed=20, min_adjust_interval_s=999.0)
    base = g.permits
    # Writer saturation reduces by 1 even though the damping interval has not passed (target mode; maximum mode decides it per
    # window, see the maximum-mode tests).
    assert g.observe(0.0, writer_saturated=True, now=1.0) == (base - 1, "writer-saturated")
    # Memory pressure wins over everything AND cuts multiplicatively, not by a step:
    # overshooting memory costs the machine (thrash, then a possible OOM kill), where
    # overshooting the writer only costs throughput. 19 -> 9, still inside the interval.
    assert g.observe(0.0, mem_low=True, writer_saturated=True, now=1.1) == (
        (base - 1) // 2,
        "mem-low",
    )


def test_permits_never_below_one_or_above_w_max():
    g = BandwidthGovernor(mode="target", target_kbps=1, w_max=3)
    # Drive it down hard with sustained over-target + contention.
    for i in range(20):
        g.observe(10_000.0, mem_low=True, now=float(i))
    assert g.permits == 1
    g2 = BandwidthGovernor(mode="maximum", w_max=3)
    for i in range(20):
        g2.observe(0.0, now=float(i) * 5.0)
    assert g2.permits == 3


def test_adjustable_semaphore_blocks_beyond_permits_and_wakes_on_raise():
    sem = _AdjustableSemaphore(1)
    sem.acquire()  # active=1, permits=1
    assert sem.active == 1
    got = threading.Event()

    def _second():
        sem.acquire()  # should block until permits rise or a release
        got.set()

    t = threading.Thread(target=_second, daemon=True)
    t.start()
    assert not got.wait(0.3)  # still blocked (permits=1, active=1)
    sem.set_permits(2)  # raise the ceiling -> the waiter proceeds
    assert got.wait(2.0)
    assert sem.active == 2
    sem.release()
    sem.release()
    assert sem.active == 0


def test_adjustable_semaphore_clamps_permits_to_at_least_one():
    sem = _AdjustableSemaphore(5)
    sem.set_permits(0)
    assert sem.permits == 1  # never zero -> a pass can never deadlock to a halt


def test_an_immediate_cut_throws_the_open_window_and_the_last_rate_away():
    """The window that a cut interrupts spans two permit counts, so its mean means nothing and the rate before the cut is not a
    baseline for the rate after it."""
    g = BandwidthGovernor(mode="maximum", w_max=50, seed=10)
    g.observe(100.0, now=0.0, articles_total=0, sources_total=0)  # opens a window at t=0
    assert g.observe(100.0, loop_lagging=True, now=10.0, articles_total=10, sources_total=3) == (9, "loop-lag")
    # t=250 is past the window that opened at 0; the new window opened at the cut's next tick has not run its length yet
    assert g.observe(100.0, now=250.0, articles_total=300, sources_total=120) == (9, "settling")
    # and its first decision has nothing to compare with (the old baseline is gone): it climbs on any rate that stored something
    assert g.observe(1.0, now=490.0, articles_total=340, sources_total=220) == (10, "hill-up")


def test_the_rate_before_an_immediate_cut_is_not_the_baseline_after_it():
    g = BandwidthGovernor(mode="maximum", w_max=50, seed=10)
    assert _windows(g, [100.0])[0] == (11, "hill-up")  # a climb, and 100 is now the last window's rate
    assert g.observe(100.0, mem_low=True, now=250.0) == (5, "mem-low")
    # a window far below the pre-cut rate is NOT 'the climb did not pay' (that would step back below the cut's own result)
    got = _windows(g, [1.0], start=251.0, a0=400, s0=100)
    assert got[0] == (6, "hill-up")
