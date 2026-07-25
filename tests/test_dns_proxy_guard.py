"""
C8 (2026-07-24 throughput brief, S-C slice 1): skip local DNS resolution when a
REMOTE-RESOLVING SOCKS proxy is engaged (socks5h/socks4a -- the exit resolves),
plus a short-TTL DNS cache for the path that still resolves locally.

The SSRF guard (and therefore this whole feature) only runs on a REAL
requests.Session (an injected fake/stub is defined to skip it entirely -- see
_guard_target's own "not self._real_session" early return) -- so, exactly like
tests/test_fetcher_limits.py's own TEST-03, every test here constructs a real
EthicalFetcher (no session= override) with socket.getaddrinfo monkeypatched,
and monkeypatches f.session.get directly for any HTTP response needed. No real
DNS/HTTP ever happens.
"""

from __future__ import annotations

import socket

import pytest

import src.ingest as ingest_mod
from src.ingest import BlockedTarget, EthicalFetcher, FetchFailed
from src.ingest import _is_remote_resolving_proxy as is_remote_resolving_proxy


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html", location=None, url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        if location is not None:
            self.headers["Location"] = location
        self.url = url


def _fake_get(routes):
    def get(url, timeout=None, allow_redirects=True, **kwargs):
        if url in routes:
            return routes[url]
        return _Resp(status_code=404, text="not found", url=url)

    return get


# --------------------------------------------------------------------------- #
# Pure scheme check.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("scheme", ["socks5h", "socks4a", "SOCKS5H", "Socks4A"])
def test_remote_resolving_schemes_are_recognised(scheme):
    assert is_remote_resolving_proxy(f"{scheme}://127.0.0.1:9050") is True


@pytest.mark.parametrize(
    "proxy",
    [
        "socks5://127.0.0.1:9050",  # local-resolve SOCKS -- the app's OWN documented
        "socks4://127.0.0.1:9050",  # example predating this fix; must NOT be treated
        "http://127.0.0.1:8118",  # as remote-resolving
        "https://127.0.0.1:8118",
        "",
        None,
        "not-a-url-at-all",
    ],
)
def test_non_remote_resolving_or_absent_proxies_are_not_recognised(proxy):
    assert is_remote_resolving_proxy(proxy) is False


# --------------------------------------------------------------------------- #
# NEGATIVE-SPACE (mandatory): the non-proxied path keeps the FULL SSRF guard,
# byte-identical -- a hostname resolving to a private/loopback address is
# STILL refused, exactly as before C8.
# --------------------------------------------------------------------------- #


def test_no_proxy_still_blocks_a_hostname_resolving_to_an_internal_ip(monkeypatch):
    def fake_getaddrinfo(host, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)  # real session, no proxy => full guard
    with pytest.raises(BlockedTarget, match="non-public"):
        f.fetch("https://totally-public.example/")


def test_a_local_resolving_socks5_proxy_still_gets_the_full_guard(monkeypatch):
    """The critical verify-at-build case: socks5:// (NO trailing h) is the
    app's OWN documented example prior to this fix -- it must NOT be treated
    as remote-resolving, or a real SSRF hole opens (PySocks would still hand
    the proxy a locally-resolved IP with nothing guarding it)."""
    calls = {"n": 0}

    def fake_getaddrinfo(host, *a, **k):
        calls["n"] += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0, proxy="socks5://127.0.0.1:9050")
    with pytest.raises(BlockedTarget):
        f.fetch("https://metadata.example/")
    assert calls["n"] >= 1  # the guard genuinely resolved (and then refused) it


# --------------------------------------------------------------------------- #
# The proxied-skip: a socks5h/socks4a proxy skips local resolution ENTIRELY --
# proven by asserting getaddrinfo is never even called, not merely that its
# result is ignored.
# --------------------------------------------------------------------------- #


def test_a_remote_resolving_proxy_skips_local_dns_resolution_entirely(monkeypatch):
    calls = {"n": 0}

    def fake_getaddrinfo(host, *a, **k):
        calls["n"] += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0, proxy="socks5h://127.0.0.1:9050")
    routes = {
        "https://public.example/robots.txt": _Resp(status_code=404, text=""),
        "https://public.example/x": _Resp(text="<html><body>hi</body></html>"),
    }
    monkeypatch.setattr(f.session, "get", _fake_get(routes))

    f.fetch("https://public.example/x")
    assert calls["n"] == 0, "a remote-resolving proxy must never trigger a local resolve"


