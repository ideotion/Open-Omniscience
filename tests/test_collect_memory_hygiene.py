"""
P0.3 E1 — per-pass memory accumulation: instrumented, bounded, released.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field event 2026-07-09: the app died by kernel OOM at RSS 10,599 MB on a
~10,237 MB VM, 21.6 hours into ONE continuous crawl pass. These tests pin the
E1 counter-measures:

  * the fetcher's per-pass host caches are BOUNDED (robots cache evicts beyond
    a cap — an evicted host simply gets its fail-closed decision recomputed);
  * eviction NEVER trades politeness for memory (a last-request timestamp is
    only forgotten when far older than any plausible crawl-delay; host locks
    are never evicted at all);
  * memory is INSTRUMENTED per perf sample (component gauges + the RSS curve
    in the pass summary), so accumulation is a measured number, not a guess;
  * the between-pass hygiene step releases per-pass state, measured and
    fail-safe.
"""

from __future__ import annotations

import threading

from src.ingest import EthicalFetcher
from src.monitoring.collect_perf import CollectionMonitor
from src.scheduler.bandwidth import BandwidthGovernor
from src.scheduler.hygiene import release_pass_state, run_pass_hygiene


class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


class _CountingSession:
    """Permissive robots + a small HTML page; counts robots fetches per host."""

    def __init__(self):
        self.headers: dict = {}
        self.proxies: dict = {}
        self.robots_fetches: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        host = url.split("://", 1)[1].split("/", 1)[0]
        if url.endswith("/robots.txt"):
            with self._lock:
                self.robots_fetches[host] = self.robots_fetches.get(host, 0) + 1
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        return _Resp(text="<html>ok</html>", url=url)


def _fetcher():
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_CountingSession())


# --------------------------------------------------------------------------- #
# Fetcher host-cache bounds
# --------------------------------------------------------------------------- #


def test_robots_cache_is_bounded_and_evicted_hosts_are_recomputed(monkeypatch):
    monkeypatch.setattr("src.ingest._ROBOTS_CACHE_MAX", 8)
    f = _fetcher()
    for i in range(20):
        f.fetch(f"https://cachehost{i}.example/page")
    # The check runs at fetch START, so the map holds at most cap + the one
    # entry the in-flight fetch just added.
    assert len(f._robots) <= 9
    # An evicted host is simply re-fetched (fail-closed recomputed, never assumed):
    # host 0 was evicted (oldest expiry); fetching it again re-reads robots.txt.
    f.fetch("https://cachehost0.example/other")
    assert f.session.robots_fetches["cachehost0.example"] == 2


def test_last_request_eviction_never_forgets_a_recent_host(monkeypatch):
    """Politeness outranks the bound: only entries older than the safe age
    (>> any plausible robots Crawl-delay) may be forgotten."""
    monkeypatch.setattr("src.ingest._LAST_REQUEST_MAX", 4)
    f = _fetcher()
    now = f._now()
    # 6 hosts: three fetched long ago (evictable), three just now (protected).
    f._last_request = {
        "old-a.example": now - 7 * 3600,
        "old-b.example": now - 8 * 3600,
        "old-c.example": now - 9 * 3600,
        "new-a.example": now - 1.0,
        "new-b.example": now - 2.0,
        "new-c.example": now - 3.0,
    }
    f._bound_host_caches()
    assert set(f._last_request) >= {"new-a.example", "new-b.example", "new-c.example"}
    assert len(f._last_request) == 4  # the two oldest stale entries evicted

    # All-recent over-cap: NOTHING is evicted — the map stays over the cap
    # rather than risk an impolitely early re-fetch (the honest trade).
    f._last_request = {f"busy{i}.example": now - float(i) for i in range(8)}
    f._bound_host_caches()
    assert len(f._last_request) == 8


def test_host_locks_are_never_evicted(monkeypatch):
    """Evicting a lock another thread may hold a reference to would let two
    threads fetch one host concurrently — so locks are exempt by design."""
    f = _fetcher()
    for i in range(30):
        f.fetch(f"https://lockhost{i}.example/x")
    assert len(f._host_locks) == 30  # unbounded by design (per-pass lifetime)


