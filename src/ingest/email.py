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
import ipaddress
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
from pathlib import Path

from sqlalchemy.orm import Session

from src.database.models import Article, Source
from src.database.write import is_locked_error, run_write_with_retry
from src.privacy.link_sanitizer import SanitizeStats, sanitize_text
from src.utils.url_utils import generate_content_hash

_LOG = logging.getLogger(__name__)

# Order matters in _strip_html: <style>/<script> BLOCKS (content + tags) and HTML
# COMMENTS must go BEFORE the generic tag strip — otherwise the CSS/JS text survives
# as body content and Outlook/MSO conditional comments (which contain '>') defeat a
# naive <[^>]+> regex, leaking '-->' fragments. (Field test 2026-06-20.)
_STYLE_SCRIPT_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)


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
    # The SENDING mail-server IP read from the Received chain (recipient-safe: it is
    # the sender's infrastructure, not the recipient). None when the chain carries no
    # public IP; ``sender_ip_reason`` states why. Deduced/approximate — a relay or
    # forwarder may sit between it and the true origin (stated in the reason).
    sender_ip: str | None = None
    sender_ip_reason: str | None = None


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


def _strip_html(html_text: str) -> str:
    """Reduce an HTML email part to clean, readable plain text.

    Drops <style>/<script> blocks ENTIRELY (their CSS/JS must never survive as body
    text), then HTML comments (incl. MSO conditional comments containing '>'), then
    every remaining tag, then DECODES HTML entities (&nbsp;, &#8202;, &copy;,
    &rsquo; …) and collapses whitespace — including non-breaking / hair / zero-width
    spaces — so the stored copy carries no markup noise (field test 2026-06-20).
    """
    text = _STYLE_SCRIPT_RE.sub(" ", html_text)
    text = _COMMENT_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    text = text.replace("\u200b", "").replace("\ufeff", "")  # strip zero-width chars
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
            txt = _decode_part(plain).strip()
            if txt:  # fall through to HTML when the text/plain part is empty
                return txt
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


# Bracketed IP literals as they appear in Received headers:
#   from mail.example.com (mail.example.com [203.0.113.5]) by ...
#   from [203.0.113.5] by ...            /  from x (x [IPv6:2001:db8::1]) by ...
_RECEIVED_IP_RE = re.compile(r"\[(?:IPv6:)?([0-9A-Fa-f:.]+)\]")


def sender_origin_ip(msg: Message) -> tuple[str | None, str | None]:
    """Deduce the SENDING mail-server IP from the message's Received chain.

    Received headers are prepended at each hop, so ``get_all("Received")`` runs
    newest→oldest; the OLDEST (last) header is written by the first server that took
    the message from the sender, so we scan oldest→newest and return the first
    PUBLIC (globally-routable) IP we find — closest to the true origin. Private /
    loopback / link-local / reserved addresses (internal relays) are skipped, and a
    garbage token never becomes an IP (``ipaddress`` validates each).

    Returns ``(ip, None)`` on a hit, else ``(None, reason)``. This is recipient-safe
    (the sender's own infrastructure, like the ``server_ip`` we already capture for
    web articles) and DEDUCED — a relay/forwarder may sit between it and the real
    origin, and a stripped/rewritten chain yields no IP rather than a guess. No
    network: the IP is read from bytes already in the ``.eml``.
    """
    received = msg.get_all("Received")
    if not received:
        return None, "no Received headers in the message"
    saw_any_ip = False
    for hdr in reversed(received):  # oldest hop first
        for token in _RECEIVED_IP_RE.findall(hdr or ""):
            try:
                addr = ipaddress.ip_address(token)
            except ValueError:
                continue
            saw_any_ip = True
            if addr.is_global:
                return addr.compressed, None
    reason = (
        "Received chain has only private/reserved hops (internal relay)"
        if saw_any_ip
        else "no IP literal in the Received chain (stripped or rewritten)"
    )
    return None, reason


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
    sender_ip, sender_ip_reason = sender_origin_ip(msg)

    return ParsedEmail(
        message_id=message_id,
        subject=subject,
        from_addr=_header(msg, "From"),
        date=date,
        body_text=body_text,
        sanitize=stats,
        redactions=r1 + r2,
        sender_ip=sender_ip,
        sender_ip_reason=sender_ip_reason,
    )


