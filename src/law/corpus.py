"""
World-law documents enter THE corpus — same aggregation as any other article.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The versioned-sources ruling (2026-07-10, made concrete for the law vertical):
"a versioned source is an Article + a linked revision/audit trail." A tracked
legal document is therefore an ARTICLE like any other — it joins full-text
search, the keyword aggregator and the When×Where×Who anchoring — with ONE
structural difference: it has versions. The text ingested here is always the
NEWEST text the tracker holds (``latest_text``, falling back to the baseline
when no change has landed yet); re-syncing after a change re-indexes
idempotently, so the analytics always describe the version the user is shown.
Its linked :class:`LawRevision` audit trail is the version layer, exactly as
:class:`WikiRevision` is for a wiki page.

This mirrors ``src/wiki/corpus.py`` deliberately (the same one-``index_article``
hook, the same idempotent-on-content-hash upsert) so laws flow through the
single indexing chokepoint like any scraped or wiki article.

Honesty notes:
  * the corpus row's content is the document's normalised VISIBLE text (the same
    ``page_text`` / PDF extraction the tracker stores) — a research mirror, never
    the authoritative gazette (``official_url`` links back);
  * provenance: each JURISDICTION gets ONE catalog source ("Law (UK)", a
    synthetic ``law.uk.local`` domain, ``source_type="legal"``) so law-derived
    rows are a filterable provenance class forever — like the per-edition wiki
    sources, and following the app's ``*.local`` non-web-provenance convention
    (cf. ``mailbox.import.local``) so it never collides with a scraped source;
  * language stays NULL: a jurisdiction is NOT a language (uk/us are English, eu
    is multilingual, many jurisdictions are ambiguous), so we never silently
    guess it — the deduced-language pass fills ``detected_language`` at index
    time instead.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.database.models import Article, LawDocument, Source
from src.database.write import is_integrity_error

_LOG = logging.getLogger(__name__)


def _law_domain(jurisdiction: str) -> str:
    """A stable, synthetic per-jurisdiction domain (never a real web host)."""
    j = (jurisdiction or "xx").strip().lower() or "xx"
    return f"law.{j}.local"


def law_canonical_url(doc: LawDocument) -> str:
    """The canonical link for a law article: the official gazette when known."""
    return doc.official_url or doc.url


def ensure_law_source(session: Session, jurisdiction: str) -> Source:
    """ONE catalog source per jurisdiction — law-derived rows stay filterable.

    Synthetic ``law.<jurisdiction>.local`` domain (the app's established
    non-web-provenance convention, cf. ``mailbox.import.local``) so it can never
    collide with a scraped source, and the law channel stays a distinct,
    filterable provenance class (``source_type="legal"``, matching the seeded
    legal catalog sources).
    """
    j = (jurisdiction or "xx").strip().lower() or "xx"
    domain = _law_domain(j)
    src = session.query(Source).filter_by(domain=domain).first()
    if src is None:
        src = Source(
            name=f"Law ({j.upper()})",
            domain=domain,
            rss_url=None,
            source_type="legal",
        )
        session.add(src)
        session.flush()
    return src


def _law_text(doc: LawDocument) -> str | None:
    """The newest visible text we hold for this document (honest fallback)."""
    return doc.latest_text or doc.baseline_text


def upsert_law_corpus_article(
    session: Session, *, doc: LawDocument, extractor=None
) -> dict:
    """Upsert ONE law document's newest text as a corpus Article and index it.

    Keyed on the canonical (official) URL; idempotent on the content hash
    (unchanged text is skipped — no duplicate Article, no re-index). Routes
    through the SINGLE ``index_article`` hook so laws get keywords +
    When×Where×Who exactly like any scraped article.
    """
    text = _law_text(doc)
    if not text:
        return {"document_id": doc.id, "status": "skipped-no-text"}
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    url = law_canonical_url(doc)

    art = session.query(Article).filter(Article.canonical_url == url).first()
    created = False
    if art is None:
        src = ensure_law_source(session, doc.jurisdiction)
        art = Article(
            url=url,
            canonical_url=url,
            source_id=src.id,
            title=doc.title,
            content=text,
            language=None,  # a jurisdiction is NOT a language — never guess it
            hash=content_hash,
            published_at=doc.last_checked_at or datetime.now(UTC),
        )
        session.add(art)
        created = True
    elif art.hash == content_hash:
        return {"document_id": doc.id, "status": "unchanged", "article_id": art.id}
    else:
        art.content = text
        art.hash = content_hash
        art.title = doc.title
        if doc.last_checked_at:
            art.published_at = doc.last_checked_at
    try:
        session.commit()
    except Exception as exc:  # noqa: BLE001 - is_integrity_error is the precise discriminator
        # Audit finding 2026-07-17: `except IntegrityError` (sqlalchemy.exc) never
        # matched on the encrypted (sqlcipher3) store, whose driver raises its OWN
        # unwrapped exception class -- the same cross-driver divergence already
        # fixed for is_locked_error/classify_restore_error/src/law/track.py.
        if not is_integrity_error(exc):
            raise
        # Article.hash is GLOBALLY unique, so identical text already in the corpus
        # (model legislation copied across jurisdictions, or a law whose text matches
        # a wiki page) collides. Dedup honestly — never store the same text twice, and
        # never let the collision raise (it would be swallowed as a silent log-only
        # failure by the caller). Fold onto the existing same-content Article.
        session.rollback()
        existing = session.query(Article).filter(Article.hash == content_hash).first()
        return {
            "document_id": doc.id,
            "status": "duplicate-content",
            "article_id": existing.id if existing else None,
        }

    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    from src.analytics.store import index_article

    tally = index_article(session, art, extractor=extractor)
    return {
        "document_id": doc.id,
        "status": "created" if created else "updated",
        "article_id": art.id,
        "mentions": tally.get("mentions", 0),
    }


def sync_law_to_corpus(session: Session, doc: LawDocument, *, extractor=None) -> dict:
    """Upsert the document's newest text as one corpus article and (re-)index it.

    The tracker's entry point (called after a baseline / change / revert),
    mirroring ``sync_page_to_corpus``. A skip is honest (no text yet); a failure
    must never block tracking (the caller wraps this — the text + revision are
    already committed before ingest runs).
    """
    if doc.id is None:
        return {"document_id": None, "status": "skipped-unsaved"}
    return upsert_law_corpus_article(session, doc=doc, extractor=extractor)


def sync_watched_laws(session: Session, *, extractor=None, limit: int = 500) -> dict:
    """Sync every watched law document that has text — the backfill for existing
    documents (new changes sync automatically from the tracker)."""
    docs = (
        session.query(LawDocument)
        .filter(LawDocument.watched.is_(True))
        .limit(limit)
        .all()
    )
    out = {"documents": 0, "created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for doc in docs:
        try:
            res = sync_law_to_corpus(session, doc, extractor=extractor)
        except Exception:  # noqa: BLE001 - one bad document must not abort the batch
            session.rollback()
            _LOG.warning("law corpus sync failed for doc %s", doc.id, exc_info=True)
            out["skipped"] += 1
            continue
        out["documents"] += 1
        st = res.get("status", "")
        if st in ("created", "updated", "unchanged"):
            out[st] += 1
        else:
            out["skipped"] += 1
    return out
