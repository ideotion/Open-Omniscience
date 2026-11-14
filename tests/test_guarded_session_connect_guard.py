"""The connect-time SSRF guard covers ``GuardedSession`` too (OPEN_QUEUE 2026-09-17, "Two findings DISCLOSED", finding (1)).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``ssrf_guard.connect_scope`` had one caller, ``EthicalFetcher._guarded_redirect_get``. A ``guarded_session`` (Wikidata, the OSM and
Wikipedia dump downloads, ring_loader, the gazetteer build, DuckDuckGo, the AI installer) got the kill switch, the protected-mode proxy
and the airplane socket guard, but no check of WHERE its sockets went: a name that resolves to 127.0.0.1 was fetched and its body
returned as a clean 200. Reproduced on main 47e356835 by the first test below before the fix. The session now enters the scope in
``send``, the method ``requests`` calls for the first request and for every redirect hop, with the proxy mapping that request is sent
through, and a refusal is a ``ConnectTargetRefused``: a ``RequestException`` (every caller already handles one) and not a
``ConnectionError`` (nothing reached the target, and a retry would ask again for the same refused address).
"""

from __future__ import annotations

import http.server
import socket
import threading
from collections.abc import Iterator

import pytest
import requests

import src.ingest.airplane as ap
from src.ingest import clear_kill_switch
from src.ingest.ssrf_guard import current_scope
from src.safety.fetcher import ConnectTargetRefused, GuardedSession

_SEEN: list[str] = []


class _Handler(http.server.BaseHTTPRequestHandler):
    """The 'internal service' an SSRF reaches; answers an absolute-form (proxy) request line too."""

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        _SEEN.append(self.path)
        body = b"INTERNAL SERVICE SECRET"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def loopback_server() -> Iterator[int]:
    _SEEN.clear()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(srv.server_address[1])
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


@pytest.fixture
def internal_dns(loopback_server: int):
    """``internal.test`` resolves to loopback, through the production hook (installed as ``airplane._orig_getaddrinfo``, so the hook
    under test stays in place and calls it). No answer is public: a ``GuardedSession`` makes no lookup of its own before the connect,
    so the first answer is the one it connects to, and a public one would leave the machine."""
    was_installed = ap.is_installed()
    saved = ap._orig_getaddrinfo
    calls: list[str] = []

    def _resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host == "internal.test":
            calls.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 0))]
        return saved(host, port, *args, **kwargs)

    ap._orig_getaddrinfo = _resolver  # type: ignore[assignment]
    clear_kill_switch()
    try:
        yield calls
    finally:
        ap._orig_getaddrinfo = saved  # type: ignore[assignment]
        if not was_installed:
            ap.uninstall_airplane_socket_guard()


def _session() -> GuardedSession:
    s = GuardedSession()
    s.trust_env = False  # no proxy from the environment of the machine running the tests
    return s


def test_a_name_that_resolves_to_loopback_is_refused(loopback_server: int, internal_dns: list, monkeypatch):
    """The reproduction. Before the fix this returned the loopback server's body with status 200."""
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    with pytest.raises(ConnectTargetRefused) as excinfo:
        _session().get(f"http://internal.test:{loopback_server}/", timeout=5)
    assert "127.0.0.1" in str(excinfo.value)
    assert "pre-fetch check" not in str(excinfo.value), "a GuardedSession makes no pre-fetch check, so its refusal says none was passed"
    assert internal_dns == ["internal.test"], "the refusal must come from the real lookup through the production hook"
    assert _SEEN == [], "nothing reached the internal service"


def test_a_literal_loopback_address_is_refused_at_connect(loopback_server: int, monkeypatch):
    """The connect check, not the resolution check: a literal address is never looked up by name."""
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    clear_kill_switch()
    with pytest.raises(ConnectTargetRefused) as excinfo:
        _session().get(f"http://127.0.0.1:{loopback_server}/", timeout=5)
    assert _SEEN == []
    assert "when it was checked" not in str(excinfo.value)


def test_the_refusal_is_a_request_exception_and_never_a_connection_error(loopback_server: int, internal_dns: list):
    """Callers handle ``RequestException``; a ``ConnectionError`` would read as a transient failure and be retried."""
    with pytest.raises(requests.RequestException) as excinfo:
        _session().get(f"http://internal.test:{loopback_server}/", timeout=5)
    assert not isinstance(excinfo.value, requests.ConnectionError)
    assert current_scope() is None, "the scope is unwound after a refusal"


def test_the_operator_opt_out_really_opts_out(loopback_server: int, internal_dns: list, monkeypatch):
    """``OO_SSRF_CONNECT_GUARD=0``, the flag the EthicalFetcher reads, stands this guard down too."""
    monkeypatch.setenv("OO_SSRF_CONNECT_GUARD", "0")
    r = _session().get(f"http://internal.test:{loopback_server}/", timeout=5)
    assert r.status_code == 200 and r.content == b"INTERNAL SERVICE SECRET"


def test_a_loopback_proxy_still_works(loopback_server: int, internal_dns: list, monkeypatch):
    """Protected mode's proxy (Tor on 127.0.0.1) is the one non-public endpoint a request is meant to reach: allowed by exact
    address AND port, read from the mapping ``requests`` hands ``send``. The target name is never resolved here, the proxy does it."""
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    proxy = f"http://127.0.0.1:{loopback_server}"
    r = _session().get("http://public.example/page", proxies={"http": proxy, "https": proxy}, timeout=5)
    assert r.status_code == 200
    assert _SEEN == ["http://public.example/page"], "the request really travelled through the proxy"


def test_a_proxy_on_another_loopback_port_does_not_open_the_machine(loopback_server: int, internal_dns: list, monkeypatch):
    """Allowlisting the proxy by address alone would open every port on 127.0.0.1."""
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    proxy = f"http://127.0.0.1:{loopback_server + 1 if loopback_server < 65535 else loopback_server - 1}"
    with pytest.raises(ConnectTargetRefused):
        _session().get(f"http://internal.test:{loopback_server}/", proxies={"https": proxy}, timeout=5)
    assert _SEEN == []


class _RecordingAdapter(requests.adapters.HTTPAdapter):
    """Answers a 302 to another host, then a 200, recording the scope each hop is sent under. Opens no socket."""

    def __init__(self) -> None:
        super().__init__()
        self.scopes: list[object] = []

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        self.scopes.append(current_scope())
        resp = requests.Response()
        resp.request = request
        resp.url = request.url
        resp.raw = None
        if "first" in request.url:
            resp.status_code = 302
            resp.headers["Location"] = "https://second.example/landing"
        else:
            resp.status_code = 200
            resp._content = b"ok"
        return resp


def test_every_redirect_hop_is_sent_inside_a_live_scope(monkeypatch):
    """``requests`` follows a redirect by calling ``Session.send`` again (``resolve_redirects``), so the hop gets its own scope."""
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    clear_kill_switch()
    s = _session()
    adapter = _RecordingAdapter()
    s.mount("https://", adapter)
    r = s.get("https://first.example/", timeout=5)
    assert r.status_code == 200
    assert len(adapter.scopes) == 2
    for scope in adapter.scopes:
        assert scope is not None and getattr(scope, "stood_down", "x") == "", scope
    assert current_scope() is None
