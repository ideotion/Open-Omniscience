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


# --- Phase 1.3: batched re-index commits (COLLECTOR_WRITER_BATCHING.md) ------- #


def _mentions_snapshot(db):
    """All (article_id, keyword_id, count) mention rows — compared across runs."""
    return sorted(
        (m.article_id, m.keyword_id, m.count) for m in db.query(KeywordMention).all()
    )


def _live_counters(db):
    """The authoritative per-keyword counts from the live GROUP BY over mentions."""
    from sqlalchemy import distinct, func

    rows = (
        db.query(
            KeywordMention.keyword_id,
            func.sum(KeywordMention.count),
            func.count(distinct(KeywordMention.article_id)),
        )
        .group_by(KeywordMention.keyword_id)
        .all()
    )
    return {kid: (int(s), int(a)) for kid, s, a in rows}


def _stored_counters(db):
    """The denormalised counters on the Keyword rows (for keywords with mentions)."""
    return {
        kw.id: (kw.mention_count, kw.article_count)
        for kw in db.query(Keyword).filter(Keyword.mention_count > 0).all()
    }


def test_batched_reindex_matches_per_article_and_keeps_counters_exact(db):
    """The killer no-loss assert (Phase 1.3): a batched re-index (commit_batch>1)
    produces IDENTICAL keyword rows + IDENTICAL counters to the per-article path, and
    the counters equal the live GROUP BY (no drift from batching)."""
    from src.analytics.store import reindex_all_batch

    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ex = BaselineExtractor()
    # Several articles SHARING keywords, so counter deltas accumulate within a batch.
    for i in range(7):
        _article(db, f"h{i}", "Election results show inflation across the global economy and trade.", title=f"T{i}")

    r1 = reindex_all_batch(db, extractor=ex, limit=100, commit_batch=1)  # per-article
    assert r1["reindexed"] == 7 and r1["failed"] == 0
    snap1, ctr1 = _mentions_snapshot(db), _stored_counters(db)

    r2 = reindex_all_batch(db, extractor=ex, limit=100, commit_batch=3)  # batched (idempotent re-run)
    assert r2["reindexed"] == 7 and r2["failed"] == 0
    snap2, ctr2 = _mentions_snapshot(db), _stored_counters(db)

    assert snap1 == snap2  # identical mention rows
    assert ctr1 == ctr2  # identical denormalised counters
    assert ctr2 == _live_counters(db)  # counters == the live GROUP BY (zero drift)


def test_batched_reindex_failure_fallback_loses_nothing(db):
    """A failure building ONE article mid-batch rolls the batch back and redoes it
    per-article — every other article is fully indexed and the counters stay exact
    (no half-batch, no data loss). Mirrors the proven ingest_emails fallback."""
    from src.analytics.store import reindex_all_batch

    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ex = BaselineExtractor()
    for i in range(6):
        _article(db, f"h{i}", "Energy prices and the drought pushed agriculture costs higher today.", title=f"T{i}")
    arts = db.query(Article).order_by(Article.id).all()
    bad_id = arts[2].id  # "T2" raises during extraction, mid-batch

    class _FlakyExtractor:
        name = ex.name

        def extract(self, content, *, title="", language="en"):
            if title == "T2":
                raise RuntimeError("boom")
            return ex.extract(content, title=title, language=language)

    r = reindex_all_batch(db, extractor=_FlakyExtractor(), limit=100, commit_batch=4)
    assert r["failed"] == 1 and r["reindexed"] == 5
    for a in arts:
        n = db.query(KeywordMention).filter_by(article_id=a.id).count()
        assert n == 0 if a.id == bad_id else n > 0  # only the bad one lost its mentions
    assert _stored_counters(db) == _live_counters(db)  # counters exact despite the failure
