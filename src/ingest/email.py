"""
Email / newsletter ingestion into the unified corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Newsletters and mailing-list traffic are first-class sources for investigative
work. Rather than a parallel store, parsed emails become Article rows (with
``author`` = sender, ``published_at`` = Date header), so they are searched,
deduplicated, exported and correlated by exactly the same machinery as web
articles -- the "one unified corpus" principle.

The IMAP connection is injectable so the parse + store path (the deterministic,
valuable part) is fully testable without a live mail server. Privacy: this only
touches mailboxes the operator explicitly configures; nothing leaves the machine.
"""

from __future__ import annotations

import email
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime

from sqlalchemy.orm import Session

from src.database.models import Article, Source
from src.utils.url_utils import generate_content_hash

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    from_addr: str
    date: datetime | None
    body_text: str


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    return re.sub(r"\s+", " ", text).strip()


def _extract_body(msg: Message) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    if msg.is_multipart():
        plain, html = None, None
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain is None:
                plain = part.get_payload(decode=True)
            elif ctype == "text/html" and html is None:
                html = part.get_payload(decode=True)
        if plain:
            return plain.decode(errors="replace").strip()
        if html:
            return _strip_html(html.decode(errors="replace"))
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    text = payload.decode(errors="replace")
    if msg.get_content_type() == "text/html":
        return _strip_html(text)
    return text.strip()


def parse_email(raw: bytes) -> ParsedEmail:
    """Parse an RFC822 message into the fields we store."""
    msg = email.message_from_bytes(raw)
    date = None
    if msg.get("Date"):
        try:
            date = parsedate_to_datetime(msg["Date"])
        except (TypeError, ValueError):
            date = None
    return ParsedEmail(
        message_id=(msg.get("Message-ID") or "").strip() or f"no-id-{generate_content_hash(raw.decode(errors='replace'))[:16]}",
        subject=(msg.get("Subject") or "(no subject)").strip(),
        from_addr=(msg.get("From") or "").strip(),
        date=date,
        body_text=_extract_body(msg),
    )


def fetch_imap(
    host: str,
    user: str,
    password: str,
    *,
    folder: str = "INBOX",
    limit: int = 50,
    use_ssl: bool = True,
    conn=None,
) -> list[bytes]:
    """Fetch up to ``limit`` most recent raw messages from a folder.

    ``conn`` may be injected (an imaplib-like object) for testing; otherwise a real
    SSL IMAP connection is opened.
    """
    if conn is None:  # pragma: no cover - exercised only against a live server
        import imaplib
        conn = imaplib.IMAP4_SSL(host) if use_ssl else imaplib.IMAP4(host)
        conn.login(user, password)
    conn.select(folder)
    typ, data = conn.search(None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return []
    ids = data[0].split()[-limit:]
    raws: list[bytes] = []
    for mid in ids:
        typ, msg_data = conn.fetch(mid, "(RFC822)")
        if typ == "OK" and msg_data and msg_data[0]:
            raws.append(msg_data[0][1])
    return raws


def ingest_emails(session: Session, source: Source, raw_messages: list[bytes]) -> dict[str, int]:
    """Parse and store raw emails as Article rows, deduplicated by content hash."""
    tally = {"stored": 0, "duplicate": 0, "empty": 0}
    for raw in raw_messages:
        parsed = parse_email(raw)
        if not parsed.body_text:
            tally["empty"] += 1
            continue
        content_hash = generate_content_hash(parsed.body_text)
        canonical = f"imap:{parsed.message_id}"
        exists = session.query(Article.id).filter(
            (Article.hash == content_hash) | (Article.canonical_url == canonical)
        ).first()
        if exists:
            tally["duplicate"] += 1
            continue
        now = datetime.now(UTC)
        session.add(Article(
            url=canonical,
            canonical_url=canonical,
            source_id=source.id,
            title=parsed.subject,
            content=parsed.body_text,
            published_at=parsed.date,
            author=parsed.from_addr,
            hash=content_hash,
            word_count=len(parsed.body_text.split()),
            created_at=now,
            updated_at=now,
        ))
        session.commit()
        tally["stored"] += 1
    return tally
