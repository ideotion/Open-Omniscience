"""
Tests for email ingestion (Action Plan Phase 4).

Emails become searchable Article rows in the unified corpus. The parse + store
path is tested with canned RFC822 bytes (no mail server); the IMAP fetch is
tested with an injected fake connection.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source
from src.ingest.email import (
    fetch_imap,
    ingest_emails,
    ingest_eml_directory,
    parse_email,
    sender_origin_ip,
)


def _msg_with_received(received_lines: bytes) -> bytes:
    return (
        b"From: News <n@news.example>\r\n"
        b"To: me@example.com\r\n"
        b"Subject: With a Received chain\r\n"
        b"Message-ID: <rc@news.example>\r\n"
        b"Date: Mon, 05 Jan 2026 18:00:00 +0000\r\n"
        + received_lines
        + b"Content-Type: text/plain; charset=utf-8\r\n\r\nBody here.\r\n"
    )

PLAIN = b"""From: Reporter <r@news.example>
To: me@example.com
Subject: Budget vote tonight
Message-ID: <abc123@news.example>
Date: Mon, 05 Jan 2026 18:00:00 +0000
Content-Type: text/plain; charset=utf-8

The city council will vote on the budget tonight after a long debate.
"""

HTML = b"""From: News <n@news.example>
Subject: Markets update
Message-ID: <def456@news.example>
Date: Tue, 06 Jan 2026 09:00:00 +0000
Content-Type: text/html; charset=utf-8

<html><body><h1>Markets</h1><p>Rare earth prices climbed today.</p></body></html>
"""

# A real-world-noisy HTML newsletter: <style>/<script> blocks, an Outlook/MSO
# conditional comment, a plain comment, and undecoded entities (field test 2026-06-20).
HTML_NOISY = b"""From: News <n@news.example>
Subject: Noisy newsletter
Message-ID: <noisy@news.example>
Date: Wed, 29 Apr 2026 21:05:00 +0000
Content-Type: text/html; charset=utf-8

