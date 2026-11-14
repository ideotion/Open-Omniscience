"""A Stop ends a mailbox pull blocked on a stalled server, at once (R647).

R640 reads the switch before every command, which cannot help a pull already blocked inside one: a server that stops answering held
it until the OS gave up. The live IMAP/POP3 socket is now registered the moment it exists, and ``activate_kill_switch`` shuts it down,
as R638 closes the HTTP pools; every read and write also has a bounded timeout (``MAILBOX_TIMEOUT_S``). These tests run the real
imaplib/poplib against a stalling server on loopback; nothing leaves the machine.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

import src.ingest as ingest
import src.ingest.email as email_mod
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.email import fetch_imap, fetch_pop3

#: Far below the 60 s timeout and far above a loopback round trip: a pull that ends inside it ended on the Stop.
_PROMPT_S = 5.0


@pytest.fixture(autouse=True)
def _net():
    clear_kill_switch()
    yield
    clear_kill_switch()


class _Server:
    """One loopback connection, answered by ``script`` (the lines received so far -> the reply, or None to stall)."""

    def __init__(self, greeting: bytes | None, script, tls=None, handshake: bool = True, starttls=None):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.greeting = greeting
        self.script = script
        self.tls = tls  # a server-side SSLContext, or None for plain
        self.handshake = handshake  # False: accept the TCP connection and never answer the TLS handshake
        self.starttls = starttls  # a server-side SSLContext the connection is upgraded with after a STARTTLS/STLS reply (R651)
        self.after_upgrade: bytes | None = None  # without ``starttls``: bytes sent a moment after the upgrade reply, where a handshake belongs
        self.received: list[bytes] = []
        self.stalled = threading.Event()
        self.eof = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        conn, _ = self.listener.accept()
        conn.settimeout(30)
        if self.tls is not None:
            if not self.handshake:
                self.stalled.set()
                with conn:
                    while conn.recv(4096):  # swallow the ClientHello, answer nothing, until the client goes
                        pass
                self.eof.set()
                return
            conn = self.tls.wrap_socket(conn, server_side=True)
        with conn:
            if self.greeting is None:
                self.stalled.set()
            else:
                conn.sendall(self.greeting)
            buf = b""
            while True:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    self.received.append(line)
                    reply = self.script(line)
                    if reply is None:
                        self.stalled.set()
                    else:
                        conn.sendall(reply)
                        if self.after_upgrade is not None and _upgrade_command(line):
                            time.sleep(0.3)  # the client has read the reply and sent its ClientHello: this lands in the TLS layer
                            conn.sendall(self.after_upgrade)
                        if self.starttls is None and _upgrade_command(line) and _accepts_upgrade(reply):
                            # The upgrade was ACCEPTED and there is no context to upgrade with: what follows is the client's
                            # TLS handshake, never a command (a REFUSED upgrade stays in plain text, so it keeps parsing). Read
                            # and discard it until the client goes. Splitting it on CRLF answered "-ERR unexpected" into the
                            # client's TLS layer whenever the ClientHello's random bytes held one (about 1 run in 100), so a
                            # test expecting a handshake timeout saw "wrong version number" (open-on-main row 41).
                            try:
                                while conn.recv(4096):
                                    pass
                            except OSError:
                                pass
                            self.eof.set()
                            return
                        if self.starttls is not None and _upgrade_command(line):
                            try:
                                conn = self.starttls.wrap_socket(conn, server_side=True)
                            except OSError:  # the client refused the certificate (R650/R651): its connection is over
                                break
                            buf = b""
            self.eof.set()

    def close(self) -> None:
        self.listener.close()
        self.thread.join(5)


def _accepts_upgrade(reply: bytes) -> bool:
    """Whether the reply to STARTTLS/STLS said yes: POP3's ``+OK``, or IMAP's tagged ``OK`` on the last line."""
    last = reply.rstrip(b"\r\n").rsplit(b"\r\n", 1)[-1]
    return last.startswith(b"+OK") or last.split(b" ")[1:2] == [b"OK"]


def _upgrade_command(line: bytes) -> bool:
    words = line.upper().split(b" ")
    return words[0] == b"STLS" or (len(words) > 1 and words[1] == b"STARTTLS")


def _imap_script(line: bytes) -> bytes | None:
    tag, _, rest = line.partition(b" ")
    cmd = rest.split(b" ", 1)[0].upper()
    if cmd == b"CAPABILITY":
        return b"* CAPABILITY IMAP4rev1 STARTTLS\r\n" + tag + b" OK done\r\n"
    if cmd in (b"LOGIN", b"SELECT", b"STARTTLS"):
        return tag + b" OK done\r\n"
    if cmd == b"SEARCH":
        return b"* SEARCH 1 2 3\r\n" + tag + b" OK done\r\n"
    if cmd == b"FETCH":
        mid = rest.split(b" ")[1]
        if mid != b"1":
            return None  # the server stops answering
        body = b"Subject: one\r\n\r\nmessage 1\r\n"
        return b"* 1 FETCH (RFC822 {%d}\r\n" % len(body) + body + b")\r\n" + tag + b" OK done\r\n"
    return tag + b" BAD unexpected\r\n"


def _pop_script(line: bytes) -> bytes | None:
    cmd = line.split(b" ", 1)[0].upper()
    if cmd == b"CAPA":
        return b"+OK\r\nSTLS\r\nUSER\r\n.\r\n"
    if cmd in (b"USER", b"PASS", b"STLS"):
        return b"+OK\r\n"
    if cmd == b"LIST":
        return b"+OK 3 messages\r\n1 30\r\n2 30\r\n3 30\r\n.\r\n"
    if cmd == b"RETR":
        if line.split(b" ")[1] != b"1":
            return None
        return b"+OK\r\nSubject: one\r\n\r\nmessage 1\r\n.\r\n"
    return b"-ERR unexpected\r\n"


def _stop_when(event: threading.Event) -> threading.Thread:
    def run() -> None:
        if event.wait(10):
            time.sleep(0.2)  # the pull is now blocked in its read
            activate_kill_switch()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _pull(fn, port: int, **kw):
    t0 = time.monotonic()
    raws = fn("127.0.0.1", "u", "p", use_ssl=False, port=port, limit=3, **kw)
    return raws, time.monotonic() - t0


def test_a_stop_ends_an_imap_pull_blocked_on_a_stalled_fetch_and_keeps_what_came_before(tls_server_context):
    srv = _Server(b"* OK ready\r\n", _imap_script, starttls=tls_server_context)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull(fetch_imap, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not end the blocked pull ({took:.1f} s)"
        assert raws.stopped is True
        assert [m.split(b"\r\n\r\n", 1)[1].strip() for m in raws] == [b"message 1"]
        assert srv.eof.wait(5)
        sent = [line.split(b" ", 2)[1].upper() for line in srv.received]
        assert sent == [b"CAPABILITY", b"STARTTLS", b"CAPABILITY", b"LOGIN", b"CAPABILITY", b"SELECT", b"SEARCH", b"FETCH", b"FETCH"], (
            "a command went out after the Stop"
        )
        assert not ingest._LIVE_MAILBOX_SOCKETS, "the pull's socket was left registered"
    finally:
        srv.close()


def test_a_stop_ends_a_pop3_pull_blocked_on_a_stalled_retr_and_keeps_what_came_before(tls_server_context):
    srv = _Server(b"+OK ready\r\n", _pop_script, starttls=tls_server_context)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull(fetch_pop3, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not end the blocked pull ({took:.1f} s)"
        assert raws.stopped is True
        assert len(raws) == 1 and raws[0].endswith(b"message 1")
        assert srv.eof.wait(5)
        assert [line.split(b" ", 1)[0].upper() for line in srv.received] == [b"CAPA", b"STLS", b"USER", b"PASS", b"LIST", b"RETR", b"RETR"]
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


@pytest.mark.parametrize("fn", [fetch_imap, fetch_pop3], ids=["imap", "pop3"])
def test_a_stop_while_the_greeting_is_awaited_ends_the_pull(fn):
    """The socket is registered before the greeting is read, so a server that accepts and never greets is cut off by the Stop too."""
    srv = _Server(None, lambda line: None)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull(fn, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S
        assert raws.stopped is True and list(raws) == []
        assert srv.received == []
    finally:
        srv.close()


@pytest.mark.parametrize("fn", [fetch_imap, fetch_pop3], ids=["imap", "pop3"])
def test_without_a_stop_a_stalled_server_meets_the_bounded_timeout(fn, monkeypatch):
    """The timeout is real and is an error while online (here shortened; the shipped value is 60 s)."""
    assert email_mod.MAILBOX_TIMEOUT_S == 60.0
    monkeypatch.setattr(email_mod, "MAILBOX_TIMEOUT_S", 0.5)
    srv = _Server(None, lambda line: None)
    try:
        t0 = time.monotonic()
        with pytest.raises(OSError):
            fn("127.0.0.1", "u", "p", use_ssl=False, port=srv.port)
        assert time.monotonic() - t0 < _PROMPT_S
    finally:
        srv.close()


def test_a_socket_registered_after_the_stop_is_shut_at_once():
    """A Stop between the connect and the registration is not missed: registering under an engaged switch shuts the socket down."""
    a, b = socket.socketpair()
    try:
        activate_kill_switch()
        ingest.register_mailbox_socket(a)
        b.settimeout(2)
        assert b.recv(1) == b""  # the peer sees the shutdown
        ingest.unregister_mailbox_socket(a)
    finally:
        a.close()
        b.close()


def test_the_stop_shuts_every_registered_socket():
    a, b = socket.socketpair()
    try:
        ingest.register_mailbox_socket(a)
        activate_kill_switch()
        b.settimeout(2)
        assert b.recv(1) == b""
    finally:
        ingest.unregister_mailbox_socket(a)
        a.close()
        b.close()


# --- TLS, the default path (security read B on #1892) ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _pki(tmp_path_factory):
    from tests._mailbox_tls_pki import build

    return build(tmp_path_factory.mktemp("tls"))


@pytest.fixture
def tls_server_context(_pki, monkeypatch):
    """A server certificate for 127.0.0.1 from a throwaway authority the pull is told to trust (R650 verifies every mailbox
    certificate; these tests are about the Stop, not about trust, so the chain and the name both check out)."""
    real = email_mod._mailbox_tls_context

    def trusting():
        ctx = real()
        ctx.load_verify_locations(_pki.ca_pem)
        return ctx

    monkeypatch.setattr(email_mod, "_mailbox_tls_context", trusting)
    return _pki.server


def _pull_tls(fn, port: int):
    t0 = time.monotonic()
    raws = fn("127.0.0.1", "u", "p", use_ssl=True, port=port, limit=3)
    return raws, time.monotonic() - t0


@pytest.mark.parametrize("fn", [fetch_imap, fetch_pop3], ids=["imap", "pop3"])
def test_a_stop_reaches_a_pull_stalled_in_the_tls_handshake(fn, tls_server_context):
    """The plain socket is registered when the TCP connect returns, before the handshake: a server that never answers the
    ClientHello is cut off by the Stop, not by the timeout."""
    srv = _Server(None, lambda line: None, tls=tls_server_context, handshake=False)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull_tls(fn, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not reach the TLS handshake ({took:.1f} s)"
        assert raws.stopped is True and list(raws) == []
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


def test_a_stop_ends_a_tls_imap_pull_blocked_mid_session(tls_server_context):
    srv = _Server(b"* OK ready\r\n", _imap_script, tls=tls_server_context)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull_tls(fetch_imap, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S
        assert raws.stopped is True and len(raws) == 1
        assert srv.eof.wait(5)
        assert [line.split(b" ", 2)[1].upper() for line in srv.received][-2:] == [b"FETCH", b"FETCH"]
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


def test_a_stop_ends_a_tls_pop3_pull_blocked_mid_session(tls_server_context):
    srv = _Server(b"+OK ready\r\n", _pop_script, tls=tls_server_context)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull_tls(fetch_pop3, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S
        assert raws.stopped is True and len(raws) == 1
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


@pytest.mark.parametrize("fn", [fetch_imap, fetch_pop3], ids=["imap", "pop3"])
def test_the_tls_constructors_carry_the_bounded_timeout(fn, tls_server_context, monkeypatch):
    """Pins the timeout on the TLS path (security read B: removing it from IMAP4_SSL left every test green)."""
    monkeypatch.setattr(email_mod, "MAILBOX_TIMEOUT_S", 0.5)
    srv = _Server(None, lambda line: None, tls=tls_server_context, handshake=False)
    try:
        t0 = time.monotonic()
        with pytest.raises(OSError):
            fn("127.0.0.1", "u", "p", use_ssl=True, port=srv.port)
        assert time.monotonic() - t0 < _PROMPT_S
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


def _imap_logout_stall(line: bytes) -> bytes | None:
    tag, _, rest = line.partition(b" ")
    cmd = rest.split(b" ", 1)[0].upper()
    if cmd == b"LOGOUT":
        return None
    if cmd == b"SEARCH":
        return b"* SEARCH\r\n" + tag + b" OK done\r\n"
    return _imap_script(line)


def _pop_quit_stall(line: bytes) -> bytes | None:
    cmd = line.split(b" ", 1)[0].upper()
    if cmd == b"QUIT":
        return None
    if cmd == b"LIST":
        return b"+OK 0 messages\r\n.\r\n"
    return _pop_script(line)


@pytest.mark.parametrize(
    ("fn", "greeting", "script"),
    [(fetch_imap, b"* OK ready\r\n", _imap_logout_stall), (fetch_pop3, b"+OK ready\r\n", _pop_quit_stall)],
    ids=["imap-logout", "pop3-quit"],
)
def test_a_stop_during_the_logout_read_still_reaches_the_socket(fn, greeting, script, tls_server_context):
    """The socket stays registered until LOGOUT/QUIT has been answered (security read B on #1892: it used to be forgotten first, so a
    server stalling on LOGOUT held the pull for the whole timeout after a Stop; the POP3 twin was unpinned until its second read)."""
    srv = _Server(greeting, script, starttls=tls_server_context)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull(fn, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not reach the LOGOUT/QUIT read ({took:.1f} s)"
        assert list(raws) == []
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


def _done_imap(line: bytes) -> bytes | None:
    tag, _, rest = line.partition(b" ")
    cmd = rest.split(b" ", 1)[0].upper()
    if cmd == b"SEARCH":
        return b"* SEARCH\r\n" + tag + b" OK done\r\n"
    if cmd == b"LOGOUT":
        return b"* BYE\r\n" + tag + b" OK done\r\n"
    return _imap_script(line)


def _done_pop(line: bytes) -> bytes | None:
    if line.split(b" ", 1)[0].upper() == b"QUIT":
        return b"+OK bye\r\n"
    return _pop_quit_stall(line)


@pytest.mark.parametrize(
    ("fn", "greeting", "script"),
    [(fetch_imap, b"* OK ready\r\n", _done_imap), (fetch_pop3, b"+OK ready\r\n", _done_pop)],
    ids=["imap", "pop3"],
)
def test_a_finished_pull_takes_its_socket_off_the_list(fn, greeting, script, monkeypatch, tls_server_context):
    """Holds every registered socket alive, so the weak list cannot empty itself by collection (security read A on #1892: poplib's
    ``quit()`` clears ``conn.sock``, so the POP3 socket used to stay listed and only garbage collection hid it)."""
    held: list[object] = []
    real = ingest.register_mailbox_socket

    def holding(sock):
        held.append(sock)
        real(sock)

    monkeypatch.setattr(ingest, "register_mailbox_socket", holding)
    srv = _Server(greeting, script, starttls=tls_server_context)
    try:
        raws, _ = _pull(fn, srv.port)
        assert raws.stopped is False
        assert held, "no socket was registered"
        assert not [s for s in held if s in ingest._LIVE_MAILBOX_SOCKETS], "a finished pull left its socket on the Stop's list"
    finally:
        srv.close()


@pytest.mark.parametrize("cls", ["IMAP4_SSL", "POP3_SSL"])
def test_a_wrap_that_fails_online_raises_its_own_error_and_closes_the_socket(cls, monkeypatch):
    """Security read A on #1892: the cleanup used to unregister ``None`` (the wrap had not returned), which raised a TypeError over the
    real error and skipped the close."""
    import imaplib
    import poplib
    import ssl

    class _Boom(ssl.SSLContext):
        def wrap_socket(self, *a, **k):
            raise ValueError("the wrap failed")

    lib = imaplib if cls == "IMAP4_SSL" else poplib
    stop_aware = email_mod._stop_aware(getattr(lib, cls))
    kw = {"ssl_context": _Boom(ssl.PROTOCOL_TLS_CLIENT)} if cls == "IMAP4_SSL" else {"context": _Boom(ssl.PROTOCOL_TLS_CLIENT)}
    srv = _Server(None, lambda line: None)
    registered: list[socket.socket] = []  # strong references: the client's own socket, never one the server closes
    real_register = ingest.register_mailbox_socket

    def holding(sock):
        registered.append(sock)
        real_register(sock)

    monkeypatch.setattr(ingest, "register_mailbox_socket", holding)
    try:
        with pytest.raises(ValueError, match="the wrap failed"):
            stop_aware("127.0.0.1", srv.port, timeout=5, **kw)
        assert registered, "the plain socket was never registered"
        assert all(s.fileno() == -1 for s in registered), "the plain socket was left open"
        assert not ingest._LIVE_MAILBOX_SOCKETS
        assert srv.stalled.wait(5)  # the server took the connection before its listener is closed
    finally:
        srv.close()


def test_unregistering_none_is_a_no_op():
    ingest.unregister_mailbox_socket(None)
