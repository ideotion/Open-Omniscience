"""
Tests for email ingestion (Action Plan Phase 4).

Emails become searchable Article rows in the unified corpus. The parse + store
path is tested with canned RFC822 bytes (no mail server); the IMAP fetch is
tested with an injected fake connection.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.ingest.email import (
    fetch_imap,
    ingest_emails,
    ingest_eml_directory,
    parse_email,
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


def test_parse_plain_email():
    p = parse_email(PLAIN)
    assert p.subject == "Budget vote tonight"
    assert p.from_addr == "Reporter <r@news.example>"
    assert "budget tonight" in p.body_text
    assert p.message_id == "<abc123@news.example>"
    assert p.date is not None


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
