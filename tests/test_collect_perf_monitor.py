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
