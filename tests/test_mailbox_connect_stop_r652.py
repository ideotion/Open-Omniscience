"""A Stop cuts a mailbox pull whose TCP connect has stalled, at once (R652).

R647 registered the live socket for the Stop the moment its connect RETURNED, so a server that never answered the connect held the pull
until the timeout. The socket is now created, registered and only then connected, with the switch read while the connect is in progress
(``_connect_watching_stop``); on Linux the Stop's shutdown also aborts the connect itself. POP3's constructor now catches
``_MailboxStopped`` by its type, as IMAP's does. Loopback only: nothing leaves the machine.
"""

from __future__ import annotations

import errno
import socket
import sys
import threading
import time

import pytest

import src.ingest as ingest
import src.ingest.email as email_mod
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.email import MailboxStarttlsError, fetch_imap, fetch_pop3

#: Far below the timeout the stalled tests use and far above a loopback round trip.
_PROMPT_S = 5.0

_FNS = [fetch_imap, fetch_pop3]
_IDS = ["imap", "pop3"]


@pytest.fixture(autouse=True)
def _net():
    clear_kill_switch()
    yield
    clear_kill_switch()


class _StalledListener:
    """A loopback listener whose accept queue is full: Linux drops a further SYN, so a connect to it stays in progress."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(0)
        self.port = self.sock.getsockname()[1]
        self.fillers: list[socket.socket] = []
        for _ in range(8):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            s.connect_ex(("127.0.0.1", self.port))
            self.fillers.append(s)
        time.sleep(0.2)

    def close(self) -> None:
        for s in self.fillers:
            s.close()
        self.sock.close()


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="a full accept queue stalls a loopback connect on Linux only")


def _stop_after(seconds: float) -> threading.Thread:
    t = threading.Thread(target=lambda: (time.sleep(seconds), activate_kill_switch()), daemon=True)
    t.start()
    return t


@linux_only
@pytest.mark.parametrize("fn", _FNS, ids=_IDS)
@pytest.mark.parametrize("use_ssl", [False, True], ids=["plain", "tls"])
def test_a_stop_cuts_a_stalled_tcp_connect_at_once(fn, use_ssl, monkeypatch):
    monkeypatch.setattr(email_mod, "MAILBOX_TIMEOUT_S", 30.0)
    lst = _StalledListener()
    try:
        stopper = _stop_after(0.5)
        t0 = time.monotonic()
        raws = fn("127.0.0.1", "u", "p", use_ssl=use_ssl, port=lst.port)
        took = time.monotonic() - t0
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not cut the stalled connect ({took:.1f} s)"
        assert raws.stopped is True and list(raws) == []
        assert not ingest._LIVE_MAILBOX_SOCKETS, "the connecting socket was left registered"
    finally:
        lst.close()


@linux_only
@pytest.mark.parametrize("fn", _FNS, ids=_IDS)
def test_without_a_stop_a_stalled_connect_meets_the_bounded_timeout(fn, monkeypatch):
    monkeypatch.setattr(email_mod, "MAILBOX_TIMEOUT_S", 0.5)
    lst = _StalledListener()
    try:
        t0 = time.monotonic()
        with pytest.raises(OSError):
            fn("127.0.0.1", "u", "p", use_ssl=False, port=lst.port)
        assert time.monotonic() - t0 < _PROMPT_S
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        lst.close()


def test_the_connect_reads_the_switch_while_it_is_in_progress(monkeypatch):
    """Portable: with the platform never reporting the connect done (here a selector that sees nothing), the Stop still ends it within
    the slice, without relying on the shutdown aborting the connect."""
    lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    calls = {"n": 0}

    class _Blind:
        def register(self, *a):
            pass

        def select(self, timeout):
            calls["n"] += 1
            time.sleep(timeout)
            return []

        def close(self):
            pass

    monkeypatch.setattr(email_mod.selectors, "DefaultSelector", _Blind)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    real_connect_ex = socket.socket.connect_ex
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, a: (real_connect_ex(self, a), errno.EINPROGRESS)[1])  # always "in progress"
    try:
        stopper = _stop_after(0.3)
        t0 = time.monotonic()
        with pytest.raises(email_mod._MailboxStopped):
            email_mod._connect_watching_stop(sock, lst.getsockname(), 30.0)
        stopper.join(5)
        assert time.monotonic() - t0 < 2.0
        assert calls["n"] >= 2
    finally:
        sock.close()
        lst.close()


def _held_registrations(monkeypatch) -> list[socket.socket]:
    """Every socket registered for the Stop, held strongly: the registry is a WeakSet, so a dropped socket would vanish from it and a
    socket left registered could not be seen (security read A on #1899)."""
    held: list[socket.socket] = []
    real = ingest.register_mailbox_socket

    def spy(sock):
        held.append(sock)
        real(sock)

    monkeypatch.setattr(ingest, "register_mailbox_socket", spy)
    return held


def test_a_family_this_kernel_lacks_moves_on_to_the_next_address(monkeypatch):
    """socket.create_connection creates each socket inside its try, so an IPv6 answer on a kernel with IPv6 off falls through to IPv4;
    so does this (security read A on #1899)."""
    good = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    good.bind(("127.0.0.1", 0))
    good.listen(1)
    answers = [
        (12345, socket.SOCK_STREAM, 0, "", ("nowhere", 0)),  # a family no kernel offers: socket.socket raises
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", good.getsockname()),
    ]
    monkeypatch.setattr(email_mod.socket, "getaddrinfo", lambda *a, **k: answers)
    sock = email_mod._connect_registered("mail.example", 143, 5.0)
    try:
        assert sock.getpeername() == good.getsockname()
    finally:
        ingest.unregister_mailbox_socket(sock)
        sock.close()
        good.close()


def test_a_failed_candidate_is_closed_and_unregistered(monkeypatch):
    held = _held_registrations(monkeypatch)
    good = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    good.bind(("127.0.0.1", 0))
    good.listen(1)
    dead = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", dead_port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", good.getsockname()),
    ]
    monkeypatch.setattr(email_mod.socket, "getaddrinfo", lambda *a, **k: answers)
    sock = email_mod._connect_registered("mail.example", 143, 5.0)
    try:
        assert len(held) == 2 and held[1] is sock
        assert held[0].fileno() == -1, "the refused candidate was not closed"
        assert held[0] not in ingest._LIVE_MAILBOX_SOCKETS and sock in ingest._LIVE_MAILBOX_SOCKETS
    finally:
        ingest.unregister_mailbox_socket(sock)
        sock.close()
        good.close()


def test_a_stopped_connect_closes_and_unregisters_its_socket(monkeypatch):
    held = _held_registrations(monkeypatch)
    monkeypatch.setattr(email_mod, "_connect_watching_stop", lambda *a: (_ for _ in ()).throw(email_mod._MailboxStopped()))
    with pytest.raises(email_mod._MailboxStopped):
        email_mod._connect_registered("127.0.0.1", 143, 5.0)
    assert held and all(s.fileno() == -1 and s not in ingest._LIVE_MAILBOX_SOCKETS for s in held)


def test_a_connect_on_a_descriptor_numbered_past_1024_works():
    """select.select refuses a descriptor numbered 1024 or more, which a process with a raised open-file limit reaches; the connect
    waits on a selector instead (security read A on #1899)."""
    resource = pytest.importorskip("resource")

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft != resource.RLIM_INFINITY and soft < 1200 and (hard == resource.RLIM_INFINITY or hard >= 1200):
        resource.setrlimit(resource.RLIMIT_NOFILE, (1200, hard))  # a typical soft limit is 1024; restored below
        request_restore = soft
    else:
        request_restore = None
    if request_restore is None and soft != resource.RLIM_INFINITY and soft < 1200:
        pytest.skip(f"the open-file limit ({soft}) is below what the test needs")
    lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    fillers = []
    try:
        while not fillers or fillers[-1].fileno() < 1100:
            fillers.append(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        sock = email_mod._connect_registered("127.0.0.1", lst.getsockname()[1], 5.0)
        assert sock.fileno() >= 1024 and sock.getpeername() == lst.getsockname()
        ingest.unregister_mailbox_socket(sock)
        sock.close()
    finally:
        for f in fillers:
            f.close()
        lst.close()
        if request_restore is not None:
            resource.setrlimit(resource.RLIMIT_NOFILE, (request_restore, hard))


def test_the_imaplib_open_audit_event_is_still_raised(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(email_mod.sys, "audit", lambda event, *args: seen.append((event, args[1:])))
    monkeypatch.setattr(email_mod, "_connect_registered", lambda *a: (_ for _ in ()).throw(ConnectionRefusedError("spy")))
    with pytest.raises(OSError):
        fetch_imap("127.0.0.1", "u", "p", use_ssl=False, port=1)
    assert ("imaplib.open", ("127.0.0.1", 1)) in seen


def test_a_zero_timeout_is_refused_as_create_connection_refuses_it():
    with pytest.raises(ValueError):
        email_mod._connect_registered("127.0.0.1", 143, 0)


@pytest.mark.parametrize("fn", _FNS, ids=_IDS)
def test_the_socket_is_registered_before_its_connect(fn, monkeypatch):
    seen: list[bool] = []
    real = ingest.register_mailbox_socket

    def spy(sock):
        try:
            sock.getpeername()
            seen.append(True)
        except OSError:
            seen.append(False)
        real(sock)

    monkeypatch.setattr(ingest, "register_mailbox_socket", spy)
    lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    port = lst.getsockname()[1]
    lst.close()  # nothing listens: the connect is refused, after the registration
    with pytest.raises(OSError):
        fn("127.0.0.1", "u", "p", use_ssl=False, port=port)
    assert seen and seen[0] is False, "the socket was registered only once connected"
    assert not ingest._LIVE_MAILBOX_SOCKETS


def test_a_refused_address_falls_through_to_the_next_and_leaves_nothing_registered(monkeypatch):
    good = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    good.bind(("127.0.0.1", 0))
    good.listen(1)
    dead = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", dead_port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", good.getsockname()),
    ]
    monkeypatch.setattr(email_mod.socket, "getaddrinfo", lambda *a, **k: answers)
    sock = email_mod._connect_registered("mail.example", 143, 5.0)
    try:
        assert sock.getpeername() == good.getsockname()
        assert sock.gettimeout() == 5.0
        assert list(ingest._LIVE_MAILBOX_SOCKETS) == [sock]
    finally:
        ingest.unregister_mailbox_socket(sock)
        sock.close()
        good.close()