def _refuse_if_offline() -> None:
    """Airplane gate for live mailbox fetches (ruling #11): no socket while offline.

    Deferred import (``src.ingest`` is this module's own package) to avoid any
    import-order coupling, matching the pattern used elsewhere.
    """
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise RuntimeError("network refused: airplane mode is engaged")


def fetch_imap(
    host: str,
    user: str,
    password: str,
    *,
    folder: str = "INBOX",
    limit: int = 50,
    use_ssl: bool = True,
    port: int = 0,
    conn=None,
) -> list[bytes]:
    """Fetch up to ``limit`` most recent raw messages from a folder.

    ``conn`` may be injected (an imaplib-like object) for testing; otherwise a real
    SSL IMAP connection is opened. AIRPLANE-gated (ruling #11): refuses up front when
    the kill switch is engaged, so an offline call opens NO socket (and even an injected
    ``conn`` is not touched). The session is logged out in a ``finally`` so a fetch error
    never leaks it. The recipient-safe anonymisation happens later, in ``ingest_emails``.
    ``port`` 0 = the protocol default (993 SSL / 143 plain).
    """
    _refuse_if_offline()
    own_conn = conn is None
    if own_conn:  # pragma: no cover - exercised only against a live server
        import imaplib

        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port or 993)
        else:
            conn = imaplib.IMAP4(host, port or 143)
        conn.login(user, password)
    try:
        conn.select(folder)
        typ, data = conn.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()[-max(1, int(limit)):]
        raws: list[bytes] = []
        for mid in ids:
            typ, msg_data = conn.fetch(mid, "(RFC822)")
            if typ == "OK" and msg_data and msg_data[0]:
                raws.append(msg_data[0][1])
        return raws
    finally:
        if own_conn:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 - logout failure must not mask the result
                pass


def fetch_pop3(
    host: str,
    user: str,
    password: str,
    *,
    limit: int = 50,
    use_ssl: bool = True,
    port: int = 0,
    conn=None,
) -> list[bytes]:
    """Fetch up to ``limit`` most recent raw messages from a POP3 mailbox (ruling #11).

    Same guardrails as :func:`fetch_imap`: AIRPLANE-gated (no socket offline), credentials
    used transiently, quit in a ``finally``. POP3 has no folders; messages are numbered
    1..N (oldest..newest), so the newest ``limit`` are the tail. ``conn`` is injectable.
    ``port`` 0 = the protocol default (995 SSL / 110 plain).
    """
    _refuse_if_offline()
    own_conn = conn is None
    if own_conn:  # pragma: no cover - exercised only against a live server
        import poplib

        conn = poplib.POP3_SSL(host, port or 995) if use_ssl else poplib.POP3(host, port or 110)
        conn.user(user)
        conn.pass_(password)
    try:
        count = len(conn.list()[1])
        start = max(1, count - max(1, int(limit)) + 1)
        raws: list[bytes] = []
        for i in range(start, count + 1):
            resp, lines, octets = conn.retr(i)
            raws.append(b"\r\n".join(lines))
        return raws
    finally:
        if own_conn:
            try:
                conn.quit()
            except Exception:  # noqa: BLE001
                pass