<html><head><style>*{box-sizing:border-box} @media (max-width:520px){.x{display:none}}</style>
<script>var x=1;</script></head>
<body>
<!--[if mso]><table><tr><td>Outlook only</td></tr></table><![endif]-->
<!-- a plain comment -->
<h1>DeepSeek&rsquo;s new bet</h1>
<p>Parallel ecosystems&#8202;in China&nbsp;and US.&copy; 2026</p>
</body></html>
"""


def test_strip_html_drops_style_script_comments_and_decodes_entities():
    # The field-test bug: CSS from <style>, JS from <script>, comment fragments and
    # raw HTML entities leaked into the stored body. None of that may survive.
    b = parse_email(HTML_NOISY).body_text
    assert "box-sizing" not in b and "@media" not in b and "var x" not in b, "CSS/JS leaked"
    assert "-->" not in b and "Outlook only" not in b and "plain comment" not in b, "comment leaked"
    assert not any(e in b for e in ("&#8202;", "&nbsp;", "&copy;", "&rsquo;")), "entities not decoded"
    assert "DeepSeek’s new bet" in b and "© 2026" in b, "entities must decode to characters"
    assert "Parallel ecosystems in China and US." in b, "spaces must collapse; real text intact"


def test_parse_plain_email():
    p = parse_email(PLAIN)
    assert p.subject == "Budget vote tonight"
    assert p.from_addr == "Reporter <r@news.example>"
    assert "budget tonight" in p.body_text
    assert p.message_id == "<abc123@news.example>"
    assert p.date is not None


def test_sender_origin_ip_takes_first_public_hop_skipping_private():
    import email as _email

    # Chain is newest→oldest as written; the oldest hop (last line) carries the true
    # sender's public IP, an internal relay (private) sits above it and must be skipped.
    raw = _msg_with_received(
        b"Received: from relay.recipient.com (relay.recipient.com [10.0.0.2])\r\n"
        b"    by mx.recipient.com; Mon, 05 Jan 2026 18:00:02 +0000\r\n"
        b"Received: from mail.sender.example (mail.sender.example [8.8.8.8])\r\n"
        b"    by relay.recipient.com; Mon, 05 Jan 2026 18:00:01 +0000\r\n"
    )
    ip, reason = sender_origin_ip(_email.message_from_bytes(raw))
    assert ip == "8.8.8.8" and reason is None
    # and it flows through parse_email onto the ParsedEmail
    p = parse_email(raw)
    assert p.sender_ip == "8.8.8.8"


def test_sender_origin_ip_ipv6_and_only_private_and_stripped():
    import email as _email

    ipv6 = _msg_with_received(
        b"Received: from s (s [IPv6:2606:4700:4700::1111]) by mx; Mon, 05 Jan 2026 18:00:00 +0000\r\n"
    )
    ip, reason = sender_origin_ip(_email.message_from_bytes(ipv6))
    assert ip == "2606:4700:4700::1111" and reason is None

    only_private = _msg_with_received(
        b"Received: from a (a [192.168.1.9]) by mx; Mon, 05 Jan 2026 18:00:00 +0000\r\n"
    )
    ip2, reason2 = sender_origin_ip(_email.message_from_bytes(only_private))
    assert ip2 is None and "private" in reason2

    stripped = parse_email(PLAIN)  # no Received headers at all
    assert stripped.sender_ip is None and "Received" in (stripped.sender_ip_reason or "")


def test_ingest_stores_sender_ip_on_the_article():
    s = _db()
    src = s.query(Source).first()
    raw = _msg_with_received(
        b"Received: from mail.sender.example (mail.sender.example [8.8.8.8])\r\n"
        b"    by mx.recipient.com; Mon, 05 Jan 2026 18:00:01 +0000\r\n"
    )
    ingest_emails(s, src, [raw])
    art = s.query(Article).filter_by(title="With a Received chain").one()
    assert art.server_ip == "8.8.8.8"
    assert art.ip_observed_at is not None
    assert "Received chain" in art.server_ip_reason  # deduced, honest
    # a message with no public hop stores no IP but an honest reason
    ingest_emails(s, src, [PLAIN])
    plain = s.query(Article).filter_by(title="Budget vote tonight").one()
    assert plain.server_ip is None and plain.ip_observed_at is None and plain.server_ip_reason
    s.close()


def test_parse_respects_declared_charset():
    # A windows-1252 / latin-1 body must decode correctly, not become mojibake.
    raw = (
        b"From: n@news.example\r\nSubject: Caf\xe9\r\nMessage-ID: <c@x>\r\n"
        b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\n"
        b"Caf\xe9 r\xe9sum\xe9 na\xefve\r\n"
    )
    p = parse_email(raw)
    assert "Café résumé naïve" in p.body_text
    assert "�" not in p.body_text  # no replacement chars


def test_parse_html_email_strips_tags():
    p = parse_email(HTML)
    assert "Rare earth prices climbed" in p.body_text
    assert "<p>" not in p.body_text


def _db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Mailbox", domain="news.example"))
    s.commit()
    return s


def test_ingest_emails_stores_and_dedups():
    s = _db()
    src = s.query(Source).first()
    tally = ingest_emails(s, src, [PLAIN, HTML])
    assert tally["stored"] == 2
    # both are searchable Article rows
    assert s.query(Article).count() == 2
    art = s.query(Article).filter_by(title="Budget vote tonight").one()
    assert art.author == "Reporter <r@news.example>"
    assert art.canonical_url == "imap:<abc123@news.example>"
    # re-ingesting is a dedup no-op
    again = ingest_emails(s, src, [PLAIN])
    assert again["duplicate"] == 1
    assert s.query(Article).count() == 2
    s.close()


class _FakeIMAP:
    """Minimal imaplib-like object for testing fetch_imap."""

    def __init__(self, messages):
        self._messages = messages  # list of raw bytes

    def select(self, folder):
        return ("OK", [b"2"])

    def search(self, charset, criterion):
        ids = b" ".join(str(i + 1).encode() for i in range(len(self._messages)))
        return ("OK", [ids])

    def fetch(self, mid, spec):
        idx = int(mid) - 1
        return ("OK", [(b"x", self._messages[idx])])


def test_fetch_imap_with_injected_connection():
    conn = _FakeIMAP([PLAIN, HTML])
    raws = fetch_imap("imap.example", "u", "p", conn=conn, limit=10)
    assert len(raws) == 2
    assert raws[0].startswith(b"From: Reporter")


# --- Anonymisation at ingest (recipient protection) ------------------------- #

RCPT = b"""From: Daily <news@publisher.example>
To: jane.doe@personal.example
Subject: Hello jane.doe@personal.example
Message-ID: <r1@publisher.example>
Date: Wed, 07 Jan 2026 09:00:00 +0000
Content-Type: text/plain; charset=utf-8

Hi jane.doe@personal.example, your weekly digest is ready.
"""

TRACK = b"""From: News <n@publisher.example>
Subject: Markets
Message-ID: <t1@publisher.example>
Date: Tue, 06 Jan 2026 09:00:00 +0000
Content-Type: text/plain; charset=utf-8

Read https://publisher.example/a?mc_eid=SECRET&id=9 and then
https://x.us2.list-manage.com/track/click?e=ME today.
"""


def test_recipient_is_redacted_and_never_stored():
    p = parse_email(RCPT)
    # the recipient address must not survive anywhere we store
    assert "jane.doe@personal.example" not in p.subject
    assert "jane.doe@personal.example" not in p.body_text
    assert "[recipient]" in p.body_text
    assert p.redactions >= 2
    # the sender is recipient-safe and kept
    assert p.from_addr == "Daily <news@publisher.example>"


UNWRAP = b"""From: News <n@publisher.example>
Subject: Recovered link
Message-ID: <unwrap1@publisher.example>
Date: Tue, 06 Jan 2026 09:00:00 +0000
Content-Type: text/plain; charset=utf-8

See https://click.tracker.example/redirect?url=https%3A%2F%2Freal-news.example%2Fstory%3Fp%3D1 for details.
"""


def test_newsletter_links_seed_article_link_rows_recovered_only():
    """SOURCE-MANAGEMENT ASKS ruling #1: cleaned newsletter links must become
    ArticleLink rows -- but ONLY fully-recovered destinations. A tracker-wrapped
    link whose destination could not be resolved (list-manage.com here) stores
    wrapper-domain-only and must NEVER seed a source; an ordinary cleaned link
    must."""
    s = _db()
    src = s.query(Source).first()
    tally = ingest_emails(s, src, [TRACK])
    assert tally["stored"] == 1
    art = s.query(Article).filter_by(title="Markets").one()
    links = s.query(ArticleLink).filter_by(article_id=art.id).all()
    normalized = {ln.normalized_url for ln in links}
    # the clean (recipient-param-stripped) link seeds a row
    assert any("publisher.example/a" in nu for nu in normalized)
    # the unrecoverable tracker wrapper (wrapper-domain-only) must NOT seed one
    assert not any("list-manage.com" in nu for nu in normalized)
    for ln in links:
        assert ln.link_type == "external"
    s.close()


def test_newsletter_unwrapped_recovered_link_seeds_the_real_destination():
    """A redirect wrapper whose destination is embedded (no network needed) is
    RECOVERED -- the ArticleLink row must point at the recovered destination's own
    domain, never at the wrapper host."""
    s = _db()
    src = s.query(Source).first()
    tally = ingest_emails(s, src, [UNWRAP])
    assert tally["stored"] == 1
    art = s.query(Article).filter_by(title="Recovered link").one()
    links = s.query(ArticleLink).filter_by(article_id=art.id).all()
    assert len(links) == 1
    assert links[0].normalized_url.startswith("https://real-news.example/story")
    assert "click.tracker.example" not in links[0].normalized_url
    s.close()


def test_newsletter_link_indexing_disabled_by_oo_no_index(monkeypatch):
    monkeypatch.setenv("OO_NO_INDEX", "1")
    s = _db()
    src = s.query(Source).first()
    tally = ingest_emails(s, src, [TRACK])
    assert tally["stored"] == 1
    assert s.query(ArticleLink).count() == 0
    s.close()


def test_links_are_detracked_on_ingest():
    s = _db()
    src = s.query(Source).first()
    tally = ingest_emails(s, src, [TRACK])
    assert tally["stored"] == 1
    art = s.query(Article).filter_by(title="Markets").one()
    assert "mc_eid" not in art.content
    assert "SECRET" not in art.content
    assert "ME" not in art.content  # recipient token inside the wrapped link is gone
    assert "[tracked link -> https://x.us2.list-manage.com]" in art.content
    assert tally["tracker_params_stripped"] >= 1
    assert tally["trackers_flagged"] == 1
    s.close()


def _eml(subject: str, body: str, mid: str) -> bytes:
    return (
        f"From: N <n@news.example>\nSubject: {subject}\n"
        f"Message-ID: <{mid}@news.example>\nDate: Mon, 05 Jan 2026 18:00:00 +0000\n"
        f"Content-Type: text/plain; charset=utf-8\n\n{body}\n"
    ).encode()


def test_ingest_emails_batched_commit_dedups_across_batches():
    # Batched commits (perf) must keep the exact dedup tally. m3 shares m1's body
    # (=> same content hash) but a different Message-ID, so it dedups on the hash.
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    src = Source(name="N", domain="nl.test")
    s.add(src)
    s.commit()
    msgs = [
        _eml("A", "body one about elections", "m1"),
        _eml("B", "body two about inflation", "m2"),
        _eml("A2", "body one about elections", "m3"),  # dup hash of m1
        _eml("C", "body three about drought", "m4"),
    ]
    tally = ingest_emails(s, src, msgs, commit_batch=2)
    assert tally["stored"] == 3 and tally["duplicate"] == 1
    assert s.query(Article).count() == 3  # actually committed
    # A later call dedups against the DB too.
    again = ingest_emails(s, src, [msgs[0]], commit_batch=2)
    assert again["stored"] == 0 and again["duplicate"] == 1


def test_batched_commit_falls_back_per_message_on_collision():
    # autoflush OFF -> the in-batch existence check can't see a same-hash sibling, so
    # the batch flush hits the unique index; the per-message fallback must store one
    # and count the other a duplicate (NO data loss — the maintainer's standing rule).
    engine = create_engine("sqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True, autoflush=False)()
    src = Source(name="N", domain="nl.test")
    s.add(src)
    s.commit()
    msgs = [_eml("A", "identical body text here", "m1"), _eml("B", "identical body text here", "m2")]
    tally = ingest_emails(s, src, msgs, commit_batch=10)  # both in one batch
    assert tally["stored"] == 1 and tally["duplicate"] == 1
    assert s.query(Article).count() == 1


def test_is_integrity_error_recognizes_a_sqlcipher3_style_unwrapped_exception(monkeypatch):
    """Audit finding 2026-07-17: on the ENCRYPTED store a unique-constraint collision
    can surface as a RAW ``sqlcipher3``/``sqlite3`` ``IntegrityError`` that SQLAlchemy
    does NOT wrap as ``sqlalchemy.exc.IntegrityError`` -- the same cross-driver class
    divergence ``src/database/write.py``'s ``is_locked_error`` and
    ``src/backup/merge.py``'s ``_db_integrity_error_types`` already had to fix. A
    narrow ``except IntegrityError`` (the sqlalchemy.exc one) would silently never
    catch this, letting a benign duplicate escape as an unhandled exception that
    aborts the whole import batch."""
    import sys
    import types

    from src.ingest.email import _is_integrity_error

    class _FakeSqlcipherIntegrityError(Exception):
        pass

    import sqlite3
    assert not issubclass(_FakeSqlcipherIntegrityError, sqlite3.IntegrityError), (
        "the fixture must be a genuinely UNRELATED class -- the whole point of the bug"
    )

    fake_dbapi2 = types.SimpleNamespace(IntegrityError=_FakeSqlcipherIntegrityError)
    fake_pkg = types.SimpleNamespace(dbapi2=fake_dbapi2)
    monkeypatch.setitem(sys.modules, "sqlcipher3", fake_pkg)
    monkeypatch.setitem(sys.modules, "sqlcipher3.dbapi2", fake_dbapi2)

    exc = _FakeSqlcipherIntegrityError("UNIQUE constraint failed: articles.hash")
    assert _is_integrity_error(exc) is True
    assert _is_integrity_error(RuntimeError("disk full")) is False


def test_commit_one_classifies_a_sqlcipher3_style_collision_as_a_duplicate_not_a_crash(monkeypatch):
    """End-to-end via the real _flush() -> _commit_one redo path: force _flush()'s
    primary session.commit() to fail once (entering its per-message redo loop), then
    have run_write_with_retry (what _commit_one actually calls) raise the driver's
    OWN (sqlcipher3-style) IntegrityError instance -- never sqlalchemy's wrapped one
    -- proving the real code path, not just the _is_integrity_error unit, handles the
    cross-driver case without crashing the batch."""
    import sys
    import types

    import src.ingest.email as email_mod

    class _FakeSqlcipherIntegrityError(Exception):
        pass

    fake_dbapi2 = types.SimpleNamespace(IntegrityError=_FakeSqlcipherIntegrityError)
    fake_pkg = types.SimpleNamespace(dbapi2=fake_dbapi2)
    monkeypatch.setitem(sys.modules, "sqlcipher3", fake_pkg)
    monkeypatch.setitem(sys.modules, "sqlcipher3.dbapi2", fake_dbapi2)

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    src = Source(name="N", domain="nl.test")
    s.add(src)
    s.commit()

    # _flush()'s own primary commit fails ONCE with the fake sqlcipher3-style
    # exception, forcing the per-message redo loop; run_write_with_retry (what
    # _commit_one calls for each pending message) is then mocked the same way, so
    # every classification decision below flows through the real dispatch code.
    real_commit = s.commit
    calls = {"n": 0}

    def _commit_once_then_real(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _FakeSqlcipherIntegrityError("UNIQUE constraint failed: articles.hash")
        return real_commit(*a, **kw)

    monkeypatch.setattr(s, "commit", _commit_once_then_real)

    def _boom(work, *, session, label):  # noqa: ARG001
        raise _FakeSqlcipherIntegrityError("UNIQUE constraint failed: articles.hash")

    monkeypatch.setattr(email_mod, "run_write_with_retry", _boom)

    tally = email_mod.ingest_emails(s, src, [_eml("A", "some body text", "m1")])
    assert tally["duplicate"] == 1  # routed through _commit_one's redo path, not a crash
    assert tally["stored"] == 0
    assert tally["errors"] == 0  # never miscounted as a lock/db error either


def test_commit_one_reraises_a_genuinely_unexpected_exception(monkeypatch):
    """A failure that is neither a lock nor an integrity violation must still surface
    loudly -- never be silently swallowed and miscounted as a duplicate."""
    import src.ingest.email as email_mod

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    src = Source(name="N", domain="nl.test")
    s.add(src)
    s.commit()

    real_commit = s.commit
    calls = {"n": 0}

    def _commit_once_then_real(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        return real_commit(*a, **kw)

    monkeypatch.setattr(s, "commit", _commit_once_then_real)

    def _boom(work, *, session, label):  # noqa: ARG001
        raise RuntimeError("disk full")

    monkeypatch.setattr(email_mod, "run_write_with_retry", _boom)

    import pytest
    with pytest.raises(RuntimeError, match="disk full"):
        email_mod.ingest_emails(s, src, [_eml("A", "some body text", "m1")])


def test_same_body_different_message_id_dedups_on_hash():
    # Field test 2026-06-24: a 5 GB folder of repeated newsletters failed the WHOLE import
    # with "UNIQUE constraint failed: articles.hash". `articles.hash` is the ONLY unique
    # column (canonical_url is not), so two emails with the SAME body but DIFFERENT
    # Message-IDs must dedup on the content hash ALONE — even when several land in ONE
    # uncommitted batch. (The old (hash, canonical) tuple key let them all in and collide
    # at the flush insertmany.) Expect: stored once, the rest counted duplicate, NO raise,
    # no errors, no row lost.
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True, autoflush=False)()
    src = Source(name="N", domain="nl.test")
    s.add(src)
    s.commit()
    msgs = [
        _eml("Original", "the council voted on the budget tonight", "m1"),
        _eml("Forwarded copy", "the council voted on the budget tonight", "m2"),  # same body
        _eml("Third copy", "the council voted on the budget tonight", "m3"),      # same body
        _eml("Unrelated", "a wholly separate story about the drought", "m4"),
    ]
    tally = ingest_emails(s, src, msgs, commit_batch=100)  # ALL in one batch
    assert tally["stored"] == 2 and tally["duplicate"] == 2
    assert tally["errors"] == 0
    assert s.query(Article).count() == 2
    s.close()


def test_ingest_eml_directory_reads_files(tmp_path):
    (tmp_path / "one.eml").write_bytes(PLAIN)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "two.eml").write_bytes(HTML)
    s = _db()
    src = s.query(Source).first()
    tally = ingest_eml_directory(s, src, tmp_path)
    assert tally["stored"] == 2
    assert s.query(Article).count() == 2
    s.close()


def test_eml_import_makes_no_network_call(tmp_path, monkeypatch):
    # Build the in-memory DB BEFORE forbidding sockets (sqlite opens none, but be safe).
    s = _db()
    src = s.query(Source).first()
    (tmp_path / "a.eml").write_bytes(PLAIN)
    (tmp_path / "b.eml").write_bytes(TRACK)

    import socket

    def _forbidden(*_a, **_k):  # pragma: no cover - only runs if the rule is violated
        raise AssertionError("import attempted a network connection")

    monkeypatch.setattr(socket, "socket", _forbidden)
    tally = ingest_eml_directory(s, src, tmp_path)
    assert tally["stored"] == 2
    s.close()


def test_newsletters_import_endpoint_zero_network(monkeypatch):
    """The Settings .eml importer (POST /api/newsletters/import): uploaded files are
    parsed + anonymised + stored under ONE dedicated, DISABLED newsletter source, with
    an honest tally — and the WHOLE request path opens NO socket (the binding invariant:
    N files => 0 sockets; a tracker pixel/link is never followed)."""
    import socket

    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import SessionLocal

    real_socket = socket.socket

    def _forbidden(*a, **k):  # any outbound socket during import is a bug
        raise AssertionError("the .eml import path opened a network socket")

    with TestClient(app) as c:
        monkeypatch.setattr(socket, "socket", _forbidden)
        try:
            r = c.post(
                "/api/newsletters/import",
                files=[
                    ("files", ("budget.eml", PLAIN, "message/rfc822")),
                    ("files", ("markets.eml", HTML, "message/rfc822")),
                    ("files", ("notes.txt", b"not an email", "text/plain")),
                ],
            )
        finally:
            monkeypatch.setattr(socket, "socket", real_socket)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "Imported newsletters (.eml)"
    tally = body["tally"]
    assert tally["stored"] == 2          # the two real .eml; the .txt is skipped
    assert tally["skipped_non_eml"] == 1
    assert body["received"] == 3

    # The dedicated bucket exists and is DISABLED (the scheduler never scrapes it).
    s = SessionLocal()
    try:
        src = s.query(Source).filter_by(domain="newsletters.import.local").first()
        assert src is not None and src.enabled is False
    finally:
        s.close()

    # Re-importing the SAME files dedups (content-hash) — no duplicate corpus rows.
    with TestClient(app) as c:
        r2 = c.post(
            "/api/newsletters/import",
            files=[("files", ("budget.eml", PLAIN, "message/rfc822"))],
        )
    assert r2.json()["tally"]["duplicate"] == 1 and r2.json()["tally"]["stored"] == 0
