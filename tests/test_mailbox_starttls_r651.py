"""A mailbox pull on a plain port upgrades with STARTTLS before any credential, or is refused (R651).

``use_ssl=False`` used to run IMAP/POP3 in plaintext, LOGIN/USER/PASS included. It now requires STARTTLS (IMAP) or STLS (POP3), with
the same verifying context as a TLS port (R650); a server that does not offer it, refuses it, or fails the certificate check is
refused with a sentence naming the cause, and nothing past the upgrade attempt is sent. Real imaplib/poplib against loopback servers.
"""

from __future__ import annotations

import threading
import time

import pytest

import src.ingest as ingest
import src.ingest.email as email_mod
from src.ingest import clear_kill_switch
from src.ingest.email import (
    MailboxCertificateError,
    MailboxStarttlsError,
    MailboxTlsRefusal,
    fetch_imap,
    fetch_pop3,
)
from tests.test_mailbox_stall_r647 import _PROMPT_S, _imap_script, _pop_script, _Server, _stop_when


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
    real = email_mod._mailbox_tls_context

    def trusting():
        ctx = real()
        ctx.load_verify_locations(pki.ca_pem)
        return ctx

    monkeypatch.setattr(email_mod, "_mailbox_tls_context", trusting)


def _imap(line: bytes) -> bytes | None:
    """The stall tests' IMAP server, answering LOGOUT and holding one message, so a whole pull completes."""
    tag, _, rest = line.partition(b" ")
    cmd = rest.split(b" ", 1)[0].upper()
    if cmd == b"LOGOUT":
        return b"* BYE\r\n" + tag + b" OK done\r\n"
    if cmd == b"SEARCH":
        return b"* SEARCH 1\r\n" + tag + b" OK done\r\n"
    return _imap_script(line)


def _pop(line: bytes) -> bytes | None:
    """The same for POP3: QUIT answered, one message listed."""
    cmd = line.split(b" ", 1)[0].upper()
    if cmd == b"QUIT":
        return b"+OK bye\r\n"
    if cmd == b"LIST":
        return b"+OK 1 messages\r\n1 30\r\n.\r\n"
    return _pop_script(line)


def _imap_without_starttls(line: bytes) -> bytes | None:
    tag, _, rest = line.partition(b" ")
    if rest.split(b" ", 1)[0].upper() == b"CAPABILITY":
        return b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK done\r\n"
    return _imap(line)


def _imap_refusing_starttls(line: bytes) -> bytes | None:
    tag, _, rest = line.partition(b" ")
    if rest.split(b" ", 1)[0].upper() == b"STARTTLS":
        return tag + b" BAD not now\r\n"
    return _imap(line)


def _pop_without_stls(line: bytes) -> bytes | None:
    if line.split(b" ", 1)[0].upper() == b"CAPA":
        return b"+OK\r\nUSER\r\n.\r\n"
    return _pop(line)


def _pop_without_capa(line: bytes) -> bytes | None:
    if line.split(b" ", 1)[0].upper() == b"CAPA":
        return b"-ERR unknown command\r\n"
    return _pop(line)


def _pop_refusing_stls(line: bytes) -> bytes | None:
    if line.split(b" ", 1)[0].upper() == b"STLS":
        return b"-ERR not now\r\n"
    return _pop(line)


_IMAP_GREETING, _POP_GREETING = b"* OK ready\r\n", b"+OK ready\r\n"


def _commands(srv: _Server, fn) -> list[bytes]:
    if fn is fetch_imap:
        return [line.split(b" ", 2)[1].upper() for line in srv.received]
    return [line.split(b" ", 1)[0].upper() for line in srv.received]


@pytest.mark.parametrize(
    ("fn", "greeting", "script", "why", "sent"),
    [
        (fetch_imap, _IMAP_GREETING, _imap_without_starttls, "does not offer STARTTLS", [b"CAPABILITY", b"LOGOUT"]),
        (fetch_imap, _IMAP_GREETING, _imap_refusing_starttls, "refused STARTTLS", [b"CAPABILITY", b"STARTTLS", b"LOGOUT"]),
        (fetch_pop3, _POP_GREETING, _pop_without_stls, "does not offer STARTTLS (STLS)", [b"CAPA", b"QUIT"]),
        (fetch_pop3, _POP_GREETING, _pop_without_capa, "does not offer STARTTLS (STLS)", [b"CAPA", b"QUIT"]),
        (fetch_pop3, _POP_GREETING, _pop_refusing_stls, "refused STLS", [b"CAPA", b"STLS", b"QUIT"]),
    ],
    ids=["imap-not-offered", "imap-refused", "pop3-not-offered", "pop3-no-capa", "pop3-refused"],
)
def test_a_plain_port_without_starttls_is_refused_and_no_credential_is_sent(fn, greeting, script, why, sent):
    srv = _Server(greeting, script)
    try:
        with pytest.raises(MailboxStarttlsError) as info:
            fn("127.0.0.1", "u", "secret-pw-r651", use_ssl=False, port=srv.port)
        msg = str(info.value)
        assert msg.startswith("refused before logging in, no password sent: "), msg
        assert why in msg and f"port {srv.port}" in msg and "never sent unencrypted" in msg
        assert srv.eof.wait(5)
        assert _commands(srv, fn) == sent, "a credential (or any command past the refusal but the polite goodbye) went out"
        assert not any(b"secret-pw-r651" in line for line in srv.received)
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), [(fetch_imap, _IMAP_GREETING, _imap), (fetch_pop3, _POP_GREETING, _pop)], ids=["imap", "pop3"])
def test_starttls_with_a_certificate_that_fails_its_check_is_refused_before_any_credential(fn, greeting, script, pki):
    srv = _Server(greeting, script, starttls=pki.self_signed_server)
    try:
        with pytest.raises(MailboxCertificateError, match=r"failed its check \(self-signed certificate\)"):
            fn("127.0.0.1", "u", "secret-pw-r651", use_ssl=False, port=srv.port)
        assert srv.eof.wait(5)
        assert not any(cmd in (b"LOGIN", b"USER", b"PASS") for cmd in _commands(srv, fn))
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), [(fetch_imap, _IMAP_GREETING, _imap), (fetch_pop3, _POP_GREETING, _pop)], ids=["imap", "pop3"])
def test_a_trusted_starttls_upgrade_pulls_and_the_credential_goes_only_over_tls(fn, greeting, script, pki, trust_test_ca):
    srv = _Server(greeting, script, starttls=pki.server)
    try:
        raws = fn("127.0.0.1", "u", "p", use_ssl=False, port=srv.port, limit=1)
        assert raws.stopped is False and len(raws) == 1
        cmds = _commands(srv, fn)
        upgrade = cmds.index(b"STARTTLS" if fn is fetch_imap else b"STLS")
        first_credential = min(i for i, c in enumerate(cmds) if c in (b"LOGIN", b"USER"))
        assert upgrade < first_credential, cmds  # the server wraps right after the upgrade reply, so every later line came over TLS
    finally:
        srv.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), [(fetch_imap, _IMAP_GREETING, _imap), (fetch_pop3, _POP_GREETING, _pop)], ids=["imap", "pop3"])
def test_a_stop_reaches_a_pull_stalled_in_the_starttls_handshake(fn, greeting, script):
    """The server answers the upgrade and never handshakes: the Stop ends the pull at once (the upgraded socket is registered before
    the handshake, as on a TLS port), and nothing else goes out."""
    upgraded = threading.Event()

    def answering_then_silent(line: bytes) -> bytes | None:
        reply = script(line)
        if line.upper().startswith(b"STLS") or b" STARTTLS" in line.upper():
            upgraded.set()
        return reply

    srv = _Server(greeting, answering_then_silent)  # no TLS context: the ClientHello is read as junk and never answered
    try:
        stopper = _stop_when(upgraded)
        t0 = time.monotonic()
        raws = fn("127.0.0.1", "u", "p", use_ssl=False, port=srv.port)
        took = time.monotonic() - t0
        stopper.join(5)
        assert took < _PROMPT_S, f"the Stop did not reach the STARTTLS handshake ({took:.1f} s)"
        assert raws.stopped is True and list(raws) == []
        assert not any(cmd in (b"LOGIN", b"USER", b"PASS") for cmd in _commands(srv, fn))
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


def test_the_route_answers_a_starttls_refusal_as_a_502_with_its_words(monkeypatch):
    from fastapi import HTTPException

    import src.api.ingestion as ingestion

    def refuse(*a, **k):
        raise email_mod._starttls_refusal("mail.example", 143, "does not offer STARTTLS")

    monkeypatch.setattr(ingestion, "fetch_imap", refuse)
    monkeypatch.setattr(ingestion, "_get_source", lambda db, sid: object())
    req = ingestion.IngestEmailRequest(host="mail.example", user="u", password="pw-needle-r651", use_ssl=False)
    with pytest.raises(HTTPException) as info:
        ingestion.ingest_email_endpoint(1, req, db=None)
    assert info.value.status_code == 502 and "does not offer STARTTLS" in info.value.detail
    assert "pw-needle-r651" not in info.value.detail


def test_the_disclosure_says_the_password_never_travels_unencrypted():
    import src.api.ingestion as ingestion

    text = ingestion._MAILBOX_DISCLOSURE
    assert "STARTTLS" in text and "never sent unencrypted" in text and "certificate is checked" in text


@pytest.mark.parametrize(("fn", "greeting", "script"), [(fetch_imap, _IMAP_GREETING, _imap), (fetch_pop3, _POP_GREETING, _pop)], ids=["imap", "pop3"])
def test_a_plain_server_on_the_tls_port_is_refused_naming_the_server_and_the_port(fn, greeting, script):
    """Security read B on #1895: a TLS failure that is not the certificate's (here a plaintext greeting where a handshake belongs)
    surfaced as OpenSSL's raw text. It is now the same refusal, naming the server, the port and the reason."""
    srv = _Server(greeting, script)
    try:
        with pytest.raises(MailboxTlsRefusal) as info:
            fn("127.0.0.1", "u", "p", use_ssl=True, port=srv.port)
        msg = str(info.value)
        assert not isinstance(info.value, MailboxCertificateError)
        assert msg.startswith("refused before logging in, no command or password sent: no TLS connection could be made"), msg
        assert f"127.0.0.1 on port {srv.port} (" in msg and "_ssl.c" not in msg and "[SSL:" not in msg
        # The server reads the ClientHello as text, so a random CR LF in it can make a "line": no line is a mail command.
        assert not any(word in line.upper() for line in srv.received for word in (b"LOGIN", b"USER", b"PASS", b"CAPA"))
    finally:
        srv.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), [(fetch_imap, _IMAP_GREETING, _imap), (fetch_pop3, _POP_GREETING, _pop)], ids=["imap", "pop3"])
def test_a_starttls_answered_with_plaintext_is_refused_before_any_credential(fn, greeting, script):
    srv = _Server(greeting, script)
    srv.after_upgrade = b"this is not a TLS record at all\r\n"
    try:
        with pytest.raises(MailboxTlsRefusal, match=r"^refused before logging in, no password sent: no TLS connection could be made"):
            fn("127.0.0.1", "u", "secret-pw-r651", use_ssl=False, port=srv.port)
        assert not any(cmd in (b"LOGIN", b"USER", b"PASS") for cmd in _commands(srv, fn))
        assert not ingest._LIVE_MAILBOX_SOCKETS
    finally:
        srv.close()


# --- Security reads A and B on #1898 -------------------------------------------------------------------------------------------------


def _imap_answering_starttls_with(answer: bytes):
    def script(line: bytes) -> bytes | None:
        tag, _, rest = line.partition(b" ")
        if rest.split(b" ", 1)[0].upper() == b"STARTTLS":
            return answer.replace(b"TAG", tag)
        return _imap(line)

    return script