def fetch_mailbox(protocol: str, host: str, user: str, password: str, **kwargs) -> list[bytes]:
    """Dispatch to :func:`fetch_imap` / :func:`fetch_pop3` by ``protocol`` ("imap"|"pop3")."""
    proto = (protocol or "").strip().lower()
    if proto == "imap":
        return fetch_imap(host, user, password, **kwargs)
    if proto == "pop3":
        kwargs.pop("folder", None)  # POP3 has no folders
        return fetch_pop3(host, user, password, **kwargs)
    raise ValueError(f"unknown mailbox protocol: {protocol!r} (use 'imap' or 'pop3')")



def _email_article(source: Source, parsed: ParsedEmail, content_hash: str, canonical: str) -> Article:
    now = datetime.now(UTC)
    # Sending mail-server IP (recipient-safe, deduced) → the same server_ip columns
    # web articles use, so newsletters surface on the ooMap "Server IPs" layer and
    # geolocate through the offline DB-IP lookup. Reason is stored either way so a
    # missing IP is honest (never a guess); observed-at is stamped only on a hit.
    return Article(
        url=canonical,
        canonical_url=canonical,
        source_id=source.id,
        title=parsed.subject,
        content=parsed.body_text,
        published_at=parsed.date,
        author=parsed.from_addr,
        hash=content_hash,
        word_count=len(parsed.body_text.split()),
        server_ip=parsed.sender_ip,
        ip_observed_at=now if parsed.sender_ip else None,
        server_ip_reason=(
            "sender mail-server IP from the .eml Received chain (deduced; may be a relay)"
            if parsed.sender_ip
            else (parsed.sender_ip_reason or "no sender IP in the .eml")
        ),
        created_at=now,
        updated_at=now,
    )


def _is_integrity_error(exc: BaseException) -> bool:
    """True iff ``exc`` (or a wrapped cause/context) is a UNIQUE/FK/NOT-NULL violation.

    Audit finding 2026-07-17: on the ENCRYPTED (sqlcipher3) store a unique-constraint
    collision can surface as a RAW ``sqlcipher3``/``sqlite3`` ``IntegrityError`` that
    SQLAlchemy does NOT wrap as ``sqlalchemy.exc.IntegrityError`` -- the exact
    cross-driver class divergence ``src/database/write.py``'s ``is_locked_error`` and
    ``src/backup/merge.py``'s ``_db_integrity_error_types`` already had to fix
    (field log 2026-07-14 "297 fetched articles left unindexed"; field bug
    2026-07-16). A narrow ``except IntegrityError`` here silently never matches on
    the encrypted default store, letting a genuine (and expected -- a benign
    same-hash duplicate) collision escape as an unhandled exception that aborts
    the WHOLE import batch instead of being counted as a duplicate.
    """
    import sqlalchemy.exc
    import sqlite3

    types: list[type] = [sqlalchemy.exc.IntegrityError, sqlite3.IntegrityError]
    try:
        from sqlcipher3.dbapi2 import IntegrityError as _SqlcipherIntegrityError

        types.append(_SqlcipherIntegrityError)
    except Exception:  # noqa: BLE001 - sqlcipher3 absent in a core install -> stdlib path only
        pass
    for e in (exc, exc.__cause__, exc.__context__):
        if e is not None and isinstance(e, tuple(types)):
            return True
    return False


