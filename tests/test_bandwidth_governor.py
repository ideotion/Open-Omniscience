"""
Tests for the bandwidth governor: the rate-target -> worker-count controller.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure, deterministic (time is injected via ``now=``), no real waiting.
"""

from __future__ import annotations

import threading

from src.scheduler.bandwidth import DEFAULT_SEED, BandwidthGovernor, _AdjustableSemaphore


def test_seed_is_capped_by_w_max_in_target_mode():
    assert BandwidthGovernor(mode="target", w_max=50).permits == min(DEFAULT_SEED, 50)
    assert BandwidthGovernor(mode="target", w_max=4).permits == 4  # seed never exceeds ceiling


def test_maximum_mode_seeds_at_ceiling_and_ramps_to_it():
    g = BandwidthGovernor(mode="maximum", w_max=8)
    assert g.permits == 8  # starts at the ceiling
    # Even with a rate of 0, maximum mode holds at the ceiling (never above).
    assert g.observe(0.0, now=100.0) == (8, "at-ceiling")


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
    g = BandwidthGovernor(mode="maximum", target_kbps=500, w_max=20, min_adjust_interval_s=999.0)
    base = g.permits
    # Writer saturation reduces by 1 even though the damping interval has not passed.
    assert g.observe(0.0, writer_saturated=True, now=1.0) == (base - 1, "writer-saturated")
    # Memory pressure reduces by 2 and wins over everything.
    assert g.observe(0.0, mem_low=True, writer_saturated=True, now=1.1) == (base - 3, "mem-low")


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
