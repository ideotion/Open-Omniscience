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

import pytest
import requests

from src.ingest import EthicalFetcher, FetchFailed


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


# --------------------------------------------------------------------------- #
# 2026-08-20 additions (quality-ratchet session): the two properties the file
# did not yet pin — the SHIPPED default is polite, and the politeness stamp
# survives a transport failure.
# --------------------------------------------------------------------------- #


def test_shipped_default_politeness_is_on(monkeypatch):
    """Politeness must be ON by default — a zeroed default ships an impolite
    fetcher to every install, which no timing test above can see (they all set
    min_interval_s explicitly). >= 1.0 pins the courtesy floor, not an exact
    calibration; raise it deliberately, never drop it below 1s."""
    monkeypatch.delenv("OO_FETCH_MIN_INTERVAL", raising=False)
    assert EthicalFetcher(session=_Session()).min_interval_s >= 1.0

    from src.safety.fetcher import make_fetcher

    assert make_fetcher(session=_Session()).min_interval_s >= 1.0


class _FailFirstPageSession(_Session):
    """Serves robots.txt normally; the FIRST page fetch raises a transport
    error, later ones succeed."""

    def __init__(self):
        super().__init__()
        self._failed = False

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        if not url.endswith("/robots.txt") and not self._failed:
            self._failed = True
            raise requests.ConnectionError("simulated transport failure")
        return super().get(url, timeout=timeout, allow_redirects=allow_redirects, **kwargs)


def test_politeness_stamp_lands_even_when_transport_fails():
    """The per-host timestamp is written in a ``finally`` around the HTTP call,
    so a host that just refused us is still owed the full courtesy interval —
    an error must never become a licence to hammer. Deleting that ``finally``
    stamp makes the second fetch sleep nothing and reddens this test."""
    f, clock = _fetcher(_FailFirstPageSession(), min_interval_s=5.0, max_retries=0)

    with pytest.raises(FetchFailed):
        f.fetch("https://example.com/a")
    assert clock.sleeps == []  # first contact: no delay owed, even on failure

    clock.advance(1.0)  # 1s passes; 4s of the 5s interval remain
    f.fetch("https://example.com/b")
    assert len(clock.sleeps) == 1
    assert abs(clock.sleeps[0] - 4.0) < 1e-9


# --------------------------------------------------------------------------- 2026-09-10
# The candidate kit's first live run: a host declaring Crawl-delay 900 cost six probes ninety
# minutes of one worker, because the delay is honoured before EVERY request. A caller planning
# its next requests can now read the declared delay -- from the cache only, never a fetch.

def test_crawl_delay_for_reads_the_cached_declaration_under_either_key_and_never_fetches():
    session = _Session(robots_text="User-agent: *\nCrawl-delay: 900\nAllow: /")
    f, clock = _fetcher(session, min_interval_s=0, respect_robots=True)
    assert f.crawl_delay_for("https://slow.example/") is None  # not cached yet: unknown, not guessed
    f.fetch("https://slow.example/")
    assert f.crawl_delay_for("https://slow.example/") == 900.0
    assert f.crawl_delay_for("https://slow.example/some/page") == 900.0  # keyed by host
    assert f.crawl_delay_for("slow.example") == 900.0  # a bare netloc: both scheme keys tried
    assert f.crawl_delay_for("https://other.example/") is None

    plain = _Session(robots_text="User-agent: *\nAllow: /")
    g, _ = _fetcher(plain, min_interval_s=0, respect_robots=True)
    g.fetch("https://fast.example/")
    assert g.crawl_delay_for("https://fast.example/") is None  # declared nothing: None, never 0


def test_a_trickling_body_is_refused_at_the_wall_clock_deadline():
    """The socket timeout bounds each recv, not the read: a tarpit that trickles a body a few
    bytes per timeout used to hold a worker for as long as it liked (2026-09-10)."""
    f = EthicalFetcher(min_interval_s=0, timeout=30.0)  # a REAL session: the streamed read path
    assert f.body_deadline_s == 300.0  # ten timeouts, never under two minutes
    assert EthicalFetcher(min_interval_s=0, timeout=5.0).body_deadline_s == 120.0
    assert EthicalFetcher(min_interval_s=0, timeout=30.0, body_deadline_s=7).body_deadline_s == 7.0
    clock = _FakeClock()
    f._now = clock.now

    class Trickle:
        headers = {"Content-Type": "text/html"}
        encoding = "utf-8"
        closed = False

        def iter_content(self, chunk_size):
            for _ in range(10):
                clock.advance(100.0)  # each chunk arrives 100 s after the last
                yield b"x" * 10

        def close(self):
            self.closed = True

    slow = Trickle()
    with pytest.raises(FetchFailed, match="body read exceeded 300s .* trickling"):
        f._read_body(slow, "https://tarpit.example/")
    assert slow.closed  # the connection is dropped, not drained

    class Prompt(Trickle):
        def iter_content(self, chunk_size):
            assert chunk_size == 16384  # the granularity at which a trickle can be caught
            yield b"<html>ok</html>"

    text, raw = f._read_body(Prompt(), "https://fine.example/")
    assert text == "<html>ok</html>" and raw is None