def test_a_remote_resolving_proxy_never_blocks_even_a_would_be_internal_target(monkeypatch):
    """A hostname that WOULD resolve to an internal IP is never even checked --
    we genuinely cannot check it (there is no IP to look at), and that is the
    point: the exit resolves it, not us."""

    def fake_getaddrinfo(host, *a, **k):
        raise AssertionError("must never be called under a remote-resolving proxy")

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0, proxy="socks4a://127.0.0.1:9050")
    routes = {
        "https://would-be-internal.example/robots.txt": _Resp(status_code=404, text=""),
        "https://would-be-internal.example/x": _Resp(text="<html><body>hi</body></html>"),
    }
    monkeypatch.setattr(f.session, "get", _fake_get(routes))

    f.fetch("https://would-be-internal.example/x")  # must not raise, must not resolve


# --------------------------------------------------------------------------- #
# NEGATIVE-SPACE (mandatory): a redirect hop obeys the SAME rule as the
# initial fetch, in both directions (guarded when not remote-resolving,
# skipped when remote-resolving).
# --------------------------------------------------------------------------- #


def test_a_redirect_hop_is_guarded_exactly_like_the_initial_fetch_when_not_proxied(
    monkeypatch,
):
    def fake_getaddrinfo(host, *a, **k):
        if host == "evil-internal.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)

    def fake_get(url, timeout=None, allow_redirects=True, **kwargs):
        if url == "https://news.example/robots.txt":
            return _Resp(status_code=404, text="")
        if url == "https://news.example/x":
            return _Resp(status_code=301, text="", location="https://evil-internal.example/x")
        return _Resp(text="<html><body>hi</body></html>")

    monkeypatch.setattr(f.session, "get", fake_get)
    with pytest.raises(BlockedTarget):
        f.fetch("https://news.example/x")


def test_a_redirect_hop_also_skips_local_resolution_under_a_remote_resolving_proxy(
    monkeypatch,
):
    def fake_getaddrinfo(host, *a, **k):
        raise AssertionError("must never be called for a redirect hop either")

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0, proxy="socks5h://127.0.0.1:9050")

    def fake_get(url, timeout=None, allow_redirects=True, **kwargs):
        if url == "https://news.example/robots.txt":
            return _Resp(status_code=404, text="")
        if url == "https://news.example/x":
            return _Resp(
                status_code=301, text="", location="https://would-be-internal.example/x"
            )
        return _Resp(text="<html><body>hi</body></html>")

    monkeypatch.setattr(f.session, "get", fake_get)
    f.fetch("https://news.example/x")  # must not raise, must not resolve either hop


# --------------------------------------------------------------------------- #
# A6: the short-TTL cache for the still-locally-resolving path.
# --------------------------------------------------------------------------- #


def test_repeat_fetches_to_the_same_host_reuse_the_cached_resolution(monkeypatch):
    calls = {"n": 0}

    def fake_getaddrinfo(host, *a, **k):
        calls["n"] += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)
    routes = {
        "https://repeat.example/robots.txt": _Resp(status_code=404, text=""),
        "https://repeat.example/a": _Resp(text="<html><body>hi</body></html>"),
        "https://repeat.example/b": _Resp(text="<html><body>hi again</body></html>"),
    }
    monkeypatch.setattr(f.session, "get", _fake_get(routes))

    f.fetch("https://repeat.example/a")
    f.fetch("https://repeat.example/b")
    assert calls["n"] == 1, "the second fetch to the same host must reuse the cached resolution"


def test_an_expired_cache_entry_is_re_resolved_not_trusted_stale(monkeypatch):
    calls = {"n": 0}

    def fake_getaddrinfo(host, *a, **k):
        calls["n"] += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)
    routes = {
        "https://ttl.example/robots.txt": _Resp(status_code=404, text=""),
        "https://ttl.example/a": _Resp(text="<html><body>hi</body></html>"),
    }
    monkeypatch.setattr(f.session, "get", _fake_get(routes))

    fake_time = [1000.0]
    monkeypatch.setattr(f, "_now", lambda: fake_time[0])
    f.fetch("https://ttl.example/a")
    assert calls["n"] == 1
    fake_time[0] += 3600.0  # far past the (default 60s) TTL
    f.fetch("https://ttl.example/a")
    assert calls["n"] == 2, "an expired entry must be re-resolved, never trusted stale"


def test_dns_cache_is_reported_in_cache_stats(monkeypatch):
    def fake_getaddrinfo(host, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)
    routes = {
        "https://stats2.example/robots.txt": _Resp(status_code=404, text=""),
        "https://stats2.example/a": _Resp(text="<html><body>hi</body></html>"),
    }
    monkeypatch.setattr(f.session, "get", _fake_get(routes))

    f.fetch("https://stats2.example/a")
    assert f.cache_stats()["dns"] == 1


def test_a_getaddrinfo_failure_is_still_a_clean_fetchfailed_not_a_crash(monkeypatch):
    def fake_getaddrinfo(host, *a, **k):
        raise OSError("simulated DNS failure")

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)
    with pytest.raises(FetchFailed, match="cannot resolve"):
        f.fetch("https://unresolvable.example/")
