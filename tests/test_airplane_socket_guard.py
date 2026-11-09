"""The socket-level airplane backstop (P0 network-honesty, field test 2026-06-19).

Proves the hard guarantee behind "Not now"/airplane mode: while the global kill
switch is engaged, NO non-loopback socket call is even reached — the guard raises
before delegating to the real ``connect``/``create_connection``/``getaddrinfo``.
Loopback and ``localhost`` always pass through, and the guard is transparent while
online. This is the regression the brief asks for: boot + decline = zero sockets.

Also proves the PROXIED-traffic closure (transversal audit 09, 2026-07-25): a
SOCKS proxy (PySocks) or a plain HTTP CONNECT-tunnel proxy (stdlib ``http.client``)
negotiates the REAL destination at an application-protocol layer the four direct
socket functions above never see — live-reproduced as a real bypass before this
fix. ``test_socks_proxy_destination_is_guarded_before_negotiation`` and
``test_http_connect_tunnel_destination_is_guarded`` pin the closure.
"""

from __future__ import annotations

import contextlib
import http.client
import socket
from pathlib import Path

import pytest

import src.ingest.airplane as ap
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.airplane import (
    AirplaneModeError,
    install_airplane_socket_guard,
    uninstall_airplane_socket_guard,
)


class _Reached(Exception):
    """Raised by a spy when the REAL socket call is reached (should never happen
    for a remote target in airplane mode)."""


@pytest.fixture
def guard():
    """Install the guard with spies standing in for the real socket calls, so a
    test can assert exactly whether the real call was reached. Restores everything."""
    saved = (
        ap._orig_getaddrinfo,
        ap._orig_create_connection,
        ap._orig_connect,
        ap._orig_connect_ex,
        ap._orig_tunnel,
        ap._orig_socks_connect,
        ap._orig_putrequest,
    )
    reached: list[str] = []

    def spy(name):
        def _f(*a, **k):
            reached.append(name)
            raise _Reached(name)  # stop here; we only need to know it was reached

        return _f

    ap._orig_getaddrinfo = spy("getaddrinfo")  # type: ignore[assignment]
    ap._orig_create_connection = spy("create_connection")  # type: ignore[assignment]
    ap._orig_connect = lambda self, address: reached.append("connect")  # type: ignore[assignment]
    ap._orig_connect_ex = lambda self, address: reached.append("connect_ex")  # type: ignore[assignment]
    ap._orig_tunnel = spy("tunnel")  # type: ignore[assignment]
    ap._orig_putrequest = spy("putrequest")  # type: ignore[assignment]
    if ap._orig_socks_connect is not None:
        ap._orig_socks_connect = spy("socks_connect")  # type: ignore[assignment]
    install_airplane_socket_guard()
    clear_kill_switch()
    try:
        yield reached
    finally:
        clear_kill_switch()
        # Restore the captured originals FIRST, so uninstall copies the TRUE stdlib
        # (and PySocks/http.client) calls back (not the spies).
        (
            ap._orig_getaddrinfo,
            ap._orig_create_connection,
            ap._orig_connect,
            ap._orig_connect_ex,
            ap._orig_tunnel,
            ap._orig_socks_connect,
            ap._orig_putrequest,
        ) = saved
        uninstall_airplane_socket_guard()


def test_airplane_blocks_remote_before_any_real_socket_call(guard):
    """The core regression: in airplane mode a remote target raises AirplaneModeError
    and the real socket call is NEVER reached -> zero sockets opened."""
    activate_kill_switch()

    with pytest.raises(AirplaneModeError):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(AirplaneModeError):
        socket.create_connection(("93.184.216.34", 443))  # numeric -> no DNS either
    with pytest.raises(AirplaneModeError):
        s = socket.socket()
        try:
            s.connect(("8.8.8.8", 53))
        finally:
            s.close()

    assert guard == [], "a real socket call was reached while airplane mode was engaged"


def test_loopback_and_localhost_pass_through_even_offline(guard):
    """Loopback and localhost are the app's own server / local LLM / DB — never the
    network — so they delegate to the real call even while offline."""
    activate_kill_switch()

    for host in ("127.0.0.1", "::1", "localhost"):
        # getaddrinfo delegates (our spy raises _Reached, proving we passed the guard).
        with pytest.raises(_Reached):
            socket.getaddrinfo(host, 8000)
    assert set(guard) == {"getaddrinfo"}


