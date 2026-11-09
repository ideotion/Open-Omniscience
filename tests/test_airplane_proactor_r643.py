"""R643: on Windows the stdlib proactor loop's ConnectEx/WSAConnect and WSASendTo meet airplane mode's connect and datagram rules.

``loop="asyncio"`` gives the proactor on win32. Its ``IocpProactor.connect`` and ``sendto`` hand the address straight to
``_overlapped``, past ``socket.socket.connect``/``sendto``, and an IP-literal target skips ``getaddrinfo`` too. Both are patch points
now. The class exists only on Windows, so these tests drive the wrappers with a stand-in proactor (``_overlapped`` is never touched)
and, on Windows alone, the real loop with the overlapped call replaced by a tripwire. No real network anywhere.
"""

from __future__ import annotations

import asyncio
import socket
import sys

import pytest

import src.ingest.airplane as ap
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.airplane import AirplaneModeError


class _Conn:
    """A socket stand-in carrying only what the wrappers read."""

    def __init__(self, family=socket.AF_INET, type_=socket.SOCK_STREAM):
        self.family = family
        self.type = type_


@pytest.fixture
def proactor(monkeypatch):
    """The guard armed, with recorders standing in for the overlapped entry points. Returns the calls they saw."""
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(ap, "_orig_proactor_connect", lambda self, conn, address: calls.append(("connect", address)) or "fut")
    monkeypatch.setattr(
        ap, "_orig_proactor_sendto", lambda self, conn, buf, flags=0, addr=None: calls.append(("sendto", addr)) or "fut"
    )
    monkeypatch.setattr(ap, "_airplane_armed", True)
    clear_kill_switch()
    try:
        yield calls
    finally:
        clear_kill_switch()


_REMOTE = [("93.184.215.14", 443), ("2606:2800:21f:cb07:6820:80da:af6b:8b2c", 443, 0, 0), ("example.com", 443)]
_ALIASES = [("localhost.localdomain", 80), ("ip6-localhost", 80)]


@pytest.mark.parametrize("type_", [socket.SOCK_STREAM, socket.SOCK_DGRAM])
@pytest.mark.parametrize("address", _REMOTE + _ALIASES)
def test_a_remote_or_alias_connect_is_refused_before_the_overlapped_call(proactor, address, type_):
    """ConnectEx for a stream and WSAConnect for a datagram socket both go through IocpProactor.connect."""
    activate_kill_switch()
    with pytest.raises(AirplaneModeError):
        ap._guarded_proactor_connect(object(), _Conn(type_=type_), address)
    assert proactor == []


@pytest.mark.parametrize(
    ("family", "address", "handed"),
    [
        (socket.AF_INET, ("127.0.0.1", 8000), ("127.0.0.1", 8000)),
        (socket.AF_INET6, ("::1", 8000, 0, 0), ("::1", 8000, 0, 0)),
        (socket.AF_INET, ("localhost", 8000), ("127.0.0.1", 8000)),
        (socket.AF_INET6, ("localhost", 8000, 0, 0), ("::1", 8000, 0, 0)),
    ],
)
def test_a_loopback_connect_reaches_the_overlapped_call(proactor, family, address, handed):
    activate_kill_switch()
    assert ap._guarded_proactor_connect(object(), _Conn(family=family), address) == "fut"
    assert proactor == [("connect", handed)]


def test_online_a_connect_is_untouched(proactor):
    ap._guarded_proactor_connect(object(), _Conn(), ("93.184.215.14", 443))
    assert proactor == [("connect", ("93.184.215.14", 443))]


def test_a_proactor_connect_meets_the_ssrf_connect_check(proactor, monkeypatch):
    """Online, the address handed to ConnectEx still goes through the connect-time SSRF check (security read A: removing the call left
    every test green). The check acts only inside a guarded fetch; here a recorder stands in for it."""
    checked: list[object] = []
    monkeypatch.setattr(ap, "check_connect_target", lambda address: checked.append(address))
    ap._guarded_proactor_connect(object(), _Conn(), ("93.184.215.14", 443))
    assert checked == [("93.184.215.14", 443)]
    assert proactor == [("connect", ("93.184.215.14", 443))]


@pytest.mark.parametrize("address", _REMOTE + _ALIASES)
def test_a_remote_or_alias_datagram_is_refused_before_wsasendto(proactor, address):
    activate_kill_switch()
    conn = _Conn(type_=socket.SOCK_DGRAM)
    with pytest.raises(AirplaneModeError):
        ap._guarded_proactor_sendto(object(), conn, b"x", 0, address)  # loop.sock_sendto
    with pytest.raises(AirplaneModeError):
        ap._guarded_proactor_sendto(object(), conn, b"x", addr=address)  # the datagram transport
    assert proactor == []


