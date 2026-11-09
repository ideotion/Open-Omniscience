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
    assert info.value.__context__ is None and info.value.__cause__ is None  # nothing chained holds the server's line (delta read 2)
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


def test_the_server_error_carries_no_chained_exception():
    """Security read B on R653: ``from None``, so no traceback prints imaplib's or poplib's error with the server's line."""

    class _Bad(_ImapStoppedMidFetch):
        def fetch(self, mid, *a):
            raise email_mod.imaplib.IMAP4.error("ZQXR653")

    with pytest.raises(MailboxServerError) as info:
        fetch_imap("mail.example", "u", _PW, conn=_Bad())
    assert info.value.__cause__ is None and info.value.__context__ is None

    class _PopBad(_PopStoppedMidRetr):
        def retr(self, i):
            raise email_mod.poplib.error_proto(b"-ERR ZQXR653")

    with pytest.raises(MailboxServerError, match="after logging in") as info:
        fetch_pop3("mail.example", "u", _PW, conn=_PopBad())
    assert "ZQXR653" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_a_stop_still_wins_over_a_pop3_error_greeting(monkeypatch):
    """Security read B on R653: the Stop check in the POP3 constructor's new handler, with the Stop landing as the -ERR is read."""
    import poplib

    from src.ingest import activate_kill_switch

    class _Stopping:
        def __init__(self, *a, **k):
            activate_kill_switch()
            raise poplib.error_proto(b"-ERR " + _MARK)

    monkeypatch.setattr(email_mod, "_stop_aware", lambda cls: _Stopping)
    assert fetch_pop3("127.0.0.1", "u", _PW, port=1, use_ssl=False).stopped


def test_a_preauth_greeting_on_the_tls_port_is_not_called_a_refused_login(pki, trust_test_ca):
    """Security read B on R653: imaplib refuses LOGIN itself after PREAUTH, so "refused the login" would blame the password."""
    srv = _Server(b"* PREAUTH [CAPABILITY IMAP4rev1] hi\r\n", _imap, tls=pki.server)
    try:
        text = _refused(fetch_imap, srv, use_ssl=True)
        assert "already logged in (PREAUTH)" in text and "no password was sent" in text
        assert not any(b"LOGIN" in line for line in srv.received)
    finally:
        srv.close()


def test_a_capability_list_after_starttls_imaplib_cannot_decode_is_named_in_fixed_words(pki, trust_test_ca):
    """Delta read 1 on R653: the main block's decode-error branch, where the capability list after the upgrade is read."""
    seen = {"capability": 0}

    def script(line: bytes) -> bytes | None:
        tag, _, rest = line.partition(b" ")
        if rest.split(b" ", 1)[0].upper() == b"CAPABILITY":
            seen["capability"] += 1
            if seen["capability"] == 2:
                return b"* CAPABILITY IMAP4rev1 ZQXR653\xff\r\n" + tag + b" OK done\r\n"
        return _imap(line)

    srv = _Server(_IMAP_GREETING, script, starttls=pki.server)
    try:
        assert "before logging in; no password was sent" in _refused(fetch_imap, srv, use_ssl=False)
        assert seen["capability"] == 2 and not any(b"LOGIN" in line for line in srv.received)
    finally:
        srv.close()


def test_a_folder_name_imaplib_cannot_encode_is_not_blamed_on_the_server():
    """Delta read 1 on R653: only the server's bytes failing to DECODE are the server's; a local encode failure is not named as one."""

    class _Encoding(_ImapStoppedMidFetch):
        def select(self, *a):  # imaplib encodes a command's arguments as ASCII on this side, before anything is sent
            raise UnicodeEncodeError("ascii", "Boîte", 2, 3, "ordinal not in range(128)")

    with pytest.raises(UnicodeEncodeError):
        fetch_imap("mail.example", "u", _PW, folder="Boîte", conn=_Encoding())