def test_guard_is_transparent_when_online(guard):
    """With the kill switch cleared, remote targets delegate straight to the real
    socket calls -- the guard costs nothing during normal collection."""
    clear_kill_switch()
    with pytest.raises(_Reached):
        socket.create_connection(("93.184.216.34", 443))
    with pytest.raises(_Reached):
        socket.getaddrinfo("example.com", 443)
    assert "create_connection" in guard and "getaddrinfo" in guard


def test_unix_sockets_are_local_ipc_and_always_allowed(guard):
    """AF_UNIX is a filesystem path (local IPC), never the network."""
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("AF_UNIX not available on this platform")
    activate_kill_switch()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect("/nonexistent/oo.sock")  # delegates -> spy records, no AirplaneModeError
    except _Reached:
        pass
    finally:
        s.close()
    assert "connect" in guard


def test_boot_path_installs_the_socket_guard():
    """The LIVE boot (run_deferred_startup) must install the backstop, so airplane
    mode is airtight in production -- not only when a test installs it by hand."""
    main_py = (Path(__file__).resolve().parent.parent / "src" / "api" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "install_airplane_socket_guard" in main_py, (
        "the boot path no longer installs the socket-level airplane backstop — "
        "airplane mode would degrade to a per-call convention only"
    )


def test_uninstall_restores_real_socket_calls():
    """After uninstall the stdlib functions are exactly the originals (no residue)."""
    real_gai, real_cc = socket.getaddrinfo, socket.create_connection
    real_conn = socket.socket.connect
    real_tunnel = http.client.HTTPConnection._tunnel
    real_putrequest = http.client.HTTPConnection.putrequest
    install_airplane_socket_guard()
    assert socket.getaddrinfo is not real_gai  # patched
    uninstall_airplane_socket_guard()
    assert socket.getaddrinfo is real_gai
    assert socket.create_connection is real_cc
    assert socket.socket.connect is real_conn
    assert http.client.HTTPConnection._tunnel is real_tunnel
    assert http.client.HTTPConnection.putrequest is real_putrequest


def test_http_connect_tunnel_destination_is_guarded(guard):
    """A plain ``http://`` proxy (Privoxy/other) relays to the REAL destination via
    an HTTP CONNECT handshake sent over an already-established (loopback, guarded)
    proxy socket — the stdlib's own ``_tunnel()`` is the only place that ever sees
    the real target. Regression for the transversal-audit-09 bypass: this must
    raise before the real ``_tunnel()`` (here, the spy) is ever reached, and
    without needing a live socket at all (``self.sock`` is never touched)."""
    activate_kill_switch()
    conn = http.client.HTTPConnection("127.0.0.1", 9999)  # never actually connected
    conn.set_tunnel("example.com", 443)
    with pytest.raises(AirplaneModeError):
        conn._tunnel()
    assert guard == [], "the real _tunnel() (spy) was reached in airplane mode"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_http_connect_tunnel_to_a_loopback_target_is_refused_too(guard, host):
    """REVERSED 2026-11-08 (R619, second security read; this test said loopback passed): ``CONNECT localhost:80`` is written to the
    PROXY, and a proxy chained upstream forwards that name like any other -- requests does the same for https://localhost through an
    HTTP proxy. In airplane mode every tunnel is refused; the direct-connect loopback exemption is untouched."""
    activate_kill_switch()
    conn = http.client.HTTPConnection("127.0.0.1", 9999)
    conn.set_tunnel(host, 8000)
    with pytest.raises(AirplaneModeError):
        conn._tunnel()
    assert guard == [], "the real _tunnel() (spy) was reached for a loopback tunnel host in airplane mode"


def test_http_connect_tunnel_transparent_when_online(guard):
    """With the kill switch cleared, a CONNECT tunnel to a remote target delegates
    straight through — the guard costs nothing during normal (proxied) collection."""
    clear_kill_switch()
    conn = http.client.HTTPConnection("127.0.0.1", 9999)
    conn.set_tunnel("example.com", 443)
    with pytest.raises(_Reached):
        conn._tunnel()
    assert "tunnel" in guard


def test_socks_proxy_destination_is_guarded_before_negotiation(guard):
    """The transversal-audit-09 live-reproduced bypass: PySocks' ``socksocket.
    connect()`` negotiates the real destination via ``sendall()`` at the SOCKS
    application layer, invisible to the four direct socket patches. This must
    raise before that negotiation — and before the real proxy TCP connect (here,
    the spy) — is ever reached, so no connection to the proxy is even attempted."""
    pysocks = pytest.importorskip("socks")
    activate_kill_switch()
    s = pysocks.socksocket()
    s.set_proxy(pysocks.SOCKS5, "127.0.0.1", 9050)  # never actually reached
    with pytest.raises(AirplaneModeError):
        s.connect(("example.com", 80))
    assert guard == [], "PySocks' real connect() (spy) was reached in airplane mode"


def test_socks_proxy_loopback_target_is_refused_too(guard):
    """REVERSED 2026-11-08 (R619): through a SOCKS proxy a loopback destination is the proxy's to reach, so it is refused offline
    like the CONNECT tunnel above. A socksocket with NO proxy set is a plain socket, and loopback stays local there."""
    pysocks = pytest.importorskip("socks")
    activate_kill_switch()
    s = pysocks.socksocket()
    s.set_proxy(pysocks.SOCKS5, "127.0.0.1", 9050)
    with pytest.raises(AirplaneModeError):
        s.connect(("localhost", 8000))
    assert guard == []
    plain = pysocks.socksocket()
    with pytest.raises(_Reached):
        plain.connect(("127.0.0.1", 8000))
    assert "socks_connect" in guard


def test_socks_proxy_transparent_when_online(guard):
    """With the kill switch cleared, a SOCKS-proxied connection to a remote target
    delegates straight through to PySocks' real connect — zero overhead online."""
    pysocks = pytest.importorskip("socks")
    clear_kill_switch()
    s = pysocks.socksocket()
    s.set_proxy(pysocks.SOCKS5, "127.0.0.1", 9050)
    with pytest.raises(_Reached):
        s.connect(("example.com", 80))
    assert "socks_connect" in guard


def test_a_real_call_written_back_over_the_guard_is_patched_again(guard):
    """``_installed`` True with the stdlib's own ``getaddrinfo`` standing in ``socket`` is a guard that is gone while its flag says it is
    there: a ``monkeypatch`` undo that recorded the real call BEFORE the install writes it back over our wrapper (tests/test_dns_proxy_guard.py
    did, and DNS was unguarded for every later test of the worker; production code that ever wrote the real call back would do the same).
    The next install patches it again, for each of the calls, and airplane mode refuses by name once more."""
    real_gai, real_cc, real_conn = socket.getaddrinfo, socket.create_connection, socket.socket.connect
    socket.getaddrinfo = ap._REAL_AT_IMPORT[0]  # type: ignore[assignment]
    socket.create_connection = ap._REAL_AT_IMPORT[1]  # type: ignore[assignment]
    socket.socket.connect = ap._REAL_AT_IMPORT[2]  # type: ignore[assignment]
    try:
        assert ap.is_installed()
        ap.ensure_connect_guard_installed()
        assert socket.getaddrinfo is ap._guarded_getaddrinfo
        assert socket.create_connection is ap._guarded_create_connection
        assert socket.socket.connect is ap._guarded_connect
        activate_kill_switch()
        with pytest.raises(AirplaneModeError):
            socket.getaddrinfo("example.com", 443)
        assert guard == [], "the real getaddrinfo must never be reached under airplane mode"
    finally:
        socket.getaddrinfo, socket.create_connection, socket.socket.connect = real_gai, real_cc, real_conn  # type: ignore[method-assign,assignment]


def test_a_stand_in_standing_where_the_guard_was_is_not_overwritten(guard):
    """Only the REAL call is replaced: a test's deliberate stand-in (the dns-proxy tests resolve through one) keeps its place."""
    real_gai = socket.getaddrinfo

    def stand_in(host, *a, **k):
        return []

    socket.getaddrinfo = stand_in  # type: ignore[assignment]
    try:
        ap.ensure_connect_guard_installed()
        assert socket.getaddrinfo is stand_in
    finally:
        socket.getaddrinfo = real_gai  # type: ignore[assignment]


def test_the_monkeypatch_order_that_left_dns_unguarded_is_healed_by_the_next_install(monkeypatch):
    """The leak exactly as found (tests/test_dns_proxy_guard.py): ``monkeypatch.setattr`` records the REAL ``getaddrinfo``, the first fetch of the
    process then installs the guard OVER the stand-in, and the undo writes the recorded real call back over the guard. ``_installed`` stays
    True; before the heal in ``_install_patches`` the next ``install_airplane_socket_guard`` was a no-op and ``test_egress_window`` reached the
    real resolver."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    uninstall_airplane_socket_guard()
    real = socket.getaddrinfo
    try:
        with monkeypatch.context() as mp:
            mp.setattr(socket, "getaddrinfo", lambda *a, **k: [])
            ap.ensure_connect_guard_installed()
        assert ap.is_installed() and socket.getaddrinfo is real  # the state the leak left behind
        install_airplane_socket_guard()
        assert socket.getaddrinfo is ap._guarded_getaddrinfo
    finally:
        uninstall_airplane_socket_guard()
        if was_installed:
            ap.ensure_connect_guard_installed()
        ap._airplane_armed = was_armed


def test_a_patch_point_that_cannot_be_read_is_left_alone_not_healed(guard, monkeypatch):
    """A private attribute a newer Python renamed (``HTTPConnection._tunnel``) reads as absent. That point is neither the real call nor a
    stand-in, so the check names nothing for it and the install does not raise or write a wrapper over a name that is not there."""
    monkeypatch.delattr(http.client.HTTPConnection, "_tunnel")
    assert ap.removed_while_installed() == []
    ap._install_patches()
    assert not hasattr(http.client.HTTPConnection, "_tunnel")


# --------------------------------------------------------------------------- #
# R619: a plain http:// URL through a LOOPBACK HTTP proxy (Privoxy -> Tor). The
# client writes an absolute-form ``GET http://host/x`` to the allowed loopback
# proxy socket and never sends CONNECT, so neither the connect guard nor
# ``_tunnel`` sees the real destination. Live-reproduced first: a loopback
# listener standing in for the proxy received the full request in airplane mode.
# --------------------------------------------------------------------------- #


def test_absolute_form_request_target_is_guarded_before_putrequest(guard):
    """The unit half: the real ``putrequest`` (a spy here) is never reached, in airplane mode, for ANY target that names its own
    destination -- whatever host it names, loopback included, since a proxy chained upstream forwards ``localhost`` too -- nor for the
    shapes a parser could read differently from a proxy (both security reads and the Opus read, 2026-11-08). Only origin-form, ``*`` and
    the empty target reach it."""
    activate_kill_switch()
    conn = http.client.HTTPConnection("127.0.0.1", 8118)
    named: list[tuple[str, str | bytes]] = [
        ("GET", "http://example.com/x"),
        ("GET", "HTTP://EXAMPLE.COM:80/"),
        ("GET", b"http://93.184.216.34/"),
        ("GET", "http://[2606:2800:220:1::]/"),
        ("GET", "http://localhost@example.com/"),
        ("GET", "http://localhost\\@example.com/"),
        ("GET", "http://127.0.0.1?@example.com/"),
        ("GET", "http://127.0.0.1#@example.com/"),
        ("GET", "http://127.0.0.1%25.example.com/"),
        ("GET", "http://[::1]example.com/"),
        ("GET", "http://:80/"),
        # Loopback names and literals are refused too: Privoxy with forward-socks5t hands them upstream like any other name.
        ("GET", "http://localhost/"),
        ("GET", "http://localhost.localdomain/"),
        ("GET", "http://127.0.0.1:8000/x"),
        ("GET", "http://[::1]/"),
        # The shapes a "scheme://" rule missed (second security read).
        ("GET", "//example.com/x"),
        ("GET", "example.com:80"),
        ("GET", "http:/example.com/"),
        ("GET", "http:example.com/"),
        ("CONNECT", "example.com:443"),
        ("CONNECT ", "example.com:443"),
        ("connect", "127.0.0.1:9050"),
        # A method that is not an RFC 7230 token carries a target of its own: "GET http://evil.com / HTTP/1.1".
        ("GET http://example.com", "/"),
        ("GET\x7f", "/"),
        ("G\tET", "/"),
    ]
    for method, target in named:
        with pytest.raises(AirplaneModeError):
            conn.putrequest(method, target)  # type: ignore[arg-type]  # bytes is what a client may hand it; typeshed says str
    assert guard == [], "the real putrequest was reached for a target naming its own destination in airplane mode"
    for method, target in [("GET", "/x"), ("OPTIONS", "*"), ("GET", "/"), ("GET", "")]:
        with pytest.raises(_Reached):
            conn.putrequest(method, target)
    assert guard == ["putrequest"] * 4


def test_the_refusal_names_no_part_of_the_target(guard):
    """The target can carry userinfo or a signed query string (R142): the refusal says it was a proxied request line and quotes none of it."""
    activate_kill_switch()
    conn = http.client.HTTPConnection("127.0.0.1", 8118)
    with pytest.raises(AirplaneModeError) as exc:
        conn.putrequest("GET", "http://user:secret@example.com/x?sig=abc")
    assert "secret" not in str(exc.value) and "sig=abc" not in str(exc.value) and "example.com" not in str(exc.value)
    assert "airplane mode is engaged" in str(exc.value)


def test_absolute_form_request_target_transparent_when_online(guard):
    conn = http.client.HTTPConnection("127.0.0.1", 8118)
    with pytest.raises(_Reached):
        conn.putrequest("GET", "http://example.com/x")
    assert guard == ["putrequest"]


class _Listener:
    """A loopback TCP listener standing in for an HTTP proxy: it records every byte any connection sends it."""

    def __init__(self) -> None:
        import threading

        self.received = bytearray()
        self.accepted = 0
        self._srv = socket.socket()
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self._srv.settimeout(0.2)
        self.port = self._srv.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                c, _ = self._srv.accept()
            except OSError:
                continue
            self.accepted += 1
            c.settimeout(0.5)
            try:
                while chunk := c.recv(65536):
                    self.received += chunk
                    if b"\r\n\r\n" in self.received:
                        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
                        break
            except OSError:
                pass
            finally:
                c.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self._srv.close()


@pytest.fixture
def proxy_listener(monkeypatch):
    """The REAL guard (no spies: the bytes must really not be written) plus a loopback listener; the guard's prior state is put back.

    ``no_proxy`` is cleared: both clients honour it, and a runner whose ``no_proxy`` covers the target would go DIRECT, making the
    airplane test pass on the connect guard instead of this one and the online control fetch example.com for real."""
    for name in ("no_proxy", "NO_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    install_airplane_socket_guard()
    clear_kill_switch()
    listener = _Listener()
    try:
        yield listener
    finally:
        clear_kill_switch()
        listener.close()
        uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()  # not ensure_connect_guard_installed: that is a no-op under OO_SSRF_CONNECT_GUARD=0
        ap._airplane_armed = was_armed


def _fetch_with_requests(port: int) -> object:
    import requests

    with requests.Session() as session:
        session.trust_env = False  # the proxy below and nothing from the environment
        return session.get("http://example.com/x", proxies={"http": f"http://127.0.0.1:{port}"}, timeout=2)


def _fetch_with_urllib(port: int) -> object:
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}"}))
    with opener.open("http://example.com/x", timeout=2) as r:
        return r.read()


@pytest.mark.parametrize("fetch", [_fetch_with_requests, _fetch_with_urllib], ids=["requests", "urllib"])
def test_no_byte_reaches_a_loopback_http_proxy_in_airplane_mode(proxy_listener, fetch):
    """The guarantee itself, end to end: with airplane mode engaged, a plain http:// fetch through a loopback HTTP proxy leaves ZERO bytes
    at the proxy, through both http.client-based clients the tree uses. The refusal is the named airplane one, wherever the client wraps it."""
    activate_kill_switch()
    with pytest.raises(Exception) as exc:
        fetch(proxy_listener.port)
    assert "airplane mode is engaged" in str(exc.value) or isinstance(exc.value, AirplaneModeError)
    clear_kill_switch()
    proxy_listener.close()
    assert bytes(proxy_listener.received) == b"", "the loopback proxy received request bytes while airplane mode was engaged"


@pytest.mark.parametrize("target", ["http://localhost.localdomain/", "http://127.0.0.1?@example.com/", "http://127.0.0.1%25.example.com/"])
def test_a_loopback_looking_target_through_the_proxy_is_refused_too(proxy_listener, target):
    """The Opus read's repro, end to end through urllib (which passes the URL through untouched): a target that reads as loopback, or
    that a parser could read as loopback, still leaves zero bytes at the proxy in airplane mode."""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{proxy_listener.port}"}))
    activate_kill_switch()
    with pytest.raises(Exception, match="airplane mode is engaged"):
        opener.open(target, timeout=2)
    clear_kill_switch()
    proxy_listener.close()
    assert bytes(proxy_listener.received) == b""


@pytest.mark.parametrize("fetch", [_fetch_with_requests, _fetch_with_urllib], ids=["requests", "urllib"])
def test_the_listener_does_see_the_request_while_online(proxy_listener, fetch):
    """The control that makes the zero above mean something: online, the same fetch DOES deliver the absolute-form request to the listener."""
    fetch(proxy_listener.port)
    proxy_listener.close()
    assert bytes(proxy_listener.received).startswith(b"GET http://example.com/x HTTP/1.1\r\n")


def test_without_the_putrequest_patch_the_bytes_arrive(proxy_listener):
    """Remove the guard, a test fails: with ``putrequest`` put back to the real call, airplane mode lets the absolute-form request through
    to the proxy -- the bypass as found. This is what the zero-bytes test above is pinning."""
    http.client.HTTPConnection.putrequest = ap._orig_putrequest  # type: ignore[method-assign]
    try:
        activate_kill_switch()
        with contextlib.suppress(Exception):  # only the bytes matter here
            _fetch_with_requests(proxy_listener.port)
        clear_kill_switch()
        proxy_listener.close()
        assert bytes(proxy_listener.received).startswith(b"GET http://example.com/x HTTP/1.1\r\n")
    finally:
        http.client.HTTPConnection.putrequest = ap._guarded_putrequest  # type: ignore[method-assign]


# --------------------------------------------------------------------------- #
# R639: in airplane mode a lookup is made only for "localhost" and loopback LITERALS. A localhost alias the connect guard treats as
# local (localhost.localdomain, ip6-localhost) is resolved from /etc/hosts only where that file lists it; elsewhere the resolver asks
# DNS, so the query itself egressed (security read A of R638). The resolver here is the fixture's spy: no real lookup is made.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("host", ["localhost.localdomain", "ip6-localhost", "LOCALHOST.LOCALDOMAIN", "localhost.", " localhost", "[::1]"])
def test_a_localhost_alias_is_not_looked_up_in_airplane_mode(guard, host):
    activate_kill_switch()
    with pytest.raises(AirplaneModeError) as exc:
        socket.getaddrinfo(host, 80)
    assert guard == [], f"the resolver was reached for {host!r} in airplane mode"
    assert "airplane mode is engaged" in str(exc.value)


def test_an_alias_refusal_is_in_fixed_words(guard):
    activate_kill_switch()
    with pytest.raises(AirplaneModeError) as exc:
        socket.getaddrinfo("ip6-localhost", 80)
    assert str(exc.value).startswith("airplane mode is engaged: refusing a network connection to ")
    assert ap._ALIAS_LOOKUP_TARGET in str(exc.value) and "ip6-localhost" not in str(exc.value)


@pytest.mark.parametrize("host", ["example.com", "intranet", "a.example"])
def test_a_plain_name_is_refused_before_any_lookup_with_the_sentence_callers_parse(guard, host):
    """A plain name was already refused before the lookup; its sentence (which the offline readers parse) is unchanged."""
    activate_kill_switch()
    with pytest.raises(AirplaneModeError) as exc:
        socket.getaddrinfo(host, 80)
    assert guard == []
    assert f"refusing a network connection to {host!r}" in str(exc.value)


@pytest.mark.parametrize("host", [None, "", "localhost", "LocalHost", "127.0.0.1", "127.8.9.10", "::1", "::1%lo", b"localhost"])
def test_localhost_and_loopback_literals_are_still_looked_up(guard, host):
    activate_kill_switch()
    with pytest.raises(_Reached):
        socket.getaddrinfo(host, 80)
    assert guard == ["getaddrinfo"]


def test_a_localhost_alias_is_looked_up_while_online(guard):
    with pytest.raises(_Reached):
        socket.getaddrinfo("localhost.localdomain", 80)
    assert guard == ["getaddrinfo"]


def test_lookup_exemption_is_narrower_than_the_connect_classification():
    """Every name exempt from a lookup is local, and the aliases are local to connect but NOT exempt from a lookup."""
    for host in (None, "", "localhost", "127.0.0.1", "::1"):
        assert ap._lookup_exempt(host) and ap._is_local_host(host)
    for host in ("localhost.localdomain", "ip6-localhost", " localhost", "[::1]"):
        assert ap._is_local_host(host) and not ap._lookup_exempt(host)


def test_localhost_is_answered_from_its_literals_in_airplane_mode(guard):
    """Exactly ``localhost`` is resolved from 127.0.0.1 / ::1, never handed to libc as a NAME, so a hosts file without an entry for the
    family asked for cannot send the query to DNS (security read A's follow-up on R639). Online, the name is resolved as before."""
    seen: list[object] = []

    def resolver(host, *a, **k):
        seen.append((host, a[1] if len(a) > 1 else k.get("family", 0)))
        if host == "::1":
            raise socket.gaierror(socket.EAI_ADDRFAMILY, "no IPv6 here")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, a[0] if a else 0))]

    ap._orig_getaddrinfo = resolver  # type: ignore[assignment]
    activate_kill_switch()
    assert socket.getaddrinfo("LOCALHOST", 80)[0][4] == ("127.0.0.1", 80)
    socket.getaddrinfo(b"localhost", 80, socket.AF_INET)
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("localhost", 80, socket.AF_INET6)  # no usable ::1: the resolver's own error, no name lookup
    assert all(host in ("127.0.0.1", "::1") for host, _family in seen), seen
    assert seen == [("127.0.0.1", 0), ("::1", 0), ("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)]
    clear_kill_switch()
    seen.clear()
    socket.getaddrinfo("localhost", 80)
    assert seen == [("localhost", 0)]


# --------------------------------------------------------------------------- #
# R639, S1's read: connect()/connect_ex() with a host NAME resolve it in CPython's C code, straight through libc, never through the
# patched getaddrinfo. In airplane mode connect(("localhost.localdomain", 80)) sent a DNS query (strace), and so did "localhost" on an
# AF_INET6 socket where /etc/hosts has no ::1 line. The connect guards now apply the getaddrinfo rule before the real call.
# --------------------------------------------------------------------------- #


@pytest.fixture
def connect_spy(guard):
    """The real connect/connect_ex replaced by recorders of the address they were handed (the guard fixture's spies record no address).
    Put back before the guard fixture restores the real calls, so nothing outlives the test."""
    handed: list[object] = []
    saved = ap._orig_connect, ap._orig_connect_ex
    ap._orig_connect = lambda self, address: handed.append(address)  # type: ignore[assignment]
    ap._orig_connect_ex = lambda self, address: handed.append(address) or 0  # type: ignore[assignment]
    try:
        yield handed
    finally:
        ap._orig_connect, ap._orig_connect_ex = saved


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
@pytest.mark.parametrize("host", ["localhost.localdomain", "ip6-localhost", " localhost"])
def test_connect_to_a_localhost_alias_is_refused_in_airplane_mode(connect_spy, method, host):
    activate_kill_switch()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(AirplaneModeError) as exc:
            getattr(s, method)((host, 80))
    finally:
        s.close()
    assert connect_spy == [], "the real connect (and so libc's resolver) was reached for a localhost alias"
    assert ap._ALIAS_LOOKUP_TARGET in str(exc.value) and repr(host) not in str(exc.value)


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
@pytest.mark.parametrize(("family", "literal"), [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")])
def test_connect_to_localhost_is_handed_the_literal_of_the_sockets_family(connect_spy, method, family, literal):
    activate_kill_switch()
    try:
        s = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        pytest.skip("this host cannot create a socket of that family")
    try:
        getattr(s, method)(("LocalHost", 8000))
    finally:
        s.close()
    assert connect_spy == [(literal, 8000)]


def test_connect_names_are_untouched_while_online(connect_spy):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("localhost", 8000))
        s.connect(("localhost.localdomain", 8000))
    finally:
        s.close()
    assert connect_spy == [("localhost", 8000), ("localhost.localdomain", 8000)]


def test_create_connection_to_a_localhost_alias_is_refused_before_anything(guard):
    activate_kill_switch()
    with pytest.raises(AirplaneModeError) as exc:
        socket.create_connection(("ip6-localhost", 80))
    assert guard == [] and ap._ALIAS_LOOKUP_TARGET in str(exc.value)


def test_a_real_loopback_server_is_reached_by_name_in_airplane_mode():
    """End to end, real guard: a listener on 127.0.0.1 is reached through connect(("localhost", port)) with the switch engaged."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    install_airplane_socket_guard()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        activate_kill_switch()
        c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            c.settimeout(2)
            c.connect(("localhost", srv.getsockname()[1]))
            assert c.getpeername()[0] == "127.0.0.1"
        finally:
            c.close()
    finally:
        clear_kill_switch()
        srv.close()
        uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed
