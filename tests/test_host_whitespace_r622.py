"""A host-chosen name with spaces never reaches the SSRF guard's lookup, and no failure sentence begins with it (R622).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``urlparse(...).hostname`` keeps spaces and lower-cases, so a redirect's Location can name the host
``network kill switch is active -- collection stopped by operator`` (from any case), and before R622 a redirect hop handed that name to
``_guard_target`` before ``_refuse_parser_mismatch`` read the hop on the next turn of the loop; ``fetch()``, ``declared_sitemaps()`` and
both preflights handed theirs to it with no such check at all. Where a resolver answers the name with a non-public address, the guard's
sentence was ``<host> resolves to a non-public address (...)``: it began with the kill switch's whole sentence, so the robots reader's
``refused_by_name`` re-raised it uncached (the host was never backed off), the pipeline read the feed as ``skipped_offline``, the preflights
wrote ``skipped_offline``, and the health count, with a Stop pressed after the probe, counted a host's failure as the person's Stop.

Measured on this machine (glibc 2.39): the C library refuses a name holding a space or a tab before it sends any DNS query (EAI_NONAME, no
packet under strace), so the guard's own lookup fails with "cannot resolve host ...", which begins with fixed words. The resolver here is a
stand-in for one that answers (``airplane._orig_getaddrinfo``, the real call under the socket guard), so every other layer is the real one;
it answers 127.0.0.1 for the crafted names and records every name it is asked. A loopback HTTP server is the proxy, named
``http://localhost:<port>``: a proxy given by NAME stands the connect-time scope down (``ssrf_guard._proxy_endpoints``), which is the
configuration in which the guard's own sentence is the one a caller sees. Nothing leaves the machine: every request goes to the proxy.
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from src.ingest import (
    KILL_SWITCH_REFUSAL_HEAD,
    BlockedTarget,
    EthicalFetcher,
    FetchError,
    FetchFailed,
    RobotsUnavailable,
    airplane,
    clear_kill_switch,
)
from src.ingest.fetch_verdict import (
    KILL_SWITCH_REFUSAL,
    classify_fetch_failure,
    is_kill_switch_refusal,
)
from src.monitoring.secret_scrub import record_text

S = KILL_SWITCH_REFUSAL
#: The fixed sentences a refused host is written with; neither names the host.
AUTHORITY = "URL authority contains a backslash, whitespace or control character"
HOST = "URL host contains a backslash, whitespace or control character"
PUBLIC = "public.example"
_PUBLIC_IP = "93.184.215.14"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")

#: Redirect targets whose host, as ``urlparse`` reads it, begins with the switch's whole sentence (the closest a host can get is the
#: sentence itself: ``hostname`` lower-cases, and the sentence is lower-case already).
SPELLED = [
    f"http://{S}/",
    f"http://{S.upper()}/",
    f"http://{S}.evil.example/x",
    f"https://{S}/",  # another scheme: ``urljoin`` hands the Location back as it came
    f"//{S}/x",  # a network-path reference
]


@pytest.fixture(autouse=True)
def _armed(monkeypatch):
    for var in {*_PROXY_VARS, *(v for v in os.environ if v.lower().endswith("_proxy")), "OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"}:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    monkeypatch.setattr(airplane, "_airplane_armed", airplane._airplane_armed)
    assert airplane.install_airplane_socket_guard()
    clear_kill_switch()
    yield
    clear_kill_switch()


@pytest.fixture
def asked(monkeypatch) -> list[str]:
    """Every name the resolver is asked. It answers ``public.example`` with a public address, hands ``localhost`` (the proxy) to the real
    one, and answers every other name with loopback, so no name a test crafts is ever sent to a real resolver."""
    real = airplane._orig_getaddrinfo
    names: list[str] = []

    def resolver(host, *a, **k):
        name = host.decode() if isinstance(host, bytes) else str(host)
        names.append(name)
        if name == PUBLIC:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_IP, 0))]
        if name == "localhost":
            return real(host, *a, **k)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(airplane, "_orig_getaddrinfo", resolver)
    return names


@contextlib.contextmanager
def _proxy(routes: dict[str, tuple[int, dict[str, str]]]):
    """A loopback HTTP proxy answering ``routes`` (the absolute URL a request names, unquoted -> status, headers); anything else is 404.
    Yields its URL, by name."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
            status, headers = routes.get(urllib.parse.unquote(self.path), (404, {}))
            body = b"<html><body>ok</body></html>" if status == 200 else b""
            self.send_response(status)
            for k, v in {"Content-Type": "text/html", **headers, "Content-Length": str(len(body))}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://localhost:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def _fetcher(tmp_path, proxy: str | None = None) -> tuple[EthicalFetcher, list[str]]:
    """A real fetcher whose ``_guard_target`` is a spy that calls the real one: returns it and the hosts the guard was handed."""
    f = EthicalFetcher(proxy=proxy, min_interval_s=0, retry_backoff_s=0, max_retries=0, robots_cache_path=tmp_path / "robots.json")
    seen: list[str] = []
    real = f._guard_target

    def guard(host):
        seen.append(host)
        return real(host)

    f._guard_target = guard  # type: ignore[method-assign]
    return f, seen


