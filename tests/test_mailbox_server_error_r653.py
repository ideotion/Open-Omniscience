"""R653: a mail server's own error reply ends a pull in fixed words, never quoted; the catch-all 500 is cut at 300 characters after
its scrub; and a serving-gate check that raises is the fixed 503 with no exception text.

imaplib and poplib put the server's line in their exceptions, and on a plain port the greeting and CAPABILITY reply come before
STARTTLS, so anyone on the path can write them; imaplib accepts a line of up to a megabyte. Loopback servers only."""

from __future__ import annotations

import asyncio

import pytest

import src.api.main as main
import src.ingest.airplane as ap
import src.ingest.email as email_mod
from src.ingest import clear_kill_switch
from src.ingest.email import MailboxServerError, fetch_imap, fetch_pop3
from tests.test_mailbox_stall_r647 import _Server
from tests.test_mailbox_starttls_r651 import _IMAP_GREETING, _POP_GREETING, _imap, _pop

#: Server-controlled text: it must never reach an exception, a detail or a log line of the pull's.
_MARK = b"ZQXR653" * 300
_PW = "pw-r653-needle"


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


def _answering(base, command: bytes, reply: bytes, *, pop: bool = False):
    """``base`` with one command answered by ``reply`` (``TAG`` replaced by the command's tag for IMAP)."""

    def script(line: bytes) -> bytes | None:
        if pop:
            if line.split(b" ", 1)[0].upper() == command:
                return reply
            return base(line)
        tag, _, rest = line.partition(b" ")
        if rest.split(b" ", 1)[0].upper() == command:
            return reply.replace(b"TAG", tag)
        return base(line)

    return script


def _refused(fn, srv, **kw) -> str:
    with pytest.raises(MailboxServerError) as info:
        fn("127.0.0.1", "u", _PW, port=srv.port, **kw)
    text = str(info.value)
    assert "ZQXR653" not in text and _PW not in text
    assert "the server's own reply is not shown" in text and str(srv.port) in text
    return text


@pytest.mark.parametrize(
    ("greeting", "script"),
    [
        (b"* BYE " + _MARK + b"\r\n", _imap),
        (b"* WHAT " + _MARK + b"\r\n", _imap),
        (_IMAP_GREETING, _answering(_imap, b"CAPABILITY", b"TAG BAD " + _MARK + b"\r\n")),
        (_IMAP_GREETING, _answering(_imap, b"CAPABILITY", b"* BYE " + _MARK + b"\r\n")),
    ],
    ids=["bye-greeting", "odd-greeting", "capability-bad", "capability-bye"],
)
def test_an_imap_greeting_or_capability_failure_before_starttls_is_named_in_fixed_words(greeting, script):
    srv = _Server(greeting, script)
    try:
        text = _refused(fetch_imap, srv, use_ssl=False)
        assert "before logging in; no password was sent" in text
        assert not any(c.upper().startswith(b"LOGIN") for c in (line.split(b" ", 2)[1] for line in srv.received if b" " in line))
    finally:
        srv.close()


def test_a_pop3_error_greeting_is_named_in_fixed_words():
    srv = _Server(b"-ERR " + _MARK + b"\r\n", _pop)
    try:
        text = _refused(fetch_pop3, srv, use_ssl=False)
        assert "before logging in; no password was sent" in text
    finally:
        srv.close()


def test_an_imap_login_refusal_is_named_in_fixed_words(pki, trust_test_ca):
    srv = _Server(_IMAP_GREETING, _answering(_imap, b"LOGIN", b"TAG NO " + _MARK + b"\r\n"), starttls=pki.server)
    try:
        assert "refused the login" in _refused(fetch_imap, srv, use_ssl=False)
    finally:
        srv.close()


def test_a_pop3_password_refusal_is_named_in_fixed_words(pki, trust_test_ca):
    srv = _Server(_POP_GREETING, _answering(_pop, b"PASS", b"-ERR " + _MARK + b"\r\n", pop=True), starttls=pki.server)
    try:
        assert "refused the login" in _refused(fetch_pop3, srv, use_ssl=False)
    finally:
        srv.close()


def test_an_error_after_the_login_is_named_in_fixed_words(pki, trust_test_ca):
    srv = _Server(_IMAP_GREETING, _answering(_imap, b"SEARCH", b"TAG BAD " + _MARK + b"\r\n"), starttls=pki.server)
    try:
        assert "after logging in" in _refused(fetch_imap, srv, use_ssl=False)
    finally:
        srv.close()


def test_a_stop_still_wins_over_a_server_error():
    """The Stop is read before the server's error is named, as for every other failure (R640)."""
    from src.ingest import activate_kill_switch

    def stop_then_bye(line: bytes) -> bytes | None:
        activate_kill_switch()
        tag = line.partition(b" ")[0]
        return tag + b" BAD " + _MARK + b"\r\n"

    srv = _Server(_IMAP_GREETING, stop_then_bye)
    try:
        assert fetch_imap("127.0.0.1", "u", _PW, port=srv.port, use_ssl=False).stopped
    finally:
        srv.close()


def test_the_route_answers_a_server_error_as_a_502_in_its_fixed_words(monkeypatch):
    from fastapi import HTTPException

    import src.api.ingestion as ingestion

    def refuse(*a, **k):
        raise email_mod._server_error("mail.example", 993, "login")

    monkeypatch.setattr(ingestion, "fetch_imap", refuse)
    monkeypatch.setattr(ingestion, "_get_source", lambda db, sid: object())
    req = ingestion.IngestEmailRequest(host="mail.example", user="u", password=_PW)
    with pytest.raises(HTTPException) as info:
        ingestion.ingest_email_endpoint(1, req, db=None)
    assert info.value.status_code == 502 and "refused the login" in info.value.detail and _PW not in info.value.detail