def test_a_loopback_or_connected_datagram_reaches_wsasendto(proactor):
    activate_kill_switch()
    conn = _Conn(type_=socket.SOCK_DGRAM)
    ap._guarded_proactor_sendto(object(), conn, b"x", 0, ("127.0.0.1", 9))
    ap._guarded_proactor_sendto(object(), conn, b"x", addr=("localhost", 9))
    ap._guarded_proactor_sendto(object(), conn, b"x")  # connected: no address, its connect met the rule
    assert proactor == [("sendto", ("127.0.0.1", 9)), ("sendto", ("127.0.0.1", 9)), ("sendto", None)]


def test_online_a_datagram_is_untouched(proactor):
    ap._guarded_proactor_sendto(object(), _Conn(type_=socket.SOCK_DGRAM), b"x", 0, ("93.184.215.14", 9))
    assert proactor == [("sendto", ("93.184.215.14", 9))]


def test_the_refusal_is_an_oserror_so_the_transport_reports_it():
    """The datagram transport catches OSError from ``proactor.sendto`` and hands it to ``protocol.error_received``."""
    assert issubclass(AirplaneModeError, OSError)


def test_the_proactor_is_a_patch_point_installed_healed_and_put_back(monkeypatch):
    """With a stand-in IocpProactor in place of the Windows-only class: install patches both methods, a removal while installed is
    healed, and an uninstall puts the real ones back."""

    class _FakeProactor:
        def connect(self, conn, address):
            return "real-connect"

        def sendto(self, conn, buf, flags=0, addr=None):
            return "real-sendto"

    real_connect, real_sendto = _FakeProactor.connect, _FakeProactor.sendto
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    ap.uninstall_airplane_socket_guard()
    monkeypatch.setattr(ap, "_proactor_cls", _FakeProactor)
    monkeypatch.setattr(ap, "_orig_proactor_connect", real_connect)
    monkeypatch.setattr(ap, "_orig_proactor_sendto", real_sendto)
    # On win32 the module's own tuple already ends with the real IocpProactor pair: replace it rather than append (security read A).
    # Elsewhere the pair is absent and is added, last, where the optional points go.
    real_at_import = ap._REAL_AT_IMPORT[:-2] if sys.platform == "win32" else ap._REAL_AT_IMPORT
    monkeypatch.setattr(ap, "_REAL_AT_IMPORT", (*real_at_import, real_connect, real_sendto))
    try:
        assert len(ap._patch_points()) == len(ap._REAL_AT_IMPORT) == len(ap._standing_calls())
        assert ap.install_airplane_socket_guard()
        assert _FakeProactor.connect is ap._guarded_proactor_connect
        assert _FakeProactor.sendto is ap._guarded_proactor_sendto
        _FakeProactor.connect = real_connect  # type: ignore[method-assign]
        assert (_FakeProactor, "connect", ap._guarded_proactor_connect) in ap.removed_while_installed()
        ap._install_patches()
        assert _FakeProactor.connect is ap._guarded_proactor_connect
        ap.uninstall_airplane_socket_guard()
        assert _FakeProactor.connect is real_connect and _FakeProactor.sendto is real_sendto
    finally:
        ap.uninstall_airplane_socket_guard()
        monkeypatch.undo()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


def test_the_points_exist_exactly_where_the_class_does():
    has = sys.modules.get("asyncio.windows_events") is not None and hasattr(sys.modules["asyncio.windows_events"], "IocpProactor")
    assert (ap._orig_proactor_connect is not None) == has == (sys.platform == "win32")
    if has:  # the real pair closes the import-time tuple, last, where the optional points go
        assert ap._REAL_AT_IMPORT[-2:] == (ap._orig_proactor_connect, ap._orig_proactor_sendto)


@pytest.mark.skipif(sys.platform != "win32", reason="the real proactor loop exists only on Windows")
def test_the_real_proactor_loop_refuses_a_literal_connect_before_connectex():
    """On Windows, the REAL loop: ``sock_connect`` to an IP literal goes to IocpProactor.connect (never getaddrinfo, never
    socket.connect). The overlapped entry point is a tripwire, so a broken guard fails here without reaching the network."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    assert ap.install_airplane_socket_guard()
    saved = ap._orig_proactor_connect

    def _tripwire(*a, **k):
        raise AssertionError("ConnectEx was reached")

    ap._orig_proactor_connect = _tripwire
    loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined,unused-ignore]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        activate_kill_switch()
        with pytest.raises(AirplaneModeError):
            loop.run_until_complete(loop.sock_connect(sock, ("192.0.2.1", 443)))
    finally:
        clear_kill_switch()
        sock.close()
        loop.close()
        ap._orig_proactor_connect = saved
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed
