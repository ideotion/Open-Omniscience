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
from src.ingest.email import fetch_imap, fetch_pop3

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
    """Portable: with the platform never reporting the connect done (here a select that sees nothing), the Stop still ends it within
    the slice, without relying on the shutdown aborting the connect."""
    lst = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    calls = {"n": 0}

    def never(r, w, x, timeout):
        calls["n"] += 1
        time.sleep(timeout)
        return [], [], []

    monkeypatch.setattr(email_mod.select, "select", never)
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