def _handle(exc: BaseException) -> str:
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/api/whatever", "headers": []}
    resp = asyncio.new_event_loop().run_until_complete(main.unhandled_exception_handler(Request(scope), exc))
    assert resp.status_code == 500
    import json

    return json.loads(resp.body)["detail"]


def test_the_catch_all_500_is_cut_at_its_limit():
    detail = _handle(RuntimeError("x" * 350_000))
    assert len(detail) == main.UNHANDLED_DETAIL_LIMIT == 300
    assert detail.startswith("internal error: ") and detail.endswith("…")
    assert _handle(RuntimeError("short")) == "internal error: short"


def test_the_cut_comes_after_the_scrub(monkeypatch):
    """A passphrase that straddles the cut is taken out whole first, so no piece of it is left at the end."""
    import src.monitoring.secret_scrub as secret_scrub

    held = "held-passphrase-r653-" + "k" * 40
    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: (held,))
    detail = _handle(RuntimeError("y" * 260 + held + "z" * 200))  # unscrubbed, the cut at 300 would fall inside the passphrase
    assert "held-" not in detail and "kkkk" not in detail
    assert "redacted" in detail and "zzzz" in detail  # the scrub ran first: what followed the passphrase moved up into the 300
    assert len(detail) <= main.UNHANDLED_DETAIL_LIMIT


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(main, "_serving_loop_checked", True)
    monkeypatch.setattr(main, "_serving_gate_logged", False)
    monkeypatch.setattr(main, "_serving_check_failure_logged", False)
    monkeypatch.delenv("OO_AIRPLANE_SOCKET_GUARD", raising=False)
    return monkeypatch


def test_a_gate_check_that_raises_is_the_fixed_503_without_its_text(gate, caplog):
    from fastapi.testclient import TestClient

    def boom():
        raise RuntimeError("ZQXR653 inside the gate")

    gate.setattr(ap, "is_armed", boom)
    client = TestClient(main.app)
    with caplog.at_level("ERROR", logger=main.logger.name):
        for _ in range(2):
            r = client.get("/unlock")
            assert r.status_code == 503 and r.json() == {"detail": main.SERVING_GATE_REFUSAL}
    lines = [rec.getMessage() for rec in caplog.records]
    assert not any("ZQXR653" in line for line in lines)
    assert sum("check failed (RuntimeError)" in line for line in lines) == 1


def test_a_capability_list_imaplib_cannot_decode_is_named_in_fixed_words():
    """Security read A on R653: a byte past ASCII in the capability list fails imaplib's own decode (UnicodeDecodeError, not its
    error class), which reached the catch-all 500; it is the same fixed-words greeting failure."""
    srv = _Server(b"* OK [CAPABILITY IMAP4rev1 STARTTLS ZQXR653\xff] hi\r\n", _imap)
    try:
        assert "before logging in; no password was sent" in _refused(fetch_imap, srv, use_ssl=False)
    finally:
        srv.close()


class _ImapStoppedMidFetch:
    """An injected IMAP connection: the first message comes back, then the Stop engages and the server's error follows."""

    def __init__(self):
        self.fetches = 0

    def login(self, *a):
        return "OK", [b""]

    def select(self, *a):
        return "OK", [b"2"]

    def search(self, *a):
        return "OK", [b"1 2"]

    def fetch(self, mid, *a):
        self.fetches += 1
        if self.fetches == 1:
            return "OK", [(b"1 (RFC822 {5}", b"first")]
        from src.ingest import activate_kill_switch

        activate_kill_switch()
        raise email_mod.imaplib.IMAP4.abort("ZQXR653 " + _MARK.decode())


class _PopStoppedMidRetr:
    def list(self):
        return b"+OK", [b"1 5", b"2 5"], 10

    def retr(self, i):
        if i == 1:
            return b"+OK", [b"first"], 5
        from src.ingest import activate_kill_switch

        activate_kill_switch()
        raise email_mod.poplib.error_proto(b"-ERR " + _MARK)


def test_a_stop_still_wins_over_a_server_error_after_the_login():
    """Security read A on R653: the Stop checks in the new post-login handlers; what was fetched is kept, no error is raised."""
    raws = fetch_imap("mail.example", "u", _PW, conn=_ImapStoppedMidFetch())
    assert raws.stopped and list(raws) == [b"first"]
    clear_kill_switch()
    raws = fetch_pop3("mail.example", "u", _PW, conn=_PopStoppedMidRetr())
    assert raws.stopped and list(raws) == [b"first"]


def test_a_server_error_after_the_login_without_a_stop_is_named_in_fixed_words():
    class _Bad(_ImapStoppedMidFetch):
        def fetch(self, mid, *a):
            raise email_mod.imaplib.IMAP4.error("ZQXR653")

    with pytest.raises(MailboxServerError, match="after logging in") as info:
        fetch_imap("mail.example", "u", _PW, conn=_Bad())
    assert "ZQXR653" not in str(info.value)


def test_a_reopened_gate_logs_a_later_failing_check_again(gate, caplog):
    from fastapi.testclient import TestClient

    def boom():
        raise RuntimeError("ZQXR653")

    client = TestClient(main.app)
    with caplog.at_level("ERROR", logger=main.logger.name):
        gate.setattr(ap, "is_armed", boom)
        assert client.get("/unlock").status_code == 503
        gate.setattr(ap, "is_armed", lambda: True)
        gate.setattr(ap, "removed_while_installed", lambda: [])
        assert client.get("/unlock").status_code == 200
        gate.setattr(ap, "is_armed", boom)
        assert client.get("/unlock").status_code == 503
    assert sum("check failed (RuntimeError)" in r.getMessage() for r in caplog.records) == 2
