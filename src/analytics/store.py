"""
Persist extracted keywords/entities as mentions, and backfill the corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``index_article`` runs an extractor over one article and writes one
``KeywordMention`` per (article, keyword), upserting the ``Keyword`` row. It is
idempotent: re-indexing an article replaces its mentions. ``backfill_corpus``
indexes articles that have no mentions yet (used by the GUI's "index corpus"
action), in bounded batches so it never blocks.

Denormalised facets (``observed_on`` from the article date, ``country`` / ``city``
from its source) are written onto each mention so trend, map and per-region
queries stay single-scan.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from src.analytics.extract import ExtractedTerm
from src.database.models import Article, Keyword, KeywordMention

_LOG = logging.getLogger(__name__)


def _get_or_create_keyword(session: Session, t: ExtractedTerm, *, language: str, extractor: str) -> Keyword:
    kw = session.query(Keyword).filter_by(normalized_term=t.normalized).first()
    is_entity = t.kind != "term"
    if kw is None:
        kw = Keyword(
            term=t.term, normalized_term=t.normalized, language=language or "en",
            frequency=0, is_entity=is_entity,
            entity_type=(t.kind if is_entity else None),
            is_ngram=(" " in t.normalized), ngram_size=len(t.normalized.split()),
            extractor=extractor,
        )
        session.add(kw)
        session.flush()  # assign id for the mention FK
    elif is_entity and not kw.is_entity:
        # A term first seen lowercase, later recognised as an entity -> upgrade.
        kw.is_entity = True
        kw.entity_type = t.kind
        kw.extractor = extractor
    return kw


def index_article(
    session: Session,
    article: Article,
    *,
    extractor,
    country: str | None = None,
    city: str | None = None,
) -> dict:
    """Extract + store mentions for one article (idempotent). Returns a small tally."""
    content = article.get_content() if hasattr(article, "get_content") else (article.content or "")
    terms = extractor.extract(
        content or "", title=article.title or "", language=article.language or "en",
    )

    observed = article.published_at or article.created_at
    observed_on = observed.date() if observed else None
    cc = (country or article.country or "")
    cc = cc[:2].lower() if cc else None

    # Idempotent re-index: drop this article's existing mentions first.
    session.query(KeywordMention).filter_by(article_id=article.id).delete()

    written = 0
    for t in terms:
        kw = _get_or_create_keyword(session, t, language=article.language or "en",
                                    extractor=extractor.name)
        session.add(KeywordMention(
            keyword_id=kw.id, article_id=article.id, count=t.count,
            first_offset=t.first_offset, observed_on=observed_on,
            country=cc, city=city, extractor=extractor.name,
        ))
        written += 1
    session.commit()
    return {"article_id": article.id, "mentions": written,
            "entities": sum(1 for t in terms if t.kind != "term")}


def _unindexed_query(session: Session):
    indexed = session.query(KeywordMention.article_id).distinct()
    return session.query(Article).filter(~Article.id.in_(indexed))


def backfill_corpus(session: Session, *, extractor, limit: int | None = 200) -> dict:
    """Index articles that have no mentions yet, up to ``limit``. Returns progress."""
    q = _unindexed_query(session).order_by(Article.id)
    if limit:
        q = q.limit(limit)
    articles = q.all()

    indexed = 0
    for art in articles:
        try:
            index_article(session, art, extractor=extractor, country=art.country)
            indexed += 1
        except Exception:  # noqa: BLE001 - one bad article must not abort the batch
            session.rollback()
            _LOG.warning("indexing article %s failed", art.id, exc_info=True)
    remaining = _unindexed_query(session).count()
    return {"indexed": indexed, "remaining": remaining}
