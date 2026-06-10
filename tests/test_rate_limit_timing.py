"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Regression test for finding TEST-04 (0.0.8 WP3): the per-host politeness delay
must actually be slept, for the right duration -- max(min_interval_s, the
robots.txt Crawl-delay) minus the time already elapsed since the last request
to that host. Existing tests set min_interval_s=0 to avoid sleeping, so until
now nothing asserted the delay arithmetic itself.

Uses the fetcher's _sleep/_now indirection (designed for this) -- a fake clock
records requested sleeps and advances time deterministically; no real sleeping.
"""

from __future__ import annotations


from src.ingest import EthicalFetcher


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _Session:
    def __init__(self, robots_text="User-agent: *\nAllow: /"):
        self.headers = {}
        self._robots_text = robots_text

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        if url.endswith("/robots.txt"):
            return _Resp(text=self._robots_text, content_type="text/plain", url=url)
        return _Resp(text="<html><body>ok</body></html>", url=url)


class _FakeClock:
    """Deterministic clock: now() returns the current fake time; sleep(d)
    records d and advances time by it (as a real sleep would)."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.t += duration

    def advance(self, dt: float) -> None:
        self.t += dt


def _fetcher(session, **kw) -> tuple[EthicalFetcher, _FakeClock]:
    f = EthicalFetcher(session=session, **kw)
    clock = _FakeClock()
    f._now = clock.now
    f._sleep = clock.sleep
    return f, clock


def test_second_fetch_sleeps_the_remaining_min_interval():
    f, clock = _fetcher(_Session(), min_interval_s=5.0)
    f.fetch("https://example.com/a")
    assert clock.sleeps == []  # first request to the host: no delay

    clock.advance(2.0)  # 2s pass; 3s of the 5s interval remain
    f.fetch("https://example.com/b")
    assert len(clock.sleeps) == 1
    assert abs(clock.sleeps[0] - 3.0) < 1e-9


def test_no_sleep_when_interval_already_elapsed():
    f, clock = _fetcher(_Session(), min_interval_s=5.0)
    f.fetch("https://example.com/a")
    clock.advance(7.0)  # more than the interval
    f.fetch("https://example.com/b")
    assert clock.sleeps == []


def test_robots_crawl_delay_overrides_a_smaller_min_interval():
    sess = _Session(robots_text="User-agent: *\nAllow: /\nCrawl-delay: 10")
    f, clock = _fetcher(sess, min_interval_s=1.0)
    f.fetch("https://example.com/a")
    clock.advance(2.0)  # 8s of the 10s crawl-delay remain
    f.fetch("https://example.com/b")
    assert len(clock.sleeps) == 1
    assert abs(clock.sleeps[0] - 8.0) < 1e-9


def test_min_interval_wins_over_a_smaller_crawl_delay():
    sess = _Session(robots_text="User-agent: *\nAllow: /\nCrawl-delay: 1")
    f, clock = _fetcher(sess, min_interval_s=6.0)
    f.fetch("https://example.com/a")
    clock.advance(2.0)  # 4s of the 6s min-interval remain
    f.fetch("https://example.com/b")
    assert len(clock.sleeps) == 1
    assert abs(clock.sleeps[0] - 4.0) < 1e-9


def test_delays_are_tracked_per_host():
    f, clock = _fetcher(_Session(), min_interval_s=5.0)
    f.fetch("https://one.example/a")
    f.fetch("https://two.example/a")  # different host: no delay owed
    assert clock.sleeps == []
