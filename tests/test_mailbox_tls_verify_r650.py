"""Every mailbox pull checks the server's certificate chain and name, and refuses honestly when either fails (R650).

imaplib and poplib verify nothing by default (``ssl._create_stdlib_context``), so LOGIN/PASS went to whoever answered for the server.
The pull now hands both a ``ssl.create_default_context()``; a failed check is a ``MailboxCertificateError`` naming the host and the
cause, raised before any command is sent, with no fallback and no switch that turns the checks off. These tests run the real
imaplib/poplib against loopback TLS servers with throwaway certificates; nothing leaves the machine.
"""

from __future__ import annotations

import inspect
import socket
import ssl
import threading

import pytest

import src.ingest as ingest
import src.ingest.email as email_mod
from src.ingest import clear_kill_switch
from src.ingest.email import MailboxCertificateError, fetch_imap, fetch_pop3


@pytest.fixture(autouse=True)
def _net():
    clear_kill_switch()
    yield
    clear_kill_switch()


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    from tests._mailbox_tls_pki import build

    return build(tmp_path_factory.mktemp("tls"))


@pytest.fixture
def trust_test_ca(pki, monkeypatch):
    """The pull's own context, with the throwaway authority added to what it trusts (the checks themselves are untouched)."""
    real = email_mod._mailbox_tls_context

    def trusting():
        ctx = real()
        ctx.load_verify_locations(pki.ca_pem)
        return ctx

    monkeypatch.setattr(email_mod, "_mailbox_tls_context", trusting)


class _TlsServer:
    """One loopback TLS connection: greets, answers ``replies`` line by line, and records every line it receives."""

    def __init__(self, ctx: ssl.SSLContext, greeting: bytes, script):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.ctx, self.greeting, self.script = ctx, greeting, script
        self.received: list[bytes] = []
        self.handshake_error: BaseException | None = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            raw, _ = self.listener.accept()
            raw.settimeout(10)
            try:
                conn = self.ctx.wrap_socket(raw, server_side=True)
            except (ssl.SSLError, OSError) as exc:  # the client refused the certificate: the expected end of a refusal test
                self.handshake_error = exc
                raw.close()
                return
            with conn:
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
                        conn.sendall(self.script(line))
        finally:
            self.done.set()

    def close(self) -> None:
        self.listener.close()
        self.thread.join(5)


def _imap(line: bytes) -> bytes:
    tag, _, rest = line.partition(b" ")
    cmd = rest.split(b" ", 1)[0].upper()
    if cmd == b"CAPABILITY":
        return b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n"
    if cmd == b"SEARCH":
        return b"* SEARCH 1\r\n" + tag + b" OK done\r\n"
    if cmd == b"FETCH":
        body = b"Subject: one\r\n\r\nmessage 1\r\n"
        return b"* 1 FETCH (RFC822 {%d}\r\n" % len(body) + body + b")\r\n" + tag + b" OK done\r\n"
    if cmd == b"LOGOUT":
        return b"* BYE\r\n" + tag + b" OK done\r\n"
    return tag + b" OK done\r\n"


def _pop(line: bytes) -> bytes:
    cmd = line.split(b" ", 1)[0].upper()
    if cmd == b"LIST":
        return b"+OK 1 messages\r\n1 30\r\n.\r\n"
    if cmd == b"RETR":
        return b"+OK\r\nSubject: one\r\n\r\nmessage 1\r\n.\r\n"
    return b"+OK\r\n"


_PROTOCOLS = [(fetch_imap, b"* OK ready\r\n", _imap), (fetch_pop3, b"+OK ready\r\n", _pop)]
_IDS = ["imap", "pop3"]


@pytest.mark.parametrize(("fn", "greeting", "script"), _PROTOCOLS, ids=_IDS)
def test_a_certificate_no_trusted_authority_issued_is_refused_before_any_command(fn, greeting, script, pki):
    srv = _TlsServer(pki.self_signed_server, greeting, script)
    try:
        with pytest.raises(MailboxCertificateError) as info:
            fn("127.0.0.1", "u", "secret-pw", use_ssl=True, port=srv.port)
        msg = str(info.value)
        assert msg.startswith("refused before logging in, no command or password sent: "), msg  # what matters first: the job status keeps 300 characters
        assert "127.0.0.1" in msg and "failed its check (self-signed certificate)" in msg, msg  # OpenSSL's own reason, unwrapped
        assert "_ssl.c" not in msg and "CERTIFICATE_VERIFY_FAILED" not in msg
        assert "secret-pw" not in msg
        assert info.value.__cause__ is None and info.value.__suppress_context__
        assert srv.done.wait(5)
        assert srv.received == [], "a command (with the credential) went to a server whose certificate failed"
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), _PROTOCOLS, ids=_IDS)
def test_a_trusted_certificate_for_another_name_is_refused(fn, greeting, script, pki, trust_test_ca):
    """The chain checks out, the name does not: refused all the same (the host name check is on)."""
    srv = _TlsServer(pki.wrong_name_server, greeting, script)
    try:
        with pytest.raises(MailboxCertificateError) as info:
            fn("127.0.0.1", "u", "p", use_ssl=True, port=srv.port)
        assert "mismatch" in str(info.value), str(info.value)
        assert srv.done.wait(5)
        assert srv.received == []
    finally:
        srv.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), _PROTOCOLS, ids=_IDS)