@pytest.mark.parametrize(
    "greeting",
    [b"* BYE " + _MARK + b"\r\n", b"* OK [CAPABILITY IMAP4rev1 STARTTLS ZQXR653\xff] hi\r\n"],
    ids=["bye", "undecodable-capability"],
)
def test_the_route_and_the_job_show_the_fixed_words_for_a_real_pull(monkeypatch, greeting):
    """Delta read 2 on R653: ``http_detail`` reads the ``__context__`` chain, so a refusal raised inside the handler showed the
    imaplib or decode error it replaced instead of its own words. End to end, through the real pull: the route and the job."""
    from fastapi import HTTPException

    import src.api.ingestion as ingestion
    from src.monitoring.secret_scrub import http_detail

    srv = _Server(greeting, _imap)
    try:
        real = ingestion.fetch_imap
        monkeypatch.setattr(ingestion, "fetch_imap", lambda *a, **k: real(*a, port=srv.port, **k))
        monkeypatch.setattr(ingestion, "_get_source", lambda db, sid: object())
        req = ingestion.IngestEmailRequest(host="127.0.0.1", user="u", password=_PW, use_ssl=False)
        with pytest.raises(HTTPException) as info:
            ingestion.ingest_email_endpoint(1, req, db=None)
        assert info.value.status_code == 502
        assert "before logging in; no password was sent" in info.value.detail and "ZQXR653" not in info.value.detail
    finally:
        srv.close()
    srv = _Server(greeting, _imap)
    try:
        with pytest.raises(MailboxServerError) as raised:
            fetch_imap("127.0.0.1", "u", _PW, port=srv.port, use_ssl=False)
        detail = http_detail(raised.value)
        assert "before logging in; no password was sent" in detail and "Unicode" not in detail and "ZQXR653" not in detail
    finally:
        srv.close()


@pytest.mark.parametrize(
    ("fn", "greeting", "script", "words"),
    [
        (fetch_imap, _IMAP_GREETING, _answering(_imap, b"STARTTLS", b"TAG BAD " + _MARK + b"\r\n"), "refused STARTTLS"),
        (fetch_pop3, _POP_GREETING, _answering(_pop, b"STLS", b"-ERR " + _MARK + b"\r\n", pop=True), "refused STLS"),
        (
            fetch_pop3,
            _POP_GREETING,
            _answering(_pop, b"CAPA", b"+OK\r\nSTLS\r\nZQXR653\xff\r\n.\r\n", pop=True),
            "gave no usable answer to CAPA",
        ),
    ],
    ids=["imap-starttls-bad", "pop3-stls-err", "pop3-capa-undecodable"],
)
def test_a_starttls_refusal_carries_no_chained_server_error(fn, greeting, script, words):
    """Delta re-read 3 on R653: a refusal raised inside the ``except`` kept imaplib's or poplib's error (or poplib's decode error,
    whose ``.object`` is the server's bytes) as its ``__context__``, and ``http_detail`` showed that instead of the refusal's words."""
    from src.ingest.email import MailboxStarttlsError
    from src.monitoring.secret_scrub import http_detail

    srv = _Server(greeting, script)
    try:
        with pytest.raises(MailboxStarttlsError) as info:
            fn("127.0.0.1", "u", _PW, port=srv.port, use_ssl=False)
        assert info.value.__context__ is None and info.value.__cause__ is None
        detail = http_detail(info.value)
        assert words in detail and "ZQXR653" not in detail and "Unicode" not in detail
    finally:
        srv.close()


def test_a_host_name_python_cannot_encode_is_not_blamed_on_the_server():
    """Delta re-read 3 on R653: a label over 63 characters fails IDNA encoding on this side, before any connection."""
    with pytest.raises(UnicodeError) as info:
        fetch_imap("a" * 64 + ".example", "u", _PW, use_ssl=False)
    assert not isinstance(info.value, MailboxServerError)


def test_a_stop_during_the_logout_after_a_server_error_still_wins(pki, trust_test_ca):
    """Delta re-read 4 on R653: the error is decided, then the Stop lands during the LOGOUT; the pull ends as the Stop."""
    from src.ingest import activate_kill_switch

    def script(line: bytes) -> bytes | None:
        tag, _, rest = line.partition(b" ")
        cmd = rest.split(b" ", 1)[0].upper()
        if cmd == b"SEARCH":
            return tag + b" BAD " + _MARK + b"\r\n"
        if cmd == b"LOGOUT":
            activate_kill_switch()
        return _imap(line)

    srv = _Server(_IMAP_GREETING, script, starttls=pki.server)
    try:
        assert fetch_imap("127.0.0.1", "u", _PW, port=srv.port, use_ssl=False).stopped
    finally:
        srv.close()
