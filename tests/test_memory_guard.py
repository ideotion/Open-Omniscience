"""
P0.3 E3 — the RSS memory guard: pause loudly before the OOM-killer fires.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field event 2026-07-09: the app died SILENTLY at RSS 10,599 MB on a ~10,237 MB
VM. The guard turns that into a LOUD, resumable pause. Pinned here:

  * hysteresis both ways — a single spike NEVER false-fires on a healthy box,
    and resume needs sustained healthy readings (no flapping);
  * missing readings carry no information (never a fabricated pressure or a
    fabricated recovery);
  * pause-not-die: an engaged guard winds a pass down (in-flight work finishes,
    the rest defers to the next pass) and the scheduler loop waits — the writer
    gate is NEVER involved (deadlock-free by construction);
  * the state is visible (scheduler status) and user-resumable.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Base, Source
from src.ingest import EthicalFetcher
from src.scheduler import memguard, runner
from src.scheduler.memguard import MemoryGuard
from src.scheduler.runner import run_scrape_once
from src.scheduler.settings import SchedulerSettings

_OVER = {"rss_mb": 9000.0, "mem_avail_mb": 100.0, "mem_total_mb": 10000.0}
_HEALTHY = {"rss_mb": 1000.0, "mem_avail_mb": 6000.0, "mem_total_mb": 10000.0}
_NONE = {"rss_mb": None, "mem_avail_mb": None, "mem_total_mb": None}


def _guard(**kw) -> MemoryGuard:
    kw.setdefault("rss_pct", 85.0)
    kw.setdefault("avail_floor_mb", 256.0)
    kw.setdefault("trip_after", 3)
    kw.setdefault("resume_after", 2)
    return MemoryGuard(**kw)


# --------------------------------------------------------------------------- #
# Trip hysteresis — never a false fire on a healthy box
# --------------------------------------------------------------------------- #


def test_a_single_spike_never_trips():
    g = _guard()
    assert g.observe(**_OVER) is False
    assert g.observe(**_OVER) is False
    assert g.observe(**_HEALTHY) is False  # spike over -> counter resets
    assert g.observe(**_OVER) is False
    assert g.observe(**_OVER) is False
    assert g.engaged is False


def test_sustained_pressure_trips_after_the_configured_samples():
    g = _guard()
    for _ in range(2):
        assert g.observe(**_OVER) is False
    assert g.observe(**_OVER) is True
    assert g.engaged is True
    st = g.state()
    assert st["engaged"] is True and st["since"] and "RSS" in (st["reason"] or "")


def test_rss_fraction_alone_trips_even_with_plenty_available():
    """The field signature: RSS at ~104% of the VM while swap masked 'available'."""
    g = _guard()
    high_rss = {"rss_mb": 9500.0, "mem_avail_mb": 5000.0, "mem_total_mb": 10000.0}
    for _ in range(3):
        g.observe(**high_rss)
    assert g.engaged is True


def test_avail_floor_alone_trips():
    g = _guard()
    low_avail = {"rss_mb": 500.0, "mem_avail_mb": 200.0, "mem_total_mb": 10000.0}
    for _ in range(3):
        g.observe(**low_avail)
    assert g.engaged is True


def test_missing_readings_carry_no_information():
    g = _guard()
    # None samples neither advance nor reset the trip counter.
    g.observe(**_OVER)
    g.observe(**_OVER)
    for _ in range(5):
        assert g.observe(**_NONE) is False
    assert g.observe(**_OVER) is True  # the 3rd INFORMATIVE over-sample trips

    # And an engaged guard is never resumed by a blackout of readings.
    for _ in range(10):
        assert g.observe(**_NONE) is True
    assert g.engaged is True


def test_disabled_by_env_never_trips(monkeypatch):
    monkeypatch.setenv("OO_MEM_GUARD", "0")
    g = _guard()
    for _ in range(10):
        assert g.observe(**_OVER) is False
    assert g.engaged is False


# --------------------------------------------------------------------------- #
# Resume hysteresis + user action
# --------------------------------------------------------------------------- #


def _engaged_guard(**kw) -> MemoryGuard:
    g = _guard(**kw)
    for _ in range(3):
        g.observe(**_OVER)
    assert g.engaged
    return g


def test_resume_needs_sustained_healthy_readings_with_margin():
    g = _engaged_guard()
    # Healthy-but-borderline (above the resume margin) does NOT count: 80% of
    # total is under the 85% trip line but over the 75% resume line.
    borderline = {"rss_mb": 8000.0, "mem_avail_mb": 6000.0, "mem_total_mb": 10000.0}
    assert g.observe(**borderline) is True
    assert g.observe(**_HEALTHY) is True  # 1st healthy sample: not yet
    assert g.observe(**borderline) is True  # streak broken
    assert g.observe(**_HEALTHY) is True
    assert g.observe(**_HEALTHY) is False  # 2nd consecutive healthy: resumed
    assert g.engaged is False


def test_reset_is_the_user_action_and_rearms_the_guard():
    g = _engaged_guard()
    g.reset(reason="user pressed collect")
    assert g.engaged is False
    # Still low after the reset? It re-trips after fresh sustained samples —
    # reset is a retry, never a permanent override.
    for _ in range(3):
        g.observe(**_OVER)
    assert g.engaged is True


def test_poll_reads_fresh_injected_readings():
    readings = {"v": _OVER}
    g = _guard(readings_fn=lambda: readings["v"])
    for _ in range(3):
        g.poll()
    assert g.engaged is True
    readings["v"] = _HEALTHY
    g.poll()
    g.poll()
    assert g.engaged is False


# --------------------------------------------------------------------------- #
# Pause-not-die: the pass winds down, the gate is never involved
# --------------------------------------------------------------------------- #


def _mem_session():
    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


class _EmptyFeedSession:
    def __init__(self):
        self.headers: dict = {}
        self.proxies: dict = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        return _Resp(
            text='<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>',
            ct="application/rss+xml", url=url,
        )


def test_engaged_guard_winds_a_pass_down_and_never_touches_the_gate(monkeypatch):
    fake = _engaged_guard()
    monkeypatch.setattr(memguard, "memory_guard", fake)
    session = _mem_session()
    tag = "mg" + uuid.uuid4().hex[:6]
    for i in range(4):
        session.add(Source(
            name=f"M{i}", domain=f"{tag}-{i}.example",
            rss_url=f"https://{tag}-{i}.example/feed.xml",
            enabled=True, status="qualified", language="en", tags=tag,
        ))
    session.commit()
    runner._consume_deferred()
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0,
                             session=_EmptyFeedSession())
    t0 = time.monotonic()
    res = run_scrape_once(session, fetcher, SchedulerSettings(mode="rss"))
    # Pause-not-die: the pass RETURNED promptly (nothing blocked, no deadlock),
    # processed nothing, deferred everything with the honest reason.
    assert time.monotonic() - t0 < 5.0
    assert res["sources_processed"] == 0
    assert res["recycled"] == "memory"
    assert res["deferred_next_pass"] == 4
    # The writer gate was never left held by the wind-down.
    from src.database.writer import write_gate

    assert write_gate.stats()["held"] is False
    runner._consume_deferred()
    session.close()


def test_scheduler_loop_waits_while_engaged_and_resumes_on_recovery(monkeypatch):
    readings = {"v": _OVER}
    fake = MemoryGuard(rss_pct=85.0, avail_floor_mb=256.0, trip_after=1,
                       resume_after=1, readings_fn=lambda: readings["v"])
    fake.poll()
    assert fake.engaged
    monkeypatch.setattr(memguard, "memory_guard", fake)

    runs = {"n": 0}
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: runs.__setitem__("n", runs["n"] + 1) or {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=True),
    )
    sched._continuous_gap_s = 0.01
    sched._mem_pause_poll_s = 0.02
    assert sched.start()
    try:
        time.sleep(0.25)
        # Paused loudly: no pass ran; the phase names the state; status carries
        # the guard's numbers.
        assert runs["n"] == 0
        assert runner.current_phase() == "paused-low-memory"
        st = sched.status()
        assert st["memory_guard"]["engaged"] is True
        # Memory recovers -> the loop resumes on its own (no restart needed).
        readings["v"] = _HEALTHY
        deadline = time.monotonic() + 5.0
        while runs["n"] == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runs["n"] >= 1
        assert sched.status()["memory_guard"]["engaged"] is False
    finally:
        sched.stop()


def test_active_reclaim_runs_while_paused_and_can_resume(monkeypatch):
    """The "scraping stops after a few hours" fix: while paused low on memory the
    loop ACTIVELY reclaims (gc + malloc_trim + library caches) so a pause caused by
    allocator retention resumes instead of sticking until restart. A genuine leak
    still can't be freed, but freeable memory is handed back and collection resumes."""
    readings = {"v": _OVER}
    fake = MemoryGuard(rss_pct=85.0, avail_floor_mb=256.0, trip_after=1,
                       resume_after=1, readings_fn=lambda: readings["v"])
    fake.poll()
    assert fake.engaged
    monkeypatch.setattr(memguard, "memory_guard", fake)

    reclaims = {"n": 0}

    def _spy_reclaim():
        reclaims["n"] += 1
        # Simulate the reclaim actually returning memory to the OS: after it runs,
        # the readings become healthy, so the NEXT poll releases the guard.
        readings["v"] = _HEALTHY
        return {"freed_mb": 100.0}

    monkeypatch.setattr("src.scheduler.hygiene.release_pass_state", _spy_reclaim)

    runs = {"n": 0}
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: runs.__setitem__("n", runs["n"] + 1) or {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=True),
    )
    sched._continuous_gap_s = 0.01
    sched._mem_pause_poll_s = 0.02
    sched._mem_reclaim_interval_s = 0.0  # reclaim on every poll (test-fast)
    assert sched.start()
    try:
        deadline = time.monotonic() + 5.0
        while runs["n"] == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert reclaims["n"] >= 1  # active reclaim fired during the pause
        assert runs["n"] >= 1  # and collection RESUMED instead of sticking
        assert sched.status()["memory_guard"]["engaged"] is False
    finally:
        sched.stop()


def test_memory_guard_resume_endpoint_is_wired_and_releases(monkeypatch):
    """The user-action resume: the route is composed on the scheduler ROUTER
    (immutable source — never the shared app singleton's .routes) and the
    handler releases the latch."""
    from src.api.scheduler import router

    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/api/scheduler/memory-guard/resume" in paths

    fake = _engaged_guard()
    monkeypatch.setattr(memguard, "memory_guard", fake)
    from src.api.scheduler import memory_guard_resume

    payload = memory_guard_resume()
    assert fake.engaged is False
    assert payload["memory_guard"]["engaged"] is False


def test_stop_interrupts_a_memory_pause_promptly(monkeypatch):
    fake = MemoryGuard(rss_pct=85.0, avail_floor_mb=256.0, trip_after=1,
                       resume_after=1, readings_fn=lambda: _OVER)
    fake.poll()
    monkeypatch.setattr(memguard, "memory_guard", fake)
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=True),
    )
    sched._mem_pause_poll_s = 0.05
    sched.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    assert sched.stop(timeout=5.0) is True
    assert time.monotonic() - t0 < 2.0  # the pause wait is interruptible