def test_a_no_answer_to_starttls_is_refused_and_no_handshake_or_credential_follows():
    srv = _Server(_IMAP_GREETING, _imap_answering_starttls_with(b"TAG NO not today\r\n"))
    try:
        with pytest.raises(MailboxStarttlsError, match="answered STARTTLS with NO"):
            fetch_imap("127.0.0.1", "u", "secret-pw-r651", use_ssl=False, port=srv.port)
        assert srv.eof.wait(5)
        assert _commands(srv, fetch_imap) == [b"CAPABILITY", b"STARTTLS", b"LOGOUT"]
    finally:
        srv.close()


def test_a_preauth_greeting_is_refused_without_sending_starttls():
    srv = _Server(b"* PREAUTH [CAPABILITY IMAP4rev1 STARTTLS] welcome\r\n", _imap)
    try:
        with pytest.raises(MailboxStarttlsError, match=r"already logged in \(PREAUTH\)"):
            fetch_imap("127.0.0.1", "u", "p", use_ssl=False, port=srv.port)
        assert srv.eof.wait(5)
        assert b"STARTTLS" not in _commands(srv, fetch_imap)
    finally:
        srv.close()


def test_a_connection_lost_before_the_starttls_answer_says_so():
    """imaplib turns the lost connection into its ``abort``: named as such, not as a refusal of the upgrade (security read A)."""
    # A server that closes on STARTTLS: built on a raw socket so the close is immediate.
    import socket as _socket

    lst = _socket.socket()
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)

    def serve() -> None:
        conn, _ = lst.accept()
        with conn:
            conn.sendall(_IMAP_GREETING)
            f = conn.makefile("rb")
            while line := f.readline():
                tag = line.split(b" ", 1)[0]
                if b" STARTTLS" in line.upper():
                    return
                conn.sendall(b"* CAPABILITY IMAP4rev1 STARTTLS\r\n" + tag + b" OK done\r\n")

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        with pytest.raises(MailboxStarttlsError, match="closed the connection before answering STARTTLS"):
            fetch_imap("127.0.0.1", "u", "p", use_ssl=False, port=lst.getsockname()[1])
    finally:
        t.join(5)
        lst.close()


@pytest.mark.parametrize(("fn", "greeting", "script"), [(fetch_imap, _IMAP_GREETING, _imap), (fetch_pop3, _POP_GREETING, _pop)], ids=["imap", "pop3"])
def test_starttls_to_a_trusted_certificate_for_another_name_is_refused_naming_what_was_sent(fn, greeting, script, pki, trust_test_ca):
    """The name check is on along the STARTTLS path too (security read A on #1898), and the refusal says only the password was not
    sent: the capability and upgrade requests did go out."""
    srv = _Server(greeting, script, starttls=pki.wrong_name_server)
    try:
        with pytest.raises(MailboxCertificateError) as info:
            fn("127.0.0.1", "u", "secret-pw-r651", use_ssl=False, port=srv.port)
        msg = str(info.value)
        assert msg.startswith("refused before logging in, no password sent: ") and "mismatch" in msg, msg
        assert srv.eof.wait(5)
        assert not any(cmd in (b"LOGIN", b"USER", b"PASS") for cmd in _commands(srv, fn))
    finally:
        srv.close()


@pytest.mark.parametrize("fn", [fetch_imap, fetch_pop3], ids=["imap", "pop3"])
def test_a_stop_when_the_capabilities_are_answered_sends_no_upgrade_request(fn):
    """The switch is read before STARTTLS/STLS: a Stop that lands while the capability request is answered stops there."""
    from src.ingest import activate_kill_switch

    base = _imap if fn is fetch_imap else _pop

    def stopping(line: bytes) -> bytes | None:
        reply = base(line)
        if b"CAPA" in line.upper():
            activate_kill_switch()
        return reply

    srv = _Server(_IMAP_GREETING if fn is fetch_imap else _POP_GREETING, stopping)
    try:
        raws = fn("127.0.0.1", "u", "p", use_ssl=False, port=srv.port)
        assert raws.stopped is True
        assert srv.eof.wait(5)
        assert not any(cmd in (b"STARTTLS", b"STLS", b"LOGIN", b"USER") for cmd in _commands(srv, fn))
    finally:
        srv.close()


