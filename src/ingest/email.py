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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import Article, Source
from src.privacy.link_sanitizer import SanitizeStats, sanitize_text
from src.utils.url_utils import generate_content_hash

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    from_addr: str
    date: datetime | None
    body_text: str
    # Anonymisation outcome. The recipient is NEVER stored; these are only the
    # counts of what anonymisation did, surfaced to the user as honest feedback.
    sanitize: SanitizeStats = field(default_factory=SanitizeStats)
    redactions: int = 0


def _decode_part(part: Message) -> str:
    """Decode a message part's bytes using its declared charset (not just UTF-8).

    Ignoring the charset corrupts every non-UTF-8 newsletter (iso-8859-1,
    windows-1252, ...) into mojibake, poisoning the stored content, its hash, the
    search index and word count.
    """
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, ValueError):
        return payload.decode("utf-8", errors="replace")


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
                plain = part
            elif ctype == "text/html" and html is None:
                html = part
        if plain is not None:
            return _decode_part(plain).strip()
        if html is not None:
            return _strip_html(_decode_part(html))
        return ""
    if msg.get_content_type() == "text/html":
        return _strip_html(_decode_part(msg))
    return _decode_part(msg).strip()


def _header(msg: Message, name: str, default: str = "") -> str:
    """Return a header decoded to a clean str (RFC2047-aware, never a Header object)."""
    raw = msg.get(name)
    if raw is None:
        return default
    try:
        parts = decode_header(str(raw))
        return "".join(
            (b.decode(enc or "utf-8", errors="replace") if isinstance(b, bytes) else b)
            for b, enc in parts
        ).strip()
    except Exception:
        return str(raw).strip()


# Headers that carry the recipient (or a per-recipient token). They are read
# transiently -- ONLY to redact any echo of the recipient address from the stored
# text -- and then discarded. This is the "anonymise at ingest" rule: the corpus
# keeps the sender side, never the subscriber.
_RECIPIENT_HEADERS = ("To", "Cc", "Bcc", "Delivered-To", "X-Original-To")


def _recipient_addresses(msg: Message) -> set[str]:
    """Collect recipient addresses from the message, for redaction only (never stored)."""
    addrs: set[str] = set()
    for name in _RECIPIENT_HEADERS:
        for raw in msg.get_all(name, []):
            for _disp, addr in getaddresses([str(raw)]):
                addr = addr.strip().lower()
                if "@" in addr:
                    addrs.add(addr)
    return addrs


def _redact(text: str, addrs: set[str]) -> tuple[str, int]:
    """Replace any literal recipient address in ``text`` with a marker.

    Conservative on purpose: only the full address is redacted (redacting a bare
    local-part would risk nuking common words). Returns ``(text, count)``.
    """
    if not text or not addrs:
        return text, 0
    count = 0
    out = text
    for addr in addrs:
        out, n = re.subn(re.escape(addr), "[recipient]", out, flags=re.IGNORECASE)
        count += n
    return out, count


def parse_email(raw: bytes) -> ParsedEmail:
    """Parse an RFC822 message into the (anonymised) fields we store.

    The recipient is NEVER stored: To/Cc/... are read only to redact any echo of
    the recipient from the subject and body, then discarded. Links are de-tracked
    (recipient query-tokens stripped, server-side wrappers flagged) before storage
    so the corpus carries no per-subscriber identifiers. ``from_addr`` is the
    sender, which is recipient-safe and kept.
    """
    msg = email.message_from_bytes(raw)
    date = None
    if msg.get("Date"):
        try:
            date = parsedate_to_datetime(msg["Date"])
        except (TypeError, ValueError):
            date = None
    message_id = _header(msg, "Message-ID")
    if not message_id:
        message_id = f"no-id-{generate_content_hash(raw.decode(errors='replace'))[:16]}"

    subject = _header(msg, "Subject", "(no subject)")
    body_text, stats = sanitize_text(_extract_body(msg))

    recipients = _recipient_addresses(msg)
    subject, r1 = _redact(subject, recipients)
    body_text, r2 = _redact(body_text, recipients)

    return ParsedEmail(
        message_id=message_id,
        subject=subject,
        from_addr=_header(msg, "From"),
        date=date,
        body_text=body_text,
        sanitize=stats,
        redactions=r1 + r2,
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
    """Parse and store raw emails as Article rows, deduplicated by content hash.

    Emails are anonymised at ingest (recipient never stored, recipient echoes
    redacted, links de-tracked). The tally surfaces what anonymisation did so the
    caller can show the user honest counts.
    """
    tally = {
        "stored": 0,
        "duplicate": 0,
        "empty": 0,
        "recipient_redactions": 0,
        "tracker_params_stripped": 0,
        "trackers_flagged": 0,
    }
    for raw in raw_messages:
        parsed = parse_email(raw)
        tally["recipient_redactions"] += parsed.redactions
        tally["tracker_params_stripped"] += parsed.sanitize.params_stripped
        tally["trackers_flagged"] += parsed.sanitize.trackers_wrapped
        if not parsed.body_text:
            tally["empty"] += 1
            continue
        content_hash = generate_content_hash(parsed.body_text)
        canonical = f"imap:{parsed.message_id}"
        exists = (
            session.query(Article.id)
            .filter((Article.hash == content_hash) | (Article.canonical_url == canonical))
            .first()
        )
        if exists:
            tally["duplicate"] += 1
            continue
        now = datetime.now(UTC)
        session.add(
            Article(
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
            )
        )
        try:
            session.commit()
            tally["stored"] += 1
        except IntegrityError:
            # A concurrent/duplicate insert (the unique hash/canonical_url) raced the
            # _exists check. Roll back so the next message isn't aborted, count as dup.
            session.rollback()
            tally["duplicate"] += 1
    return tally


def ingest_eml_files(session: Session, source: Source, paths) -> dict[str, int]:
    """Read ``.eml`` files from local disk and ingest them as Articles.

    Local files only -- this opens no network connection. Unreadable files are
    skipped; duplicate paths (e.g. a case-insensitive filesystem yielding the
    same file as ``.eml`` and ``.EML``) are read once.
    """
    raws: list[bytes] = []
    seen: set[object] = set()
    for p in paths:
        path = Path(p)
        try:
            key: object = path.resolve()
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            raws.append(path.read_bytes())
        except OSError:
            continue
    return ingest_emails(session, source, raws)


def ingest_eml_directory(
    session: Session, source: Source, directory, *, recursive: bool = True
) -> dict[str, int]:
    """Ingest every ``.eml`` file under ``directory`` (recursively by default)."""
    root = Path(directory)
    pattern = "**/*.eml" if recursive else "*.eml"
    paths = sorted(root.glob(pattern)) + sorted(root.glob(pattern[:-4] + ".EML"))
    return ingest_eml_files(session, source, paths)
