"""
Tests for keyword-mention persistence + backfill + ingest wiring.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import backfill_corpus, index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _article(db, hash_, text, *, country="fr", title="T", when="2024-03-01"):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title=title,
        content=text,
        hash=hash_,
        country=country,
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def test_index_article_writes_mentions_with_facets(db):
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(
        db,
        "h1",
        "The WHO warned about climate policy. Climate policy and trade dominated talks.",
    )
    res = index_article(db, art, extractor=BaselineExtractor(), country="fr", city="Paris")
    assert res["mentions"] > 0 and res["entities"] >= 1

    # Entities are now ALL-CAPS acronyms only, kept UPPERCASE so they stay distinct
    # from a lowercase homograph (WHO != who) — Title-Case ("Climate Policy") is a
    # topical term, not an entity (PR #283 dropped Title-Case as an entity signal).
    # The entity is one keyword, flagged as entity, with denormalised facets.
    kw = db.query(Keyword).filter_by(normalized_term="WHO").one()
    assert kw.is_entity is True
    m = db.query(KeywordMention).filter_by(keyword_id=kw.id, article_id=art.id).one()
    assert m.country == "fr" and m.city == "Paris"
    assert m.observed_on.isoformat() == "2024-03-01"
    assert m.count >= 1 and m.first_offset is not None


def test_reindex_is_idempotent(db):
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(db, "h2", "Trade policy and trade policy and trade policy again here now.")
    index_article(db, art, extractor=BaselineExtractor())
    n1 = db.query(KeywordMention).filter_by(article_id=art.id).count()
    index_article(db, art, extractor=BaselineExtractor())
    n2 = db.query(KeywordMention).filter_by(article_id=art.id).count()
    assert n1 == n2 and n2 > 0  # replaced, not duplicated


def test_backfill_only_indexes_missing(db):
    db.add(Source(name="S", domain="x.test", country="de"))
    db.commit()
    _article(db, "h3", "Energy prices and energy policy shaped the debate across the region today.")
    _article(
        db, "h4", "Election results surprised analysts and shifted the political landscape sharply."
    )
    r1 = backfill_corpus(db, extractor=BaselineExtractor(), limit=10)
    assert r1["indexed"] == 2 and r1["remaining"] == 0
    # Running again indexes nothing new (all already have mentions).
    r2 = backfill_corpus(db, extractor=BaselineExtractor(), limit=10)
    assert r2["indexed"] == 0


def _kw_set(db, article_id):
    """The set of (normalized_term, count) keyword mentions for one article."""
    rows = (
        db.query(KeywordMention.count, Keyword.normalized_term)
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .filter(KeywordMention.article_id == article_id)
        .all()
    )
    return {(term, cnt) for cnt, term in rows}


def test_keyword_only_scope_skips_when_where_who_and_sentiment(db):
    """Phase 1.2: scope="keywords" runs the keyword pass ONLY — it leaves the
    dates/places/entities + sentiment untouched (a fast keyword cleanup)."""
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    art = _article(db, "h1", "The WHO warned about climate policy and trade in Paris on 5 March 2024.")
    ex = BaselineExtractor()
    full = index_article(db, art, extractor=ex, scope="full")
    assert full["mentions"] > 0
    # Mark sentiment with a sentinel, then a KEYWORD-ONLY re-index.
    art.sentiment_score, art.sentiment_label = 0.999, "sentinel"
    db.commit()
    kwonly = index_article(db, art, extractor=ex, scope="keywords")
    # when/where/who passes were skipped (tally zeros) but keywords still extracted.
    assert kwonly["dates"] == 0 and kwonly["places"] == 0 and kwonly["entities_stored"] == 0
    assert kwonly["mentions"] > 0
    a = db.get(Article, art.id)
    assert a.sentiment_score == 0.999 and a.sentiment_label == "sentinel"  # untouched
    # Contrast: a FULL re-index DOES recompute sentiment (away from the sentinel).
    index_article(db, art, extractor=ex, scope="full")
    assert db.get(Article, art.id).sentiment_label != "sentinel"


def test_keyword_only_scope_produces_identical_keyword_rows_to_full(db):
    """The keyword rows from a keyword-only pass match a full pass exactly."""
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    text = "The election results show major inflation across the global economy."
    a1 = _article(db, "h1", text)
    a2 = _article(db, "h2", text)
    ex = BaselineExtractor()
    index_article(db, a1, extractor=ex, scope="full")
    index_article(db, a2, extractor=ex, scope="keywords")
    assert _kw_set(db, a1.id) == _kw_set(db, a2.id)
    assert _kw_set(db, a1.id)  # non-empty (the comparison isn't vacuous)
