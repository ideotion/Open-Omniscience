"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Regression tests for finding BUG-02: the EthicalFetcher now retries *transient*
failures (network errors, 429, 5xx) with bounded exponential backoff, while
deterministic refusals (4xx, robots disallow) are never retried.
"""

from __future__ import annotations

import pytest
import requests

from src.ingest import EthicalFetcher, FetchFailed, RobotsDisallowed


class _Resp:
    def __init__(self, status_code=200, text="ok", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _ScriptedSession:
    """Returns a scripted sequence of responses/exceptions for the page URL;
    always serves a permissive robots.txt."""

    def __init__(self, page_url, script):
        self.headers = {}
        self._page = page_url
        self._script = list(script)
        self.page_calls = 0

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", content_type="text/plain", url=url)
        if url == self._page:
            self.page_calls += 1
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return _Resp(status_code=404, text="nf", url=url)


def _fetcher(session, **kw):
    # backoff 0 so the test does not actually sleep
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=session, **kw)


def test_retries_then_succeeds_on_transient_503():
    page = "https://example.com/a"
    sess = _ScriptedSession(page, [_Resp(status_code=503), _Resp(status_code=200, text="<html>ok</html>")])
    f = _fetcher(sess, max_retries=2)
    result = f.fetch(page)
    assert result.status_code == 200
    assert sess.page_calls == 2  # one retry


def test_retries_then_succeeds_on_network_error():
    page = "https://example.com/a"
    sess = _ScriptedSession(page, [requests.ConnectionError("boom"), _Resp(text="<html>ok</html>")])
    f = _fetcher(sess, max_retries=2)
    result = f.fetch(page)
    assert result.status_code == 200
    assert sess.page_calls == 2


def test_gives_up_after_max_retries():
    page = "https://example.com/a"
    sess = _ScriptedSession(page, [_Resp(status_code=503)] * 5)
    f = _fetcher(sess, max_retries=2)
    with pytest.raises(FetchFailed, match="HTTP 503"):
        f.fetch(page)
    assert sess.page_calls == 3  # initial + 2 retries


def test_does_not_retry_4xx():
    page = "https://example.com/a"
    sess = _ScriptedSession(page, [_Resp(status_code=404)] * 5)
    f = _fetcher(sess, max_retries=2)
    with pytest.raises(FetchFailed, match="HTTP 404"):
        f.fetch(page)
    assert sess.page_calls == 1  # no retry on a deterministic client error


def test_does_not_retry_robots_disallow():
    page = "https://example.com/private"

    class _RobotsDeny(_ScriptedSession):
        def get(self, url, timeout=None, allow_redirects=True, **kwargs):
            if url.endswith("/robots.txt"):
                return _Resp(text="User-agent: *\nDisallow: /private", content_type="text/plain", url=url)
            return super().get(url, timeout=timeout, allow_redirects=allow_redirects, **kwargs)

    sess = _RobotsDeny(page, [_Resp(status_code=200)] * 3)
    f = _fetcher(sess, max_retries=2)
    with pytest.raises(RobotsDisallowed):
        f.fetch(page)
    assert sess.page_calls == 0  # robots refusal happens before any page fetch