def ingest_emails(
    session: Session, source: Source, raw_messages: list[bytes], *, commit_batch: int | None = None
) -> dict[str, int]:
    """Parse and store raw emails as Article rows, deduplicated by content hash.

    Emails are anonymised at ingest (recipient never stored, recipient echoes
    redacted, links de-tracked). The tally surfaces what anonymisation did so the
    caller can show the user honest counts.

    PERFORMANCE (field test 2026-06-20: a 20 GB+ folder is slow while hardware idles):
    commits are BATCHED (every ``commit_batch`` rows, default ``OO_EMAIL_COMMIT_BATCH``
    = 200) instead of one fsync per message — the .eml import is fsync/SQLCipher-codec
    bound, not CPU bound. Correctness is preserved: messages are deduped against the DB
    AND within the uncommitted batch, and if a batch commit ever races a unique-index
    collision the batch is REDONE one message at a time, so a single conflict never
    drops the rest (no data loss — the maintainer's standing rule).
    """
    import os

    if commit_batch is None:
        try:
            commit_batch = int(os.getenv("OO_EMAIL_COMMIT_BATCH", "200"))
        except ValueError:
            commit_batch = 200
    commit_batch = max(1, commit_batch)

    tally = {
        "stored": 0,
        "duplicate": 0,
        "empty": 0,
        "errors": 0,
        "recipient_redactions": 0,
        "tracker_params_stripped": 0,
        "trackers_flagged": 0,
    }
    # Added-but-not-yet-committed: (parsed, hash, canonical) — kept so a batch that
    # fails on commit can be re-applied one message at a time without re-parsing.
    pending: list[tuple[ParsedEmail, str, str]] = []
    # In-batch dedup keyed on the ACTUAL unique column. `articles.hash` is the ONLY
    # UNIQUE constraint (canonical_url is NOT unique), so two emails with the SAME body
    # but DIFFERENT Message-IDs share a content_hash and MUST dedup on the hash ALONE.
    # The old (hash, canonical) tuple key let such a pair into one uncommitted batch and
    # collide at flush on `UNIQUE articles.hash`; under the continuously-running scraper's
    # writer contention that collision escaped as an unhandled 500, failing the WHOLE
    # import (field test 2026-06-24: a 5 GB folder of repeated .eml). We still track the
    # canonical so a repeated canonical within a batch dedups too (a harmless nicety).
    pending_hashes: set[str] = set()
    pending_canon: set[str] = set()

    def _exists(content_hash: str, canonical: str) -> bool:
        return (
            session.query(Article.id)
            .filter((Article.hash == content_hash) | (Article.canonical_url == canonical))
            .first()
            is not None
        )

    def _commit_one(parsed: ParsedEmail, content_hash: str, canonical: str) -> None:
        # The safe per-message path used on a batch-commit collision: re-check (the batch
        # rolled back; a concurrent writer may have inserted), then commit. A transient
        # lock RETRIES (never drops fetched data — the no-data-loss rule); a genuine
        # duplicate is counted; an exhausted lock is logged + counted, NEVER raised, so a
        # single message can neither abort the import nor escape as an unhandled 500.
        if _exists(content_hash, canonical):
            tally["duplicate"] += 1
            return

        def _work() -> None:
            session.add(_email_article(source, parsed, content_hash, canonical))
            session.commit()

        try:
            run_write_with_retry(_work, session=session, label="newsletter import")
            tally["stored"] += 1
        except Exception as exc:  # noqa: BLE001 - is_locked_error/_is_integrity_error are the
            # precise, cross-driver-aware discriminators (see _is_integrity_error's docstring);
            # anything neither of them recognises is a genuinely unexpected failure and must
            # still surface loudly, never be silently swallowed as a miscounted duplicate.
            session.rollback()
            if is_locked_error(exc):
                tally["errors"] += 1
                _LOG.warning("newsletter import: a message could not be stored (db locked); skipped")
            elif _is_integrity_error(exc):
                tally["duplicate"] += 1
            else:
                raise

    def _flush() -> None:
        if not pending:
            return
        try:
            session.commit()
            tally["stored"] += len(pending)
        except Exception as exc:  # noqa: BLE001 - same discriminated dispatch as _commit_one
            if not (is_locked_error(exc) or _is_integrity_error(exc)):
                session.rollback()
                raise
            # A unique-index collision the in-batch/DB dedup didn't catch, or a transient
            # lock: redo this batch one message at a time so a single collision/lock never
            # drops its batch-mates and never escapes as an unhandled error.
            session.rollback()
            for parsed, h, canon in pending:
                _commit_one(parsed, h, canon)
        pending.clear()
        pending_hashes.clear()
        pending_canon.clear()

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
        # In-batch dedup on the unique column (hash) + the canonical (nicety): two
        # identical-body messages in the SAME uncommitted batch would collide on
        # `UNIQUE articles.hash` at flush — count the later one a duplicate now.
        if (
            content_hash in pending_hashes
            or canonical in pending_canon
            or _exists(content_hash, canonical)
        ):
            tally["duplicate"] += 1
            continue
        session.add(_email_article(source, parsed, content_hash, canonical))
        pending.append((parsed, content_hash, canonical))
        pending_hashes.add(content_hash)
        pending_canon.add(canonical)
        if len(pending) >= commit_batch:
            _flush()
    _flush()
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


