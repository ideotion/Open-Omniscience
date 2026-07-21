"""End-to-end guardrails for the parallel collect worker pool (Step 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_parallel_collect.py`` already proves the EthicalFetcher's per-host
lock in ISOLATION and that ``run_scrape_once`` with a pool covers every source.
This file closes the remaining end-to-end assertions for the binding guardrails
(SCRAPING_AUTOMATION_PLAN Step 2): driven THROUGH ``run_scrape_once``'s worker
pool, not the fetcher directly —

  * politeness is never traded for speed: two sources on the SAME host are
    fetched serially even at parallelism > 1, while two on DIFFERENT hosts DO
    overlap (the actual Tor speedup);
  * the network kill switch halts every worker mid-pass — no worker fetches
    after it trips, the pass returns (no deadlock), and one bad/blocked source
    never aborts the batch.

The pool fetches concurrently but every DB write still drains through the one
single-writer gate (src/database/writer.py), which these tests do not disturb.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from src.database.models import Source
from src.ingest import (
    EthicalFetcher,
    activate_kill_switch,
    clear_kill_switch,
)
from src.scheduler.runner import run_scrape_once
from src.scheduler.settings import SchedulerSettings

_RSS = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    "</channel></rss>"
)


class _Resp:
    def __init__(self, text="", ct="application/rss+xml", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


class _OverlapSession:
    """Thread-safe fake transport that records max concurrent in-flight FEED
    fetches overall and per host (robots are permissive and not counted — they
    ride the same per-host lock anyway). Each feed fetch sleeps so genuine
    overlap is observable."""

    def __init__(self, delay=0.1):
        self.headers: dict = {}
        self.proxies: dict = {}
        self._delay = delay
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.host_active: dict[str, int] = {}
        self.host_max: dict[str, int] = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None,
            proxies=None, stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        host = url.split("://", 1)[1].split("/", 1)[0]
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.host_active[host] = self.host_active.get(host, 0) + 1
            self.host_max[host] = max(self.host_max.get(host, 0), self.host_active[host])
        time.sleep(self._delay)
        with self._lock:
            self.active -= 1
            self.host_active[host] -= 1
        return _Resp(text=_RSS, url=url)


def _run(sources_session_factory, fetcher, settings):
    from src.database.session import SessionLocal

    sel = SessionLocal()
    try:
        return run_scrape_once(sel, fetcher, settings)
    finally:
        sel.close()


def _seed(tag, feed_hosts):
    """``feed_hosts``: the network host each source's RSS feed lives on.

    The per-host politeness lock keys on the FEED URL's netloc, not on
    Source.domain (which carries a UNIQUE constraint), so a shared host is
    expressed by reusing the same entry in ``feed_hosts`` while every Source row
    still gets a distinct ``domain``.
    """
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        for i, host in enumerate(feed_hosts):
            s.add(Source(
                name=f"{tag}-{i}", domain=f"{tag}-{i}.src",  # unique per row
                rss_url=f"https://{host}/feed{i}.xml",  # shared host = same netloc
                enabled=True, status="qualified", language="en", tags=tag,
            ))


def test_pool_serialises_same_host_but_overlaps_different_hosts():
    """The politeness guardrail, end-to-end through the collect pool.

    Four sources, two on host A and two on host B, fetched at parallelism 4:
      * neither host ever has two concurrent in-flight requests (politeness);
      * yet the two HOSTS overlap (the real speedup is exercised).
    """
    tag = "g" + uuid.uuid4().hex[:6]
    host_a = f"{tag}-a.example"
    host_b = f"{tag}-b.example"
    _seed(tag, [host_a, host_a, host_b, host_b])

    sess = _OverlapSession(delay=0.1)
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)
    settings = SchedulerSettings(mode="rss", collect_parallelism=4, select_tags=[tag])

    res = _run(None, fetcher, settings)

    assert res["sources_processed"] == 4
    # Per-host politeness: at most ONE in-flight request per host, ever.
    assert sess.host_max.get(host_a, 0) == 1, sess.host_max
    assert sess.host_max.get(host_b, 0) == 1, sess.host_max
    # The speedup: the two DIFFERENT hosts were fetched concurrently.
    assert sess.max_active > 1, sess.max_active


class _CountingSession:
    """Counts feed fetches (not robots) so we can assert the kill switch stops
    further work. Slow enough that a mid-pass trip lands while workers run."""

    def __init__(self, delay=0.05):
        self.headers: dict = {}
        self.proxies: dict = {}
        self._delay = delay
        self._lock = threading.Lock()
        self.feed_fetches = 0

    def get(self, url, timeout=None, allow_redirects=True, headers=None,
            proxies=None, stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        with self._lock:
            self.feed_fetches += 1
        time.sleep(self._delay)
        return _Resp(text=_RSS, url=url)


def test_kill_switch_halts_every_worker_and_pass_returns():
    """A tripped kill switch makes every worker raise (no fetch proceeds past
    it), the pass returns without deadlock, and no source aborts the batch."""
    tag = "k" + uuid.uuid4().hex[:6]
    _seed(tag, [f"{tag}-{i}.example" for i in range(8)])

    sess = _CountingSession(delay=0.05)
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)
    settings = SchedulerSettings(mode="rss", collect_parallelism=4, select_tags=[tag])

    activate_kill_switch()
    try:
        # With the kill switch already tripped, every fetch() raises FetchFailed
        # at the top of the call; _process_source catches it per source, so the
        # pass completes promptly and stores nothing — and crucially RETURNS
        # (no hang/deadlock through the pool + write gate).
        done = threading.Event()
        result: dict = {}

        def go():
            result["res"] = _run(None, fetcher, settings)
            done.set()

        t = threading.Thread(target=go)
        t.start()
        assert done.wait(15), "parallel pass did not return under a tripped kill switch (deadlock?)"
        t.join(5)
    finally:
        clear_kill_switch()

    # No feed was actually fetched — every worker was halted at the gate.
    assert sess.feed_fetches == 0, sess.feed_fetches
    # The pass returned a well-formed tally; nothing stored.
    assert result["res"]["articles_stored"] == 0


def test_kill_switch_tripped_mid_pass_stops_remaining_workers():
    """Trip the kill switch AFTER the pass starts: in-flight fetches finish, but
    the switch stops the rest, so far fewer than all sources are fetched — and
    still no deadlock."""
    tag = "m" + uuid.uuid4().hex[:6]
    n = 12
    _seed(tag, [f"{tag}-{i}.example" for i in range(n)])

    sess = _CountingSession(delay=0.1)
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)
    settings = SchedulerSettings(mode="rss", collect_parallelism=2, select_tags=[tag])

    clear_kill_switch()
    done = threading.Event()
    result: dict = {}

    def go():
        result["res"] = _run(None, fetcher, settings)
        done.set()

    t = threading.Thread(target=go)
    t.start()
    # Let a couple of workers get in flight, then trip the switch.
    time.sleep(0.12)
    activate_kill_switch()
    try:
        assert done.wait(15), "mid-pass kill switch did not let the pass return (deadlock?)"
        t.join(5)
    finally:
        clear_kill_switch()

    # The switch stopped the remaining workers: strictly fewer than all sources
    # were fetched (a couple in-flight may complete; the rest are halted).
    assert sess.feed_fetches < n, sess.feed_fetches


@pytest.fixture(autouse=True)
def _ensure_kill_switch_clear():
    """Never leak a tripped kill switch into another test."""
    clear_kill_switch()
    yield
    clear_kill_switch()
