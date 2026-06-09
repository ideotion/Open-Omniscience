"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Regression tests for finding ETH-01: RSS-feed discovery must go through the
EthicalFetcher (robots.txt fail-closed, SSRF guard, per-host rate limiting),
not raw ``requests``. Before the fix, ``discover_rss_feeds`` fetched the target
page directly, bypassing every ethical-scraping guard.
"""

from __future__ import annotations

from datetime import UTC

from src.ingest import BlockedTarget, FetchResult, RobotsDisallowed
from src.services.duckduckgo import DuckDuckGoSearch


class _RecordingFetcher:
    """A fake EthicalFetcher that records calls and replays scripted outcomes.

    Mirrors the real fetch contract: ``fetch(url, require_html=...)`` returns a
    FetchResult or raises a FetchError subclass. This lets us prove discovery
    honours the same robots/SSRF refusals the real fetcher would raise.
    """

    def __init__(self, outcomes: dict[str, object]):
        self._outcomes = outcomes
        self.calls: list[tuple[str, bool]] = []

    def fetch(self, url: str, *, require_html: bool = True) -> FetchResult:
        self.calls.append((url, require_html))
        outcome = self._outcomes.get(url)
        if outcome is None:
            # Unscripted common-path probes (e.g. /rss, /feed) simulate a miss --
            # a real fetcher would 404. Discovery must swallow these.
            from src.ingest import FetchFailed

            raise FetchFailed(f"no such resource: {url}")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _html(url: str, body: str) -> FetchResult:
    from datetime import datetime

    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        content=body,
        content_type="text/html",
        fetched_at=datetime.now(UTC),
    )


def test_discovery_uses_injected_fetcher_not_raw_requests(monkeypatch):
    """discover_rss_feeds must route the page fetch through the given fetcher."""
    page = (
        "<html><head>"
        '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        "</head></html>"
    )
    fetcher = _RecordingFetcher(
        {
            "https://example.com": _html("https://example.com", page),
            # the discovered/validated feed is fetched as non-HTML XML
            "https://example.com/feed.xml": FetchResult(
                requested_url="https://example.com/feed.xml",
                final_url="https://example.com/feed.xml",
                status_code=200,
                content='<?xml version="1.0"?><rss></rss>',
                content_type="application/rss+xml",
                fetched_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            ),
        }
    )
    # If discovery still used raw requests, this would make a real network call
    # and never touch our fetcher.
    monkeypatch.setattr(
        "src.services.duckduckgo.requests",
        _ForbiddenRequests(),
    )

    feeds = DuckDuckGoSearch.discover_rss_feeds("https://example.com", fetcher=fetcher)

    assert ("https://example.com", True) in fetcher.calls
    assert "https://example.com/feed.xml" in feeds


def test_discovery_respects_robots_fail_closed(monkeypatch):
    """When the fetcher refuses (robots disallow), discovery yields no feeds and
    does not fall back to a raw request."""
    fetcher = _RecordingFetcher(
        {"https://blocked.example": RobotsDisallowed("robots.txt disallows")}
    )
    monkeypatch.setattr("src.services.duckduckgo.requests", _ForbiddenRequests())

    feeds = DuckDuckGoSearch.discover_rss_feeds("https://blocked.example", fetcher=fetcher)

    assert feeds == []
    assert fetcher.calls == [("https://blocked.example", True)]


def test_discovery_respects_ssrf_guard(monkeypatch):
    """A target the fetcher blocks for SSRF reasons must not be fetched raw."""
    fetcher = _RecordingFetcher({"http://169.254.169.254/": BlockedTarget("non-public address")})
    monkeypatch.setattr("src.services.duckduckgo.requests", _ForbiddenRequests())

    feeds = DuckDuckGoSearch.discover_rss_feeds("http://169.254.169.254/", fetcher=fetcher)

    assert feeds == []


class _ForbiddenRequests:
    """Stand-in for the ``requests`` module that fails the test if any HTTP verb
    is called -- proving discovery no longer reaches the network directly."""

    def _boom(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("discovery made a raw requests call, bypassing the EthicalFetcher")

    get = property(lambda self: self._boom)
    head = property(lambda self: self._boom)
    post = property(lambda self: self._boom)

    class exceptions:  # noqa: N801 - mimic requests.exceptions namespace
        class RequestException(Exception):
            pass