def test_responses_injected_around_the_starttls_answer_are_not_carried_past_the_upgrade(pki, trust_test_ca):
    """An untagged SEARCH before the OK and a forged FETCH right after it, in the same segment (the STARTTLS response-injection
    class): neither reaches the pull, which fetches only the one real message over TLS."""
    injected = b"* SEARCH 7 8 9\r\nTAG OK go\r\n* 9 FETCH (RFC822 {9}\r\nEVIL!!!\r\n)\r\n"
    srv = _Server(_IMAP_GREETING, _imap_answering_starttls_with(injected), starttls=pki.server)
    try:
        raws = fetch_imap("127.0.0.1", "u", "p", use_ssl=False, port=srv.port, limit=5)
        assert len(raws) == 1 and b"message 1" in raws[0] and not any(b"EVIL" in r for r in raws)
    finally:
        srv.close()


def test_the_reader_is_rebound_with_nothing_buffered_on_either_imaplib_layout():
    """3.13 reads ``file``; 3.14 reads a ``_file`` behind a read-only ``file`` property and buffers in ``_readbuf`` (security read A
    on #1898: assigning ``file`` there raises). Both are rebound, emptied, and no untagged response survives."""

    class _Sock:
        def makefile(self, mode):
            return ("fresh", mode)

    class _Old:
        def __init__(self):
            self.sock, self.file, self.untagged_responses = _Sock(), "stale", {"SEARCH": [b"7 8 9"]}

    class _New:
        file = property(lambda self: self._file)

        def __init__(self):
            self.sock, self._file, self._readbuf, self.untagged_responses = _Sock(), "stale", [b"* 9 FETCH"], {"EXISTS": [b"3"]}

    old, new = _Old(), _New()
    email_mod._rebind_reader(old)
    email_mod._rebind_reader(new)
    assert old.file == ("fresh", "rb") and old.untagged_responses == {}
    assert new.file == ("fresh", "rb") and new._readbuf == [] and new.untagged_responses == {}


@pytest.mark.parametrize(("fn", "greeting", "script"), [(fetch_imap, _IMAP_GREETING, _imap), (fetch_pop3, _POP_GREETING, _pop)], ids=["imap", "pop3"])
def test_a_starttls_handshake_that_times_out_is_refused_naming_the_server(fn, greeting, script, monkeypatch):
    monkeypatch.setattr(email_mod, "MAILBOX_TIMEOUT_S", 0.5)
    srv = _Server(greeting, script)  # answers the upgrade and never handshakes
    try:
        with pytest.raises(MailboxTlsRefusal) as info:
            fn("127.0.0.1", "u", "p", use_ssl=False, port=srv.port)
        msg = str(info.value)
        assert "the TLS handshake timed out" in msg and f"port {srv.port}" in msg and "no password sent" in msg, msg
        assert "_ssl.c" not in msg and "accepted the upgrade" in msg
    finally:
        srv.close()


def test_a_lower_case_stls_capability_is_honoured(monkeypatch):
    monkeypatch.setattr(email_mod, "MAILBOX_TIMEOUT_S", 0.5)
    def lower(line: bytes) -> bytes | None:
        if line.split(b" ", 1)[0].upper() == b"CAPA":
            return b"+OK\r\nuser\r\nstls\r\n.\r\n"
        return _pop(line)

    srv = _Server(_POP_GREETING, lower)
    try:
        with pytest.raises(MailboxTlsRefusal):  # the upgrade is attempted (no TLS server here), not refused as "not offered"
            fetch_pop3("127.0.0.1", "u", "p", use_ssl=False, port=srv.port)
        assert b"STLS" in _commands(srv, fetch_pop3)
    finally:
        srv.close()