def _not_the_switch(exc: BaseException) -> None:
    """No reader takes ``exc`` for the kill switch's refusal."""
    from src.ingest.pipeline import _failure_reason

    text = record_text(exc, typed=False)
    assert not text.startswith(S), text
    # the robots reader's test, as ``_get_robots`` writes it
    assert not (isinstance(exc, FetchError) and record_text(exc, typed=False).startswith(KILL_SWITCH_REFUSAL_HEAD)), text
    assert not is_kill_switch_refusal(text) and not is_kill_switch_refusal(record_text(exc, typed=True)), text
    assert classify_fetch_failure(text) != "offline" and _failure_reason(text) != "offline", text


def _crafted(names: list[str]) -> list[str]:
    return [n for n in names if n not in (PUBLIC, "localhost", "127.0.0.1")]


# --- the named case: a redirect hostname with spaces spelling the whole sentence --------------------------------------------------------


@pytest.mark.parametrize("location", SPELLED)
def test_a_redirect_host_spelling_the_switch_sentence_is_refused_before_any_lookup(tmp_path, asked, location):
    assert (urlparse(urllib.parse.urljoin(f"http://{PUBLIC}/", location)).hostname or "").startswith(S), "premise: the host spells it"
    with _proxy({f"http://{PUBLIC}/": (302, {"Location": location})}) as proxy:
        f, guarded = _fetcher(tmp_path, proxy)
        with pytest.raises(BlockedTarget) as caught:
            f.fetch(f"http://{PUBLIC}/", require_html=False)
    assert record_text(caught.value, typed=False) == AUTHORITY
    assert guarded == [PUBLIC], f"the hop reached the guard: {guarded}"  # the fetch's own check only
    assert _crafted(asked) == [], f"the resolver was asked: {asked}"
    _not_the_switch(caught.value)


def test_a_robots_redirect_spelling_the_sentence_is_the_hosts_failure_and_backs_off(tmp_path, asked):
    """``_get_robots`` re-raises, uncached, a failure that BEGINS with the switch's words; a host's own failure is charged to the host."""
    with _proxy({f"http://{PUBLIC}/robots.txt": (302, {"Location": f"http://{S}/robots.txt"})}) as proxy:
        f, guarded = _fetcher(tmp_path, proxy)
        with pytest.raises(RobotsUnavailable) as caught:
            f.fetch(f"http://{PUBLIC}/story", require_html=False)
    assert f._robots_fails == {f"http://{PUBLIC}": 1} and f._robots_cause == {f"http://{PUBLIC}": "unreachable"}
    assert S not in guarded and _crafted(asked) == [], (guarded, asked)
    _not_the_switch(caught.value)


# --- the independent read of R622: two ValueErrors that escaped the fetch raw ----------------------------------------------------------

#: Locations ``urljoin`` cannot read (an unclosed IPv6 bracket). Before the read's fold the ValueError escaped ``fetch()``: the robots read
#: re-raised it uncounted (the host was never backed off) and ``ingest_url``, which catches FetchError, did not catch it.
UNREADABLE = ["http://[::1/x", "//[::1/x", "http://[a/"]


