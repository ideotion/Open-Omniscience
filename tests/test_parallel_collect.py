"""Parallel collection: fetch many hosts at once, politely, write serially.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

SCRAPING_AUTOMATION_PLAN Step 2 (the Tor speedup): a bounded worker pool fetches
DIFFERENT hosts concurrently while the single SQLite writer serialises writes.
The binding guardrail — per-host politeness is NEVER traded for speed — holds via
the EthicalFetcher's per-host lock: one host is fetched by at most one thread at
a time, different hosts in parallel. Default parallelism is 1 (opt-in).
"""

from __future__ import annotations

import threading
import time
import uuid

from src.database.models import Source
from src.ingest import EthicalFetcher
from src.scheduler.runner import run_scrape_once
from src.scheduler.settings import SchedulerSettings, load_settings, save_settings

_EMPTY_RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'


class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


class _ConcurrencySession:
    """Records max concurrent in-flight PAGE fetches, overall and per host; each
    page fetch sleeps so genuine concurrency is observable. Robots are permissive
    and not counted (they ride the same host lock anyway)."""

    def __init__(self, delay=0.05, body="<html>ok</html>", ct="text/html"):
        self.headers: dict = {}
        self.proxies: dict = {}
        self._delay = delay
        self._body = body
        self._ct = ct
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.host_active: dict[str, int] = {}
        self.host_max: dict[str, int] = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
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
        return _Resp(text=self._body, ct=self._ct, url=url)


def _fetch_all(fetcher, urls):
    errs = []

    def go(u):
        try:
            fetcher.fetch(u)
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    threads = [threading.Thread(target=go, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    return errs


def test_same_host_fetches_are_serialised():
    """Politeness guardrail: never two concurrent requests to ONE host."""
    sess = _ConcurrencySession(delay=0.05)
    f = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)
    _fetch_all(f, [f"https://samehost.example/page{i}" for i in range(6)])
    assert sess.host_max.get("samehost.example", 0) == 1


def test_different_hosts_fetch_in_parallel():
    """The speedup: different hosts DO run concurrently."""
    sess = _ConcurrencySession(delay=0.1)
    f = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)
    _fetch_all(f, [f"https://host{i}.example/x" for i in range(5)])
    assert sess.max_active > 1


# --------------------------------------------------------------------------- #
# run_scrape_once with a worker pool
# --------------------------------------------------------------------------- #


class _EmptyFeedSession:
    """Serves a permissive robots + an empty RSS for any feed URL (thread-safe)."""

    def __init__(self):
        self.headers: dict = {}
        self.proxies: dict = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        return _Resp(text=_EMPTY_RSS, ct="application/rss+xml", url=url)


def test_run_scrape_once_parallel_processes_all_sources():
    from src.database.session import SessionLocal, init_db, session_scope

    init_db()
    tag = "par" + uuid.uuid4().hex[:6]
    with session_scope() as s:
        for i in range(6):
            s.add(Source(
                name=f"P{i}", domain=f"{tag}-{i}.example",
                rss_url=f"https://{tag}-{i}.example/feed.xml",
                enabled=True, status="qualified", language="en", tags=tag,
            ))
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_EmptyFeedSession())
    settings = SchedulerSettings(mode="rss", collect_parallelism=4, select_tags=[tag])

    sel = SessionLocal()
    try:
        res = run_scrape_once(sel, fetcher, settings)
    finally:
        sel.close()
    # All six tagged sources were fetched concurrently and counted (empty feeds,
    # so nothing stored — the point is the POOL covered every source).
    assert res["sources_processed"] == 6


def test_collect_parallelism_setting_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # The bandwidth-governed collector: the default rate mode is "maximum"
    # (maintainer ruling 2026-07-23 — the 500 KiB/s target parked workers and
    # left real connections under-used) with a concurrency CEILING of 50
    # (maintainer ruling 2026-06-16, supersedes the old opt-in default of 1).
    # collect_target_kbps keeps its 500 default for anyone who switches back
    # to "target" mode.
    d = load_settings()
    assert d.collect_parallelism == 50  # hard ceiling (the governor's upper bound)
    assert d.collect_rate_mode == "maximum"
    assert d.collect_target_kbps == 500
    save_settings({"collect_parallelism": 4})
    assert load_settings().collect_parallelism == 4


def test_collect_rate_settings_validate_and_clamp(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    import pytest

    from src.scheduler.settings import SchedulerSettingsError

    # Ceiling raised to 50; >50 is rejected on save, clamped on load.
    save_settings({"collect_parallelism": 50})
    assert load_settings().collect_parallelism == 50
    with pytest.raises(SchedulerSettingsError):
        save_settings({"collect_parallelism": 51})

    # Download-rate target + mode round-trip; bad mode is rejected.
    save_settings({"collect_rate_mode": "maximum", "collect_target_kbps": 1000})
    s = load_settings()
    assert s.collect_rate_mode == "maximum"
    assert s.collect_target_kbps == 1000
    with pytest.raises(SchedulerSettingsError):
        save_settings({"collect_rate_mode": "warp-speed"})
