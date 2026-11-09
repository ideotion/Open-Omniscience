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

    def __init__(self, greeting: bytes | None, script, tls=None, handshake: bool = True):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.greeting = greeting
        self.script = script
        self.tls = tls  # a server-side SSLContext, or None for plain
        self.handshake = handshake  # False: accept the TCP connection and never answer the TLS handshake
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
            self.eof.set()

    def close(self) -> None:
        self.listener.close()
        self.thread.join(5)


def _imap_script(line: bytes) -> bytes | None:
    tag, _, rest = line.partition(b" ")
    cmd = rest.split(b" ", 1)[0].upper()
    if cmd == b"CAPABILITY":
        return b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n"
    if cmd in (b"LOGIN", b"SELECT"):
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
    if cmd in (b"USER", b"PASS"):
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


def test_a_stop_ends_an_imap_pull_blocked_on_a_stalled_fetch_and_keeps_what_came_before():
    srv = _Server(b"* OK ready\r\n", _imap_script)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull(fetch_imap, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not end the blocked pull ({took:.1f} s)"
        assert raws.stopped is True
        assert [m.split(b"\r\n\r\n", 1)[1].strip() for m in raws] == [b"message 1"]
        assert srv.eof.wait(5)
        sent = [line.split(b" ", 2)[1].upper() for line in srv.received]
        assert sent == [b"CAPABILITY", b"LOGIN", b"CAPABILITY", b"SELECT", b"SEARCH", b"FETCH", b"FETCH"], "a command went out after the Stop"
        assert not ingest._LIVE_MAILBOX_SOCKETS, "the pull's socket was left registered"
    finally:
        srv.close()


def test_a_stop_ends_a_pop3_pull_blocked_on_a_stalled_retr_and_keeps_what_came_before():
    srv = _Server(b"+OK ready\r\n", _pop_script)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull(fetch_pop3, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not end the blocked pull ({took:.1f} s)"
        assert raws.stopped is True
        assert len(raws) == 1 and raws[0].endswith(b"message 1")
        assert srv.eof.wait(5)
        assert [line.split(b" ", 1)[0].upper() for line in srv.received] == [b"USER", b"PASS", b"LIST", b"RETR", b"RETR"]
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
def tls_server_context(tmp_path_factory):
    """A throwaway self-signed certificate for 127.0.0.1. (The pull's own TLS context does not verify it today; that is tracked
    separately, and these tests are about the Stop, not about trust.)"""
    import datetime
    import ipaddress
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    d = tmp_path_factory.mktemp("tls")
    (d / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "k.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(d / "c.pem", d / "k.pem")
    return ctx


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


def test_a_stop_during_the_logout_read_still_reaches_the_socket():
    """The socket stays registered until LOGOUT has been answered (security read B: it used to be forgotten first, so a server
    stalling on LOGOUT held the pull for the whole timeout after a Stop)."""

    def script(line: bytes) -> bytes | None:
        tag, _, rest = line.partition(b" ")
        if rest.split(b" ", 1)[0].upper() == b"LOGOUT":
            return None
        if rest.split(b" ", 1)[0].upper() == b"SEARCH":
            return b"* SEARCH\r\n" + tag + b" OK done\r\n"
        return _imap_script(line)

    srv = _Server(b"* OK ready\r\n", script)
    try:
        stopper = _stop_when(srv.stalled)
        raws, took = _pull(fetch_imap, srv.port)
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not reach the LOGOUT read ({took:.1f} s)"
        assert list(raws) == []
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()
