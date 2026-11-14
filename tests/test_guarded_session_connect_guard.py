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
import os
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


# --------------------------------------------------------------------------- #
# the two security reads of 2026-11-14: only the proxy the request uses counts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("variable", ["ftp_proxy", "npm_config_proxy", "yarn_https_proxy", "HTTPS_PROXY"])
def test_a_hostname_proxy_this_request_does_not_use_cannot_stand_the_guard_down(
    loopback_server: int, internal_dns: list, monkeypatch, variable: str
):
    """With ``trust_env`` on (``guarded_session``'s default), the merged mapping holds every ``*_proxy`` variable. One naming a HOST
    stood the whole check down, though this plain-http request goes direct: the loopback body came back as a 200 (both reads)."""
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    for name in [n for n in os.environ if n.lower().endswith("_proxy")]:  # the machine's own, which would win over the one set here
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(variable, "http://proxy.invalid:3128")
    s = GuardedSession()
    assert s.trust_env
    with pytest.raises(ConnectTargetRefused):
        s.get(f"http://internal.test:{loopback_server}/", timeout=5)
    assert _SEEN == []


def test_a_loopback_proxy_for_the_other_scheme_does_not_open_its_port_to_a_direct_request(loopback_server: int, monkeypatch):
    """The proxy's exact address and port are allowed only for a request that goes THROUGH it."""
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    clear_kill_switch()
    proxy = f"http://127.0.0.1:{loopback_server}"
    with pytest.raises(ConnectTargetRefused):
        _session().get(f"http://127.0.0.1:{loopback_server}/", proxies={"https": proxy}, timeout=5)
    assert _SEEN == []


def test_gethostbyname_answers_are_checked_inside_a_scope(monkeypatch):
    """PySocks resolves a ``socks4://`` destination with ``socket.gethostbyname`` and hands the ADDRESS to the proxy, so the only
    socket opened is the allowed one to the proxy: that lookup is the one place the destination is visible (read A, SHOULD-FIX 2)."""
    from src.ingest.ssrf_guard import BlockedConnectTarget, connect_scope

    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    was_installed = ap.is_installed()
    saved, saved_ex = ap._orig_gethostbyname, ap._orig_gethostbyname_ex
    ap._orig_gethostbyname = lambda host: "127.0.0.1" if host == "internal.test" else "93.184.216.34"  # type: ignore[assignment]
    ap._orig_gethostbyname_ex = lambda host: (host, [], ["127.0.0.1"] if host == "internal.test" else ["93.184.216.34"])  # type: ignore[assignment]
    ap.ensure_connect_guard_installed()
    try:
        with connect_scope(enabled=True, prechecked=False):
            with pytest.raises(BlockedConnectTarget):
                socket.gethostbyname("internal.test")
            with pytest.raises(BlockedConnectTarget):
                socket.gethostbyname_ex("internal.test")
            assert socket.gethostbyname("public.test") == "93.184.216.34"
        assert socket.gethostbyname("internal.test") == "127.0.0.1"  # outside a scope nothing is checked
    finally:
        ap._orig_gethostbyname, ap._orig_gethostbyname_ex = saved, saved_ex  # type: ignore[assignment]
        if not was_installed:
            ap.uninstall_airplane_socket_guard()
