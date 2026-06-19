"""The socket-level airplane backstop (P0 network-honesty, field test 2026-06-19).

Proves the hard guarantee behind "Not now"/airplane mode: while the global kill
switch is engaged, NO non-loopback socket call is even reached — the guard raises
before delegating to the real ``connect``/``create_connection``/``getaddrinfo``.
Loopback and ``localhost`` always pass through, and the guard is transparent while
online. This is the regression the brief asks for: boot + decline = zero sockets.
"""

from __future__ import annotations

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
    saved = (ap._orig_getaddrinfo, ap._orig_create_connection, ap._orig_connect, ap._orig_connect_ex)
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
    install_airplane_socket_guard()
    clear_kill_switch()
    try:
        yield reached
    finally:
        clear_kill_switch()
        # Restore the captured originals FIRST, so uninstall copies the TRUE stdlib
        # calls back into socket.* (not the spies).
        (ap._orig_getaddrinfo, ap._orig_create_connection, ap._orig_connect, ap._orig_connect_ex) = saved
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
    install_airplane_socket_guard()
    assert socket.getaddrinfo is not real_gai  # patched
    uninstall_airplane_socket_guard()
    assert socket.getaddrinfo is real_gai
    assert socket.create_connection is real_cc
    assert socket.socket.connect is real_conn