def test_a_stop_before_the_connect_sends_no_syn(monkeypatch):
    connects: list[object] = []
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, a: connects.append(a) or 0)
    activate_kill_switch()
    with pytest.raises(email_mod._MailboxStopped):
        email_mod._connect_registered("127.0.0.1", 143, 5.0)
    assert connects == []
    assert not ingest._LIVE_MAILBOX_SOCKETS


@pytest.mark.parametrize("fn", _FNS, ids=_IDS)
def test_both_pulls_catch_the_stop_by_its_type_at_the_connect(fn, monkeypatch):
    """POP3 caught ``_MailboxStopped`` from its constructor only through ``except Exception`` and a second read of the switch (R652):
    it now catches it by its type, as IMAP does, so the Stop is never re-raised out of the pull."""

    def stopped(*a, **k):
        raise email_mod._MailboxStopped

    monkeypatch.setattr(email_mod, "_connect_registered", stopped)
    raws = fn("127.0.0.1", "u", "p", use_ssl=False, port=1)
    assert raws.stopped is True and list(raws) == []


def test_an_unexpected_starttls_reply_type_is_named_in_fixed_words_never_echoed():
    """S1's should-fix under R652: imaplib takes any run of capitals as a tagged reply's type, so the refusal names NO or BAD
    in fixed words and anything else as "an unexpected reply", never the server's bytes."""
    from tests.test_mailbox_starttls_r651 import (
        _IMAP_GREETING,
        _commands,
        _imap_answering_starttls_with,
        _Server,
    )

    marker = "ZQX" * 400
    srv = _Server(_IMAP_GREETING, _imap_answering_starttls_with(b"TAG " + marker.encode() + b" text\r\n"))
    try:
        with pytest.raises(MailboxStarttlsError) as info:
            fetch_imap("127.0.0.1", "u", "pw-r652-needle", use_ssl=False, port=srv.port)
        text = str(info.value)
        assert "answered STARTTLS with an unexpected reply" in text
        assert "ZQX" not in text
        assert srv.eof.wait(5)
        assert _commands(srv, fetch_imap) == [b"CAPABILITY", b"STARTTLS", b"LOGOUT"]
    finally:
        srv.close()