def test_a_certificate_that_checks_out_pulls_as_before(fn, greeting, script, pki, trust_test_ca):
    srv = _TlsServer(pki.server, greeting, script)
    try:
        raws = fn("127.0.0.1", "u", "p", use_ssl=True, port=srv.port, limit=1)
        assert len(raws) == 1 and b"message 1" in raws[0]
        assert raws.stopped is False
    finally:
        srv.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), _PROTOCOLS, ids=_IDS)
def test_a_host_name_is_checked_and_sent_as_the_server_name(fn, greeting, script, pki, trust_test_ca):
    """The name checked is the host the pull was given, and it goes out as SNI (security read A on #1895: every other test connects
    to the IP 127.0.0.1, so a pull that checked a fixed name would have passed them)."""
    seen: list[str | None] = []
    ctx = pki.localhost_server
    ctx.sni_callback = lambda sock, name, c: seen.append(name)
    srv = _TlsServer(ctx, greeting, script)
    try:
        raws = fn("localhost", "u", "p", use_ssl=True, port=srv.port, limit=1)
        assert len(raws) == 1 and seen == ["localhost"]
    finally:
        ctx.sni_callback = None
        srv.close()
    srv = _TlsServer(pki.localhost_server, greeting, script)
    try:
        with pytest.raises(MailboxCertificateError, match="mismatch"):
            fn("127.0.0.1", "u", "p", use_ssl=True, port=srv.port)  # the same certificate does not name the IP
        assert srv.done.wait(5) and srv.received == []
    finally:
        srv.close()
    srv = _TlsServer(pki.wrong_name_server, greeting, script)
    try:
        # A trusted certificate for another DNS name, reached by a DNS name (security read B on #1895: a pull that dropped the name
        # check for DNS hosts only, or checked the peer's IP instead of the typed name, passed every IP-only test).
        with pytest.raises(MailboxCertificateError, match="Hostname mismatch"):
            fn("localhost", "u", "p", use_ssl=True, port=srv.port)
        assert srv.done.wait(5) and srv.received == []
    finally:
        srv.close()


def test_the_route_answers_a_certificate_refusal_as_the_mail_servers_failure_with_its_words(monkeypatch):
    """``/ingest-email`` answers 502 with the refusal's own sentence, not a 500 "internal error" (security read A on #1895)."""
    import src.api.ingestion as ingestion

    def refuse(*a, **k):
        raise email_mod._certificate_refusal("mail.example", "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1035)")

    monkeypatch.setattr(ingestion, "fetch_imap", refuse)
    from fastapi import HTTPException

    req = ingestion.IngestEmailRequest(host="mail.example", user="u", password="pw-needle-xyz")
    monkeypatch.setattr(ingestion, "_get_source", lambda db, sid: object())
    with pytest.raises(HTTPException) as info:
        ingestion.ingest_email_endpoint(1, req, db=None)
    assert info.value.status_code == 502
    assert "refused before logging in, no command or password sent" in info.value.detail and "self-signed certificate" in info.value.detail
    assert "pw-needle-xyz" not in info.value.detail


def test_the_context_checks_the_chain_and_the_name_and_uses_the_platform_trust():
    ctx = email_mod._mailbox_tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert email_mod._mailbox_tls_context() is not ctx  # a fresh one per pull: nothing a caller sets on one leaks into the next


@pytest.mark.parametrize(("fn", "attr", "kw"), [(fetch_imap, "imaplib", "ssl_context"), (fetch_pop3, "poplib", "context")], ids=_IDS)
def test_each_pull_hands_the_library_the_verifying_context(fn, attr, kw, monkeypatch):
    """Pins the wiring: dropping the context from a constructor falls back to the stdlib's unverified one, silently."""
    seen: dict = {}

    class _Spy:
        def __init__(self, host, port, timeout=None, **kwargs):
            seen.update(kwargs)
            raise ConnectionRefusedError("spy")

    lib = getattr(email_mod, attr)
    monkeypatch.setattr(lib, "IMAP4_SSL" if attr == "imaplib" else "POP3_SSL", _Spy)
    with pytest.raises(ConnectionRefusedError):
        fn("mail.example", "u", "p", use_ssl=True)
    ctx = seen.get(kw)
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_there_is_no_switch_that_turns_the_checks_off():
    src = inspect.getsource(email_mod)
    for weakening in ("CERT_NONE", "check_hostname = False", "check_hostname=False", "_create_unverified_context", "_create_stdlib_context"):
        assert weakening not in src, weakening