# The two dedicated, FILTERABLE newsletter provenance buckets: locally-imported
# .eml files and live IMAP/POP3 mailbox pulls. The single source of truth for
# "which sources hold imported newsletters" — reused by the backup snapshot filter
# (src.backup.artifact) and the live-remove maintenance action below.
NEWSLETTER_SOURCE_DOMAINS: tuple[str, ...] = (
    "newsletters.import.local",
    "mailbox.import.local",
)


def _newsletter_article_ids(session: Session) -> list[int]:
    """Live ids of every article that arrived via an imported-newsletter source."""
    src_ids = [
        s for (s,) in session.query(Source.id).filter(Source.domain.in_(NEWSLETTER_SOURCE_DOMAINS))
    ]
    if not src_ids:
        return []
    return [a for (a,) in session.query(Article.id).filter(Article.source_id.in_(src_ids))]


def count_imported_newsletters(session: Session) -> int:
    """How many imported-newsletter articles the live corpus holds (for the confirm)."""
    return len(_newsletter_article_ids(session))


def delete_imported_newsletters(session: Session) -> dict:
    """Remove imported-newsletter articles from the LIVE corpus (the "replace the faulty
    ones" loop).

    Restore is additive-only, so excluding newsletters from a *backup* never purges the
    *live* corpus — this is the action that does. It deletes the .eml + mailbox source
    articles AND every dependent row (any mapped table with an ``article_id`` column —
    every FK to ``articles.id`` uses that name), then reconciles the denormalised keyword
    counters so trending/top stay exact (the bulk DELETE bypasses ``index_article``'s
    per-article counter maintenance). The empty source rows are LEFT, so a future clean
    re-import re-attaches to them. The article DELETE fires the ``article_fts_ad`` trigger,
    so the search index is cleaned automatically.

    Reversible only via a prior backup (the caller nudges "back up first"). Counts only;
    takes the single-writer gate so it never races a scrape/import write.
    """
    from src.database.models import Base
    from src.database.writer import write_lock

    art_ids = _newsletter_article_ids(session)
    if not art_ids:
        return {"removed_articles": 0, "domains": list(NEWSLETTER_SOURCE_DOMAINS)}

    dep_tables = [
        t
        for t in Base.metadata.sorted_tables
        if t.name != "articles" and "article_id" in t.columns
    ]
    with write_lock():
        for lo in range(0, len(art_ids), 900):  # under SQLite's 999-variable cap
            chunk = art_ids[lo : lo + 900]
            for t in dep_tables:
                session.execute(t.delete().where(t.c.article_id.in_(chunk)))
            session.execute(Article.__table__.delete().where(Article.__table__.c.id.in_(chunk)))
        session.commit()

    # The bulk delete didn't go through index_article, so the denormalised
    # Keyword.mention_count / article_count are now stale — repair them authoritatively.
    from src.analytics.store import backfill_keyword_counters, reconcile_source_counters

    backfill_keyword_counters(session)
    # S6: the per-source article counter is stale too (a bulk delete removed articles) —
    # reconcile it so source_io/sources reads a correct count immediately.
    reconcile_source_counters(session)
    return {"removed_articles": len(art_ids), "domains": list(NEWSLETTER_SOURCE_DOMAINS)}