@pytest.mark.parametrize("location", UNREADABLE)
def test_an_unreadable_redirect_is_the_hosts_failure_not_a_raw_value_error(tmp_path, asked, location):
    with _proxy({f"http://{PUBLIC}/": (302, {"Location": location})}) as proxy:
        f, guarded = _fetcher(tmp_path, proxy)
        with pytest.raises(FetchError) as caught:
            f.fetch(f"http://{PUBLIC}/", require_html=False)
    assert type(caught.value) is FetchFailed
    # requests itself reads the Location to build ``Response.next`` and raises first; the fetcher writes its own fixed words
    assert record_text(caught.value, typed=False) == f"redirect to a URL that cannot be read, from http://{PUBLIC}/", caught.value
    assert guarded == [PUBLIC] and _crafted(asked) == [], (guarded, asked)
    _not_the_switch(caught.value)


@pytest.mark.parametrize("location", UNREADABLE)
def test_an_unreadable_location_the_session_hands_back_is_refused_in_fixed_words(tmp_path, asked, monkeypatch, location):
    """The fetcher's own ``urljoin`` of the Location is read the same way, for a session that hands a 3xx back without parsing it."""
    f, guarded = _fetcher(tmp_path)
    answer = SimpleNamespace(status_code=302, headers={"Location": location}, url=f"http://{PUBLIC}/", close=lambda: None)
    monkeypatch.setattr(f.session, "get", lambda *_a, **_k: answer)
    with pytest.raises(FetchError) as caught:
        f._guarded_redirect_get(f"http://{PUBLIC}/")
    assert type(caught.value) is FetchFailed
    assert record_text(caught.value, typed=False).startswith("redirect to a URL that cannot be read: "), caught.value
    _not_the_switch(caught.value)


def test_a_value_error_the_request_raises_is_the_hosts_failure_and_carries_no_context(tmp_path, monkeypatch):
    """The handler sits round the loop, not round the request line (that line stays as main has it, for CodeQL). The error is raised
    after the handler, so no ValueError (or UnicodeError) is its context, and the redirect chain is never followed further."""
    f, guarded = _fetcher(tmp_path)

    def get(*_a, **_k):
        raise ValueError("Invalid IPv6 URL")

    monkeypatch.setattr(f.session, "get", get)
    with pytest.raises(FetchError) as caught:
        f._guarded_redirect_get(f"http://{PUBLIC}/")
    assert type(caught.value) is FetchFailed
    assert record_text(caught.value, typed=False) == f"redirect to a URL that cannot be read, from http://{PUBLIC}/", caught.value
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert guarded == []
    _not_the_switch(caught.value)


def test_the_unreadable_redirect_names_the_hop_whose_answer_could_not_be_read(tmp_path, monkeypatch):
    """After one good hop, the sentence names the URL the failing request was for, not the first one."""
    f, _guarded = _fetcher(tmp_path)
    hops: list[str] = []
    f._guard_target = hops.append  # type: ignore[method-assign]
    hop = f"http://{PUBLIC}/next"
    answer = SimpleNamespace(status_code=302, headers={"Location": hop}, url=f"http://{PUBLIC}/", close=lambda: None)
    calls: list[str] = []

    def get(url, **_k):
        calls.append(url)
        if len(calls) == 1:
            return answer
        raise ValueError("Invalid IPv6 URL")

    monkeypatch.setattr(f.session, "get", get)
    with pytest.raises(FetchFailed) as caught:
        f._guarded_redirect_get(f"http://{PUBLIC}/")
    assert calls == [f"http://{PUBLIC}/", hop] and hops == [PUBLIC]
    assert record_text(caught.value, typed=False) == f"redirect to a URL that cannot be read, from {hop}", caught.value


