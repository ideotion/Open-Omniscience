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
    install_airplane_socket_guard()
    assert socket.getaddrinfo is not real_gai  # patched
    uninstall_airplane_socket_guard()
    assert socket.getaddrinfo is real_gai
    assert socket.create_connection is real_cc
    assert socket.socket.connect is real_conn
    assert http.client.HTTPConnection._tunnel is real_tunnel


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


def test_http_connect_tunnel_loopback_target_passes_through(guard):
    """Tunnelling to a loopback target (the app's own server via a local relay)
    is still allowed offline, mirroring the direct-connect loopback exemption."""
    activate_kill_switch()
    conn = http.client.HTTPConnection("127.0.0.1", 9999)
    conn.set_tunnel("127.0.0.1", 8000)
    with pytest.raises(_Reached):
        conn._tunnel()
    assert "tunnel" in guard


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


def test_socks_proxy_loopback_target_passes_through(guard):
    """A SOCKS-proxied connection to a loopback target is still allowed offline."""
    pysocks = pytest.importorskip("socks")
    activate_kill_switch()
    s = pysocks.socksocket()
    s.set_proxy(pysocks.SOCKS5, "127.0.0.1", 9050)
    with pytest.raises(_Reached):
        s.connect(("127.0.0.1", 8000))
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
