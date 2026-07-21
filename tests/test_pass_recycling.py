"""
P0.3 E2 — pass recycling: one pass is bounded; nothing is ever dropped.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field event 2026-07-09: ONE continuous crawl pass ran 21.6 hours and
accumulated per-pass memory until the kernel OOM-killer fired. Pass recycling
bounds a pass's wall-clock (and optionally its work): when the budget expires
the pass ends CLEANLY — in-flight sources finish, the not-yet-started remainder
is DEFERRED and runs FIRST next pass. Ordering, never exclusion:

  * the negative-space skeptic ("recycling drops a queued source at the pass
    boundary") is pinned here as the exactness invariant — every source is
    either processed or recorded deferred, and the carryover runs first;
  * politeness is untouched (workers are never interrupted mid-fetch);
  * budget 0 = the old unbounded pass, byte-identical.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Base, Source
from src.ingest import EthicalFetcher
from src.scheduler import runner
from src.scheduler.runner import run_scrape_once
from src.scheduler.settings import SchedulerSettings

_EMPTY_RSS = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'
)


class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


class _RecordingFeedSession:
    """Permissive robots + an empty RSS; records the ORDER feed hosts are hit."""

    def __init__(self, delay: float = 0.0):
        self.headers: dict = {}
        self.proxies: dict = {}
        self.feed_hosts: list[str] = []
        self._delay = delay
        self._lock = threading.Lock()

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        host = url.split("://", 1)[1].split("/", 1)[0]
        with self._lock:
            self.feed_hosts.append(host)
        if self._delay:
            import time

            time.sleep(self._delay)
        return _Resp(text=_EMPTY_RSS, ct="application/rss+xml", url=url)


def _mem_session():
    """An ISOLATED in-memory corpus (never the shared SessionLocal — the
    order-dependent-pollution lesson). run_scrape_once runs SEQUENTIALLY on a
    non-global engine, which is exactly what deterministic ordering needs."""
    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def _seed_sources(session, n: int, tag: str) -> list[int]:
    ids = []
    for i in range(n):
        s = Source(
            name=f"R{i}", domain=f"{tag}-{i}.example",
            rss_url=f"https://{tag}-{i}.example/feed.xml",
            enabled=True, status="qualified", language="en", tags=tag,
        )
        session.add(s)
        session.commit()
        ids.append(s.id)
    return ids


@pytest.fixture(autouse=True)
def _clean_carryover():
    """The deferral carryover is module state; isolate every test."""
    runner._consume_deferred()
    yield
    runner._consume_deferred()


# --------------------------------------------------------------------------- #
# The wind-down decider (unit, injected clock)
# --------------------------------------------------------------------------- #


def test_wind_down_budget_is_wall_clock_based():
    t = {"v": 0.0}
    wd = runner._PassWindDown(budget_s=10.0, max_sources=0, now=lambda: t["v"])
    assert wd.admit() is None
    t["v"] = 9.9
    assert wd.admit() is None
    t["v"] = 10.0
    assert wd.admit() == "budget"
    assert wd.admit() == "budget"  # stays wound down


def test_wind_down_work_cap_counts_admitted_sources():
    wd = runner._PassWindDown(budget_s=0.0, max_sources=2, now=lambda: 0.0)
    assert wd.admit() is None
    assert wd.admit() is None
    assert wd.admit() == "work"


def test_wind_down_zero_budget_and_zero_cap_admit_forever():
    wd = runner._PassWindDown(budget_s=0.0, max_sources=0, now=lambda: 1e9)
    for _ in range(100):
        assert wd.admit() is None


# --------------------------------------------------------------------------- #
# End-to-end: budget expiry defers, carryover runs first, nothing dropped
# --------------------------------------------------------------------------- #


def test_expired_budget_defers_the_rest_after_the_progress_floor(monkeypatch):
    """An already-expired budget still admits EXACTLY ONE source (the
    forward-progress floor: a pathological budget — an env typo — must never
    yield zero progress forever) and defers the rest, exactly."""
    monkeypatch.setenv("OO_PASS_BUDGET_MINUTES", "0.0000001")  # already expired
    session = _mem_session()
    tag = "rc" + uuid.uuid4().hex[:6]
    ids = _seed_sources(session, 4, tag)
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0,
                             session=_RecordingFeedSession())
    res = run_scrape_once(session, fetcher, SchedulerSettings(mode="rss"))
    assert res["sources_processed"] == 1  # the floor: never zero forever
    assert res["deferred_next_pass"] == 3
    assert res["recycled"] == "budget"
    assert runner.deferred_carryover_count() == 3
    # The exactness invariant: processed + deferred == every selected source
    # (order is the pass's fair-rotation order, which shuffles by design).
    deferred = runner._consume_deferred()
    assert len(deferred) == 3 and set(deferred) < set(ids)
    session.close()


def test_zero_budget_disables_recycling_entirely(monkeypatch):
    monkeypatch.setenv("OO_PASS_BUDGET_MINUTES", "0")
    session = _mem_session()
    tag = "rz" + uuid.uuid4().hex[:6]
    _seed_sources(session, 3, tag)
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0,
                             session=_RecordingFeedSession())
    res = run_scrape_once(session, fetcher, SchedulerSettings(mode="rss"))
    assert res["sources_processed"] == 3
    assert "recycled" not in res
    assert "deferred_next_pass" not in res
    assert runner.deferred_carryover_count() == 0
    session.close()


def test_work_cap_processes_exactly_n_and_defers_the_rest(monkeypatch):
    monkeypatch.setenv("OO_PASS_MAX_SOURCES", "2")
    session = _mem_session()
    tag = "rw" + uuid.uuid4().hex[:6]
    ids = _seed_sources(session, 5, tag)
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0,
                             session=_RecordingFeedSession())
    res = run_scrape_once(session, fetcher, SchedulerSettings(mode="rss"))
    assert res["sources_processed"] == 2
    assert res["deferred_next_pass"] == 3
    assert res["recycled"] == "work"
    # processed + deferred == every source; the deferred set is disjoint from
    # the processed one (no double-count, no drop).
    deferred = runner._consume_deferred()
    assert len(deferred) == 3 and set(deferred) <= set(ids)
    session.close()


def test_carryover_sources_run_first_next_pass():
    session = _mem_session()
    tag = "rf" + uuid.uuid4().hex[:6]
    ids = _seed_sources(session, 6, tag)
    # Simulate a prior pass boundary having deferred sources 5 and 3 (in that order).
    runner._record_deferred([ids[4], ids[2]])
    sess = _RecordingFeedSession()
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)
    res = run_scrape_once(session, fetcher, SchedulerSettings(mode="rss"))
    assert res["sources_processed"] == 6
    # The deferred pair ran FIRST, in their recorded order (no starvation).
    assert sess.feed_hosts[0] == f"{tag}-4.example"
    assert sess.feed_hosts[1] == f"{tag}-2.example"
    # Fully covered => the carryover is consumed and nothing re-deferred.
    assert runner.deferred_carryover_count() == 0
    session.close()


def test_parallel_pool_exactness_processed_plus_deferred_covers_all(monkeypatch):
    """Under the real worker pool (global engine), the pass boundary loses
    nothing: processed + deferred == every selected source."""
    from src.database.session import init_db, session_scope

    monkeypatch.setenv("OO_PASS_MAX_SOURCES", "3")
    init_db()
    tag = "rp" + uuid.uuid4().hex[:6]
    with session_scope() as s:
        for i in range(7):
            s.add(Source(
                name=f"P{i}", domain=f"{tag}-{i}.example",
                rss_url=f"https://{tag}-{i}.example/feed.xml",
                enabled=True, status="qualified", language="en", tags=tag,
            ))
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0,
                             session=_RecordingFeedSession())
    from src.database.session import SessionLocal

    sel = SessionLocal()
    try:
        res = run_scrape_once(
            sel, fetcher,
            SchedulerSettings(mode="rss", collect_parallelism=4, select_tags=[tag]),
        )
    finally:
        sel.close()
    assert res["sources_processed"] + res["deferred_next_pass"] == 7
    assert res["sources_processed"] == 3
    assert runner.deferred_carryover_count() == 4
    # Leave the shared store clean for later tests (pollution lesson).
    with session_scope() as s:
        for src in s.query(Source).filter(Source.tags == tag):
            src.enabled = False


def test_status_surfaces_the_deferred_carryover():
    runner._record_deferred([11, 22, 33])
    sched = runner.BackgroundScheduler(
        run_once_fn=lambda: {"ok": True},
        settings_provider=lambda: SchedulerSettings(continuous=False),
    )
    st = sched.status()
    assert st["deferred_carryover"] == 3