@pytest.mark.parametrize("name", ["InvalidURL", "InvalidHeader", "MissingSchema", "InvalidSchema"])
def test_a_request_error_that_is_also_a_value_error_stays_a_request_error(tmp_path, monkeypatch, name):
    """requests' own URL and header errors are RequestException AND ValueError: they keep the request error's path (the fetcher's
    "request error for <url>" and its retries), not the unreadable-redirect words."""
    import requests

    cls = getattr(requests.exceptions, name)
    assert issubclass(cls, ValueError)
    f, _guarded = _fetcher(tmp_path)

    def get(*_a, **_k):
        raise cls("no")

    monkeypatch.setattr(f.session, "get", get)
    with pytest.raises(cls):
        f._guarded_redirect_get(f"http://{PUBLIC}/")


@pytest.mark.parametrize("location", UNREADABLE)
def test_an_unreadable_robots_redirect_backs_the_host_off(tmp_path, asked, location):
    with _proxy({f"http://{PUBLIC}/robots.txt": (302, {"Location": location})}) as proxy:
        f, _guarded = _fetcher(tmp_path, proxy)
        with pytest.raises(RobotsUnavailable) as caught:
            f.fetch(f"http://{PUBLIC}/story", require_html=False)
    assert f._robots_fails == {f"http://{PUBLIC}": 1}, f._robots_fails
    _not_the_switch(caught.value)


@pytest.mark.parametrize("host", ["a..example", "x" * 64 + ".example"])
def test_a_name_the_resolver_cannot_encode_is_a_dns_failure_not_a_raw_unicode_error(tmp_path, monkeypatch, host):
    """``socket.getaddrinfo`` IDNA-encodes the name before any query and raises a UnicodeError (a ValueError) for an empty label or one
    over 63 characters. The stand-in resolver does exactly that encoding, so no name is sent anywhere."""

    def resolver(name, *a, **k):
        (name.decode() if isinstance(name, bytes) else str(name)).encode("idna")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(airplane, "_orig_getaddrinfo", resolver)
    f, _guarded = _fetcher(tmp_path)
    with pytest.raises(FetchError) as caught:
        f._guard_target(host)
    assert type(caught.value) is FetchFailed, caught.value
    text = record_text(caught.value, typed=False)
    assert text.startswith(f"cannot resolve host {host!r}: "), text
    assert classify_fetch_failure(text) == "dns", text
    _not_the_switch(caught.value)
    with pytest.raises(FetchError):  # and through the fetch itself, never a raw ValueError
        f.fetch(f"http://{host}/story", require_html=False)


def test_the_health_count_does_not_take_a_hosts_redirect_for_the_stop(tmp_path, asked, monkeypatch):
    from src.api import monitoring as api_monitoring

    class _OneSource:
        def __init__(self, source):
            self.source = source

        def query(self, *_a):
            return self

        filter = order_by = limit = lambda self, *_a, **_k: self  # noqa: E731

        def all(self):
            return [self.source]

    source = SimpleNamespace(id=1, name="s", rss_url=f"http://{PUBLIC}/feed", domain=PUBLIC)
    with _proxy({f"http://{PUBLIC}/feed": (302, {"Location": f"http://{S}/feed"})}) as proxy:
        f, _guarded = _fetcher(tmp_path, proxy)
        # a Stop pressed after the probe, before the count (main reads the window since R617, no longer the switch as it is now)
        monkeypatch.setattr(api_monitoring, "kill_switch_engaged_since", lambda _epoch: True)
        out = api_monitoring.sources_health(limit=1, db=_OneSource(source), fetcher=f)
    assert out["summary"] == {"down": 1}, out
    assert out["sources"][0]["detail"] == AUTHORITY and _crafted(asked) == [], (out, asked)


# --- a backslash, a tab, a newline and control characters in a redirect authority -----------------------------------------------------


