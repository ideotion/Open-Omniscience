"""Per-host Tor stream isolation in the EthicalFetcher.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer concept 2026-06-13 (the "protect the user from other sources" win,
done the safe way — circuit isolation, NOT clearnet). Over a SOCKS (Tor) proxy
each host's requests ride their own circuit via IsolateSOCKSAuth (a per-host
SOCKS username), so no exit node or circuit observer can link the user's
activity across different sources. A no-op for non-SOCKS / no proxy / disabled.
The page fetch AND its robots.txt share the host's circuit.
"""

from __future__ import annotations

from src.ingest import EthicalFetcher


class _Resp:
    def __init__(self, status_code=200, text="<html>ok</html>", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _RecordingSession:
    """Serves robots + a page, recording the ``proxies`` kwarg of every request."""

    def __init__(self):
        self.headers = {}
        self.proxies: dict = {}
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        self.calls.append((url, proxies))
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", content_type="text/plain", url=url)
        return _Resp(text="<html>ok</html>", url=url)


def _fetcher(session, proxy):
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=session, proxy=proxy)


_SOCKS = "socks5://127.0.0.1:9050"


def _proxy_userinfo(proxies: dict | None) -> str | None:
    """The 'user:pass@' injected into the SOCKS proxy URL, if any."""
    if not proxies:
        return None
    url = proxies.get("https") or proxies.get("http") or ""
    return url.split("://", 1)[1].split("@")[0] if "@" in url else None


def test_socks_proxy_isolates_each_host_robots_and_page_on_one_circuit():
    sess = _RecordingSession()
    _fetcher(sess, _SOCKS).fetch("https://hosta.example/story")
    # Both the robots.txt fetch and the page fetch carried a per-host SOCKS token.
    assert len(sess.calls) == 2
    tokens = {_proxy_userinfo(p) for _, p in sess.calls}
    assert tokens == {"hosta.example:hosta.example"}  # one circuit, that host's


def test_different_hosts_get_different_circuits():
    sess = _RecordingSession()
    f = _fetcher(sess, _SOCKS)
    f.fetch("https://hosta.example/x")
    f.fetch("https://hostb.example/y")
    page_tokens = {_proxy_userinfo(p) for u, p in sess.calls if not u.endswith("/robots.txt")}
    assert page_tokens == {"hosta.example:hosta.example", "hostb.example:hostb.example"}


def test_non_socks_proxy_is_not_isolated():
    sess = _RecordingSession()
    _fetcher(sess, "http://127.0.0.1:8118").fetch("https://hosta.example/x")
    # An HTTP proxy can't do per-stream isolation -> no per-request override.
    assert all(p is None for _, p in sess.calls)


def test_no_proxy_no_isolation():
    sess = _RecordingSession()
    _fetcher(sess, None).fetch("https://hosta.example/x")
    assert all(p is None for _, p in sess.calls)


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("OO_TOR_STREAM_ISOLATION", "0")
    sess = _RecordingSession()
    _fetcher(sess, _SOCKS).fetch("https://hosta.example/x")  # SOCKS, but disabled
    assert all(p is None for _, p in sess.calls)


def test_isolated_proxies_unit():
    f = _fetcher(_RecordingSession(), _SOCKS)
    iso = f._isolated_proxies("news.example")
    assert iso == {
        "http": "socks5://news.example:news.example@127.0.0.1:9050",
        "https": "socks5://news.example:news.example@127.0.0.1:9050",
    }
    assert f._isolated_proxies(None) is None
    # Non-SOCKS proxy -> nothing to isolate.
    assert _fetcher(_RecordingSession(), "http://127.0.0.1:8118")._isolated_proxies("x") is None