def test_cache_stats_reports_real_lengths():
    f = _fetcher()
    for i in range(3):
        f.fetch(f"https://stats{i}.example/x")
    stats = f.cache_stats()
    assert stats["robots"] == 3
    assert stats["last_request"] == 3
    assert stats["host_locks"] == 3


# --------------------------------------------------------------------------- #
# Perf-sample instrumentation
# --------------------------------------------------------------------------- #

_HEALTHY_VITALS = {
    "cpu_sys_pct": 20.0,
    "cpu_proc_pct": 10.0,
    "mem_avail_mb": 4000.0,
    "mem_total_mb": 8000.0,
    "rss_mb": 200.0,
}
_IDLE_WRITER = {"waiters": 0, "total_wait_s": 0.0, "peak_waiters": 0}


def test_samples_carry_component_gauges_and_summary_carries_rss_curve(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    rss = iter([100.0, 150.0, 140.0])
    mon = CollectionMonitor(
        governor=BandwidthGovernor(mode="maximum", w_max=2),
        pass_id="mem-test",
        mode="rss",
        rate_fn=lambda: 10.0,
        vitals_fn=lambda: {**_HEALTHY_VITALS, "rss_mb": next(rss)},
        writer_stats_fn=lambda: _IDLE_WRITER,
        cache_stats_fn=lambda: {"robots": 7, "last_request": 7, "host_locks": 7},
    )
    for _ in range(3):
        mon._tick()
    from src.monitoring.collect_perf import get_latest

    sample = get_latest()
    assert sample["mem"]["fetcher"] == {"robots": 7, "last_request": 7, "host_locks": 7}
    assert isinstance(sample["mem"]["py_alloc_blocks"], int)
    assert sample["mem_total_mb"] == 8000.0

    summary = mon._write_summary(None)
    assert summary["rss_mb"] == {"first": 100.0, "last": 140.0, "max": 150.0}


def test_gauge_failure_never_breaks_a_tick(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def _boom():
        raise RuntimeError("gauge broke")

    mon = CollectionMonitor(
        governor=BandwidthGovernor(mode="maximum", w_max=2),
        pass_id="mem-test-2",
        mode="rss",
        rate_fn=lambda: 10.0,
        vitals_fn=lambda: _HEALTHY_VITALS,
        writer_stats_fn=lambda: _IDLE_WRITER,
        cache_stats_fn=_boom,
    )
    mon._tick()  # must not raise
    from src.monitoring.collect_perf import get_latest

    assert get_latest()["mem"]["fetcher"] is None


# --------------------------------------------------------------------------- #
# Between-pass hygiene
# --------------------------------------------------------------------------- #


def test_release_pass_state_returns_measured_record():
    rec = release_pass_state()
    assert rec is not None
    # Measured fields present; caches_reset True (trafilatura installed here).
    assert rec["caches_reset"] is True
    assert rec["duration_ms"] >= 0
    assert isinstance(rec["gc_collected"], int)
    # RSS readings are real numbers when psutil is present, else honest None.
    assert rec["rss_mb_before"] is None or rec["rss_mb_before"] > 0


def test_hygiene_is_env_disableable_and_fail_safe(monkeypatch):
    monkeypatch.setenv("OO_PASS_HYGIENE", "0")
    assert release_pass_state() is None
    monkeypatch.delenv("OO_PASS_HYGIENE")

    # run_pass_hygiene never raises, even if the release step blows up.
    monkeypatch.setattr("src.scheduler.hygiene.release_pass_state", _raise)
    assert run_pass_hygiene() is None


def _raise():
    raise RuntimeError("hygiene broke")


def test_run_boundary_records_hygiene_on_the_run_report(tmp_path, monkeypatch):
    """The scheduler's run boundary runs hygiene and attaches the measured
    record to the run report (auditable, never guessed)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.scheduler.runner import BackgroundScheduler
    from src.scheduler.settings import SchedulerSettings

    reports: list[dict] = []
    monkeypatch.setattr("src.scheduler.runlog.record_run", reports.append)
    sched = BackgroundScheduler(
        run_once_fn=lambda: {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=False),
    )
    sched._do_run()
    assert reports and reports[0]["hygiene"]["caches_reset"] is True