class _Resp:
    def __init__(self, status: int, location: str | None = None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.url = "http://www.example.org/"
        self.content = b""

    def close(self) -> None:
        pass


class _Session:
    """Answers the first request with ``first`` and every later one with 200; records what was asked."""

    def __init__(self, first: _Resp):
        self.first = first
        self.urls: list[str] = []

    def get(self, url, **_kw):
        self.urls.append(url)
        return self.first if len(self.urls) == 1 else _Resp(200)


def _stub_fetcher(session) -> tuple[EthicalFetcher, list[str]]:
    f = EthicalFetcher.__new__(EthicalFetcher)
    f.session = session
    f.timeout = 5
    f._max_redirects = 3
    seen: list[str] = []
    f._guard_target = lambda host: seen.append(host)  # type: ignore[method-assign,assignment,func-returns-value]
    f._isolated_proxies = lambda netloc: None  # type: ignore[method-assign]
    f._request_proxy_endpoints = lambda url, proxies: {}  # type: ignore[method-assign]
    return f, seen


IN_AUTHORITY = {
    "spaces": f"http://{S}/",
    "backslash-before-at": "http://evil.test\\@www.example.org/",
    "backslash": "http://a\\b.example/",
    "tab": "http://a\tb.example/",
    "newline": "http://a\nb.example/",
    "carriage-return": "http://a\rb.example/",
    "crlf-network-path": "//a\r\nb.example/x",
    "tab-other-scheme": "https://a\tb.example/",
    "nul": "http://a\x00b.example/",
    "soh": "http://a\x01b.example/",
    "vertical-tab": "http://a\x0bb.example/",
    "escape": "http://a\x1bb.example/",
    "del": "http://a\x7fb.example/",
    "nbsp": "http://a b.example/",
    "tab-inside-the-slashes": "http:/\t/a\\b.example/",  # the tab is dropped and the backslash host remains
    "tab-in-a-bracketed-host": "http://[::1\t]/",  # shown as a space, the bracketed host cannot be read
}


@pytest.mark.parametrize("location", list(IN_AUTHORITY.values()), ids=list(IN_AUTHORITY))
def test_a_redirect_authority_with_a_backslash_whitespace_or_control_is_refused_before_the_guard(location):
    s = _Session(_Resp(302, location))
    f, guarded = _stub_fetcher(s)
    with pytest.raises(BlockedTarget) as caught:
        f._guarded_redirect_get("http://www.example.org/")
    assert guarded == [], f"the guard was handed {guarded!r}"
    assert s.urls == ["http://www.example.org/"]
    assert record_text(caught.value, typed=False) in (AUTHORITY, "URL host cannot be read")
    _not_the_switch(caught.value)


# --- the other callers of the guard --------------------------------------------------------------------------------------------------

HOSTS = {"spaces": S, "backslash": "a\\b.example", "tab": "a\tb.example", "newline": "a\nb.example", "soh": "a\x01b.example", "del": "a\x7fb.example"}


@pytest.mark.parametrize("host", list(HOSTS.values()), ids=list(HOSTS))
def test_fetch_refuses_the_host_before_the_guard(tmp_path, asked, host):
    f, guarded = _fetcher(tmp_path)
    with pytest.raises(BlockedTarget) as caught:
        f.fetch(f"https://{host}/story")
    assert guarded == [] and _crafted(asked) == [], (guarded, asked)
    assert record_text(caught.value, typed=False) == AUTHORITY
    _not_the_switch(caught.value)


@pytest.mark.parametrize("host", list(HOSTS.values()), ids=list(HOSTS))
def test_declared_sitemaps_refuses_the_host_before_the_guard(tmp_path, asked, host):
    f, guarded = _fetcher(tmp_path)
    with pytest.raises(BlockedTarget) as caught:
        f.declared_sitemaps(f"https://{host}")
    assert guarded == [] and _crafted(asked) == [], (guarded, asked)
    assert record_text(caught.value, typed=False) == AUTHORITY


@pytest.mark.parametrize("host", list(HOSTS.values()), ids=list(HOSTS))
def test_the_source_preflight_refuses_the_domain_before_the_guard(tmp_path, asked, host):
    from src.monitoring import preflight

    f, guarded = _fetcher(tmp_path)
    rec = preflight._check_one(f, SimpleNamespace(id=1, domain=host))
    assert guarded == [] and _crafted(asked) == [], (guarded, asked)
    assert rec["verdict"] == "unreachable" and not rec.get("skipped_offline"), rec
    assert rec["robots_error"] == AUTHORITY, rec


@pytest.mark.parametrize("host", list(HOSTS.values()), ids=list(HOSTS))
def test_the_feed_preflight_refuses_the_host_before_the_guard(tmp_path, asked, host):
    from src.monitoring import feed_preflight

    f, guarded = _fetcher(tmp_path)
    rec = feed_preflight._check_host_robots(f, host)
    assert guarded == [] and _crafted(asked) == [], (guarded, asked)
    assert rec["robots"] == "unreachable" and not rec.get("skipped_offline"), rec
    assert rec["error"] == AUTHORITY, rec


@pytest.mark.parametrize("host", [*HOSTS.values(), "a b.example", "[v1.x:" + S + "]"], ids=[*HOSTS, "space", "ipvfuture"])
def test_the_guard_itself_refuses_the_host_before_any_lookup(tmp_path, asked, host):
    """For a caller that does not check first: the guard's own refusal, written in fixed words, before the resolver is asked."""
    f = EthicalFetcher(min_interval_s=0, robots_cache_path=tmp_path / "robots.json")
    with pytest.raises(BlockedTarget) as caught:
        f._guard_target(host)
    assert asked == [], asked
    assert record_text(caught.value, typed=False) == HOST
    _not_the_switch(caught.value)


def test_the_guards_resolve_time_sentence_begins_with_fixed_words(tmp_path, asked):
    f = EthicalFetcher(min_interval_s=0, robots_cache_path=tmp_path / "robots.json")
    with pytest.raises(BlockedTarget) as caught:
        f._guard_target("network-kill-switch-is-active.evil.example")
    text = record_text(caught.value, typed=False)
    assert text == "refusing to fetch 'network-kill-switch-is-active.evil.example': it resolves to a non-public address (127.0.0.1)", text


# --- controls: an ordinary redirect, and a space in a path or query --------------------------------------------------------------------


def test_an_ordinary_redirect_is_still_followed(tmp_path, asked):
    routes = {f"http://{PUBLIC}/": (302, {"Location": "/next"}), f"http://{PUBLIC}/next": (200, {})}
    with _proxy(routes) as proxy:
        f, guarded = _fetcher(tmp_path, proxy)
        res = f.fetch(f"http://{PUBLIC}/")
    assert res.status_code == 200 and res.final_url == f"http://{PUBLIC}/next", res.final_url
    assert guarded == [PUBLIC, PUBLIC]  # the fetch's own check, and the hop's


@pytest.mark.parametrize(
    ("start", "location", "final"),
    [
        (f"http://{PUBLIC}/some story.html?q=a b", None, f"http://{PUBLIC}/some story.html?q=a b"),
        (f"http://{PUBLIC}/", f"http://{PUBLIC}/some article.html?q=a b", f"http://{PUBLIC}/some article.html?q=a b"),
        (f"http://{PUBLIC}/", "/a b?c=d e#f g", f"http://{PUBLIC}/a b?c=d e"),
    ],
    ids=["first-request", "absolute-hop", "relative-hop"],
)
def test_a_space_in_a_path_or_query_is_still_fetched(tmp_path, asked, start, location, final):
    routes = {final: (200, {})}
    if location is not None:
        routes[start] = (302, {"Location": location})
    with _proxy(routes) as proxy:
        f, _guarded = _fetcher(tmp_path, proxy)
        res = f.fetch(start)
    assert res.status_code == 200 and urllib.parse.unquote(res.final_url).split("#")[0] == final, res.final_url
    assert _crafted(asked) == [], asked


@pytest.mark.parametrize("location", ["/a\tb?q=x\ty", "http://www.example.org/a\r\nb", "relative\tpath"], ids=["tab", "crlf", "relative"])
def test_a_tab_or_newline_outside_the_authority_is_still_followed(location):
    s = _Session(_Resp(302, location))
    f, guarded = _stub_fetcher(s)
    f._guarded_redirect_get("http://www.example.org/")
    assert guarded == ["www.example.org"] and len(s.urls) == 2, (guarded, s.urls)
