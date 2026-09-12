"""
Tests for the collection-performance monitor + bottleneck classifier.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Deterministic: the rate, vitals and writer-gate readings are injected, and we
drive ``_tick`` directly (no real thread / waiting / psutil).
"""

from __future__ import annotations

from src.monitoring import collect_perf
from src.monitoring.collect_perf import CollectionMonitor, recent_samples
from src.scheduler.bandwidth import BandwidthGovernor


def _monitor(*, governor, rate, vitals, writer):
    return CollectionMonitor(
        governor=governor,
        pass_id="test-pass",
        mode="rss",
        rate_fn=lambda: rate,
        vitals_fn=lambda: vitals,
        writer_stats_fn=lambda: writer,
    )


_IDLE_WRITER = {"waiters": 0, "total_wait_s": 0.0, "peak_waiters": 0}
_HEALTHY_VITALS = {"cpu_sys_pct": 20.0, "cpu_proc_pct": 10.0, "mem_avail_mb": 4000.0, "rss_mb": 200.0}


def test_classifier_cpu_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=4)
    vit = {**_HEALTHY_VITALS, "cpu_sys_pct": 99.0}
    mon = _monitor(governor=g, rate=200.0, vitals=vit, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    assert summary["bottleneck"]["verdict"] == "cpu-bound"
    assert summary["bottleneck"]["max_cpu_sys_pct"] == 99.0


def test_classifier_memory_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=4)
    vit = {**_HEALTHY_VITALS, "mem_avail_mb": 100.0}  # below the 512 MB floor
    mon = _monitor(governor=g, rate=200.0, vitals=vit, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    assert summary["bottleneck"]["verdict"] == "memory-bound"
    # S4.3: a real, MEASURED note (never a projected worker count from total
    # RAM) — this pass genuinely hit mem-low back-offs every tick.
    b = summary["bottleneck"]
    assert b["mem_low_ticks"] == 3
    assert b["mem_low_min_permits"] is not None
    assert str(b["mem_low_min_permits"]) in b["memory_headroom_note"]
    assert "capped parallel collection" in b["memory_headroom_note"]


def test_memory_headroom_note_absent_when_ram_was_never_low(tmp_path, monkeypatch):
    """Negative space: a healthy pass must report mem_low_ticks == 0 and no note
    — the honesty non-negotiable that absence of pressure reads as absence, not
    a guessed capacity ceiling."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=4)
    mon = _monitor(governor=g, rate=200.0, vitals=_HEALTHY_VITALS, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    b = summary["bottleneck"]
    assert b["mem_low_ticks"] == 0
    assert b["mem_low_min_permits"] is None
    assert b["memory_headroom_note"] is None


def test_mem_low_min_permits_tracks_the_worst_observed_floor(tmp_path, monkeypatch):
    """The governor cuts permits by 2 on EVERY mem-low tick (down to a floor of
    1) — mem_low_min_permits must track the SMALLEST value actually reached,
    not just the first or the last."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=10, seed=10)
    vit = {**_HEALTHY_VITALS, "mem_avail_mb": 100.0}
    mon = _monitor(governor=g, rate=200.0, vitals=vit, writer=_IDLE_WRITER)
    permits_seen = []
    for _ in range(4):
        mon._tick()
        permits_seen.append(g.permits)
    summary = mon._write_summary(None)
    b = summary["bottleneck"]
    assert b["mem_low_ticks"] == 4
    assert b["mem_low_min_permits"] == min(permits_seen)


def test_guard_pressure_is_tracked_even_while_mem_low_never_fires(tmp_path, monkeypatch):
    """D2: on a machine above ~3.4 GB total RAM, the memory guard's own RSS-relative
    trip point (85% of total, by default) is reached at a LOWER RSS than the
    governor's fixed 512 MB available-memory floor -- so a pass can run entirely
    under real memory pressure while mem_low_ticks stays 0 and
    scheduler.capacity's learner never sees a signal. guard_pressure_ticks is the
    signal it was missing: RSS 850/1000 MB (85%) with available comfortably above
    the 512 MB floor."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.scheduler import memguard

    guard = memguard.MemoryGuard(rss_pct=85.0, avail_floor_mb=256.0, trip_after=3, resume_after=2)
    monkeypatch.setattr(memguard, "memory_guard", guard)

    g = BandwidthGovernor(mode="maximum", w_max=10)
    vit = {
        "cpu_sys_pct": 20.0,
        "cpu_proc_pct": 10.0,
        "mem_avail_mb": 600.0,  # well above the governor's 512 MB mem_low floor
        "mem_total_mb": 1000.0,
        "rss_mb": 850.0,  # 85% of total -- crosses the GUARD's own threshold
    }
    mon = _monitor(governor=g, rate=200.0, vitals=vit, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    b = summary["bottleneck"]
    assert b["mem_low_ticks"] == 0, "the governor's own floor never fires in this scenario"
    assert b["mem_low_min_permits"] is None
    assert b["guard_pressure_ticks"] == 3, "the guard's raw per-sample reading must still see it"
    assert b["guard_pressure_min_permits"] is not None
    assert "memory guard" in b["guard_pressure_note"]
    assert str(b["guard_pressure_ticks"]) in b["guard_pressure_note"]


def test_guard_pressure_note_absent_when_healthy(tmp_path, monkeypatch):
    """Negative space, mirroring memory_headroom_note's own absence test: a
    healthy pass must report guard_pressure_ticks == 0 and no note."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.scheduler import memguard

    guard = memguard.MemoryGuard(rss_pct=85.0, avail_floor_mb=256.0)
    monkeypatch.setattr(memguard, "memory_guard", guard)

    g = BandwidthGovernor(mode="maximum", w_max=4)
    vit = {**_HEALTHY_VITALS, "mem_total_mb": 8000.0}
    mon = _monitor(governor=g, rate=200.0, vitals=vit, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    b = summary["bottleneck"]
    assert b["guard_pressure_ticks"] == 0
    assert b["guard_pressure_min_permits"] is None
    assert b["guard_pressure_note"] is None


def test_classifier_writer_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=12)
    # Several workers queued behind the single writer, and its cumulative wait grows.
    waits = iter([1.0, 2.0, 3.0, 4.0])
    mon = CollectionMonitor(
        governor=g,
        pass_id="w",
        mode="rss",
        rate_fn=lambda: 50.0,
        vitals_fn=lambda: _HEALTHY_VITALS,
        writer_stats_fn=lambda: {"waiters": 5, "total_wait_s": next(waits), "peak_waiters": 5},
    )
    for _ in range(4):
        mon._tick()
    summary = mon._write_summary(None)
    assert summary["bottleneck"]["verdict"] == "writer-bound"
    assert summary["bottleneck"]["writer_total_wait_s_delta"] > 0


def test_classifier_network_or_source_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # Seed == ceiling so peak_permits reaches w_max immediately; rate stays far
    # below target with the machine idle -> the network/source is the limit.
    g = BandwidthGovernor(mode="target", target_kbps=500, w_max=2)
    mon = _monitor(governor=g, rate=50.0, vitals=_HEALTHY_VITALS, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    assert summary["bottleneck"]["verdict"] == "network-or-source-bound"


def test_network_bound_stays_reachable_when_a_learned_ceiling_caps_the_ramp(
    tmp_path, monkeypatch
):
    """"As wide as we were ALLOWED to run" is the ramp ceiling, not w_max.

    A machine with a learned memory ceiling can never reach w_max by construction, so
    comparing peak_permits against w_max makes this verdict unreachable there — and the
    pass then reports "target-met-or-headroom", claiming headroom it does not have on
    the one class of machine that has already proved it has none.
    """
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(
        mode="target", target_kbps=500, w_max=50, seed=2, ramp_ceiling=2
    )
    mon = _monitor(governor=g, rate=50.0, vitals=_HEALTHY_VITALS, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    assert summary["bottleneck"]["verdict"] == "network-or-source-bound"


def test_classifier_target_met(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="target", target_kbps=500, w_max=8)
    mon = _monitor(governor=g, rate=520.0, vitals=_HEALTHY_VITALS, writer=_IDLE_WRITER)
    for _ in range(3):
        mon._tick()
    summary = mon._write_summary(None)
    assert summary["bottleneck"]["verdict"] == "target-met-or-headroom"


def test_no_samples_writes_no_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="target", w_max=4)
    mon = _monitor(governor=g, rate=1.0, vitals=_HEALTHY_VITALS, writer=_IDLE_WRITER)
    # Never ticked -> no JSONL summary (a sub-interval pass must not slow down).
    assert mon._write_summary(None) is None


def _clock(step=1.5):
    """A fake monotonic clock advancing ``step`` seconds per read (deterministic dt)."""
    t = [0.0]

    def now():
        t[0] += step
        return t[0]

    return now


def test_writer_saturation_trips_on_wait_rate_not_just_instantaneous_waiters(tmp_path, monkeypatch):
    """The field bug: instantaneous ``waiters`` reads ~1 at a sample tick even when
    the gate queued 23 deep between ticks, so the governor kept RAMPING. The gate's
    accrued wait RATE must trip saturation and make the governor back off."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=15, seed=8)
    # waiters reads 1 every tick (below max(2, permits//3)) so the OLD check never
    # trips; but total_wait_s grows 3.0 per 1.5 s tick => wait_rate 2.0 >= 1.0.
    waits = iter([3.0, 6.0, 9.0, 12.0, 15.0, 18.0])
    mon = CollectionMonitor(
        governor=g,
        pass_id="wr",
        mode="rss",
        interval_s=1.5,
        rate_fn=lambda: 50.0,  # far below "maximum" ceiling => would ramp if not saturated
        vitals_fn=lambda: _HEALTHY_VITALS,
        writer_stats_fn=lambda: {"waiters": 1, "total_wait_s": next(waits), "contended": 0, "peak_waiters": 23},
        now_fn=_clock(1.5),
    )
    start = g.permits
    reasons = []
    for _ in range(4):
        mon._tick()
        reasons.append(collect_perf.get_latest()["adjust_reason"])
    # Despite low instantaneous waiters, the governor recognised the writer is the
    # limit and reduced the worker count instead of ramping toward the ceiling.
    assert "writer-saturated" in reasons
    assert g.permits < start
    last = collect_perf.get_latest()["writer_gate"]
    assert last["saturated"] is True
    assert last["wait_rate"] is not None and last["wait_rate"] >= 1.0


def test_writer_not_saturated_when_gate_is_quiet(tmp_path, monkeypatch):
    """Control: an idle/low-wait gate must NOT be flagged saturated (no false back-off)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    g = BandwidthGovernor(mode="maximum", w_max=15, seed=4)
    mon = CollectionMonitor(
        governor=g,
        pass_id="wq",
        mode="rss",
        interval_s=1.5,
        rate_fn=lambda: 50.0,
        vitals_fn=lambda: _HEALTHY_VITALS,
        writer_stats_fn=lambda: {"waiters": 0, "total_wait_s": 0.0, "contended": 0, "peak_waiters": 0},
        now_fn=_clock(1.5),
    )
    for _ in range(3):
        mon._tick()
    last = collect_perf.get_latest()["writer_gate"]
    assert last["saturated"] is False
    # With the gate quiet and rate below the maximum ceiling, it ramped (didn't back off).
    assert g.permits >= 4


def test_samples_and_summary_land_in_the_log(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    collect_perf._set_latest(None)
    g = BandwidthGovernor(mode="maximum", w_max=4)
    mon = _monitor(governor=g, rate=300.0, vitals=_HEALTHY_VITALS, writer=_IDLE_WRITER)
    for _ in range(2):
        mon._tick()
    assert collect_perf.get_latest()["download_rate_kbps"] == 300.0
    mon._write_summary({"articles_stored": 7, "sources_processed": 3, "pages_fetched": 9})
    rows = recent_samples(50)
    assert any(r.get("kind") == "summary" for r in rows)
    assert any(r.get("download_rate_kbps") == 300.0 for r in rows)


# --------------------------------------------------------------------------- #
#  P4 (2026-09-10): the CPU back-off asks WHOSE load it is.
# --------------------------------------------------------------------------- #


def test_a_collector_that_saturates_the_cpu_alone_is_not_contention():
    """The defect this fixes, stated as the case that used to be wrong.

    The collector is CPU-bound in pure Python, so a healthy pass on a small box drives
    system CPU to ~100% BY ITSELF. Under the old ``cpu_sys >= 92`` rule the governor
    read that as contention and cut a permit every 1.5 s tick — measured, 50 permits to
    1 in 73 seconds — which reduces throughput and frees nothing, because the CPU it
    gave back was the collector's own.

    ``psutil.cpu_percent()`` is normalised 0-100 across the machine while
    ``Process.cpu_percent()`` SUMS across cores, so 380% of 4 cores is 95% of the box.
    """
    contended, others = collect_perf.cpu_contention(98.0, 380.0, 4)
    assert contended is False
    assert others == 3.0


def test_another_process_saturating_the_cpu_still_backs_off():
    """The mirror, and the reason this is a narrowing rather than a removal.

    This app runs on the operator's own machine beside their browser, their editor and
    a local model. When one of those needs the CPU the collector should still yield —
    that is the case the back-off exists for, and it is untouched.
    """
    contended, others = collect_perf.cpu_contention(98.0, 40.0, 4)
    assert contended is True
    assert others == 88.0


def test_a_machine_that_is_not_saturated_is_never_contention():
    assert collect_perf.cpu_contention(12.0, 20.0, 4) == (False, None)
    assert collect_perf.cpu_contention(91.9, 0.0, 4) == (False, None)


def test_an_unattributable_saturated_machine_keeps_the_old_rule():
    """Without a process reading we cannot say whose load it is, and the safe direction
    for a POLITENESS control is to keep yielding. ``others_pct`` is None rather than 0:
    "we could not attribute this" and "there was no other load" are opposite facts and
    the perf log must not blur them."""
    assert collect_perf.cpu_contention(98.0, None, 4) == (True, None)
    assert collect_perf.cpu_contention(98.0, 380.0, 0) == (True, None)


def test_an_unreadable_system_cpu_never_fabricates_contention():
    assert collect_perf.cpu_contention(None, 380.0, 4) == (False, None)


def test_the_tick_decides_on_the_attribution_not_on_the_system_total(tmp_path, monkeypatch):
    """The wiring, DRIVEN rather than read off the source: a tick whose vitals say the
    machine is full and that WE are the load must not hand the governor a cpu-saturated
    back-off, and must record the attribution it used."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(collect_perf, "_cpu_count", lambda: 4)
    g = BandwidthGovernor(mode="maximum", w_max=50, min_adjust_interval_s=0.0)
    ours = {**_HEALTHY_VITALS, "cpu_sys_pct": 99.0, "cpu_proc_pct": 390.0}
    mon = _monitor(governor=g, rate=200.0, vitals=ours, writer=_IDLE_WRITER)
    mon._tick()
    sample = recent_samples(limit=1)[-1]
    assert sample["adjust_reason"] != "cpu-saturated"
    assert sample["cpu_others_pct"] == 1.5  # 99 - 390/4, stated rather than implied
    assert g.permits == 50, "the governor cut a permit for the collector's own CPU"

    # The mirror on the same wiring: the same saturated machine, someone else's load.
    theirs = {**_HEALTHY_VITALS, "cpu_sys_pct": 99.0, "cpu_proc_pct": 40.0}
    g2 = BandwidthGovernor(mode="maximum", w_max=50, min_adjust_interval_s=0.0)
    mon2 = _monitor(governor=g2, rate=200.0, vitals=theirs, writer=_IDLE_WRITER)
    mon2._tick()
    assert recent_samples(limit=1)[-1]["adjust_reason"] == "cpu-saturated"
    assert g2.permits == 49
