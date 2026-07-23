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
