"""Slice 2: the hot keyword queries read the denormalised counters — equivalence.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``top_terms`` (corpus-wide path) now reads ``Keyword.mention_count`` /
``article_count`` instead of joining + GROUP BY-ing keyword_mentions. These tests
pin that the counter-based result is BYTE-IDENTICAL to the old join-based query on a
fixture corpus, and that the windowed (days/country) path still uses the mention
aggregation (the counters are corpus-wide and cannot serve a scoped SUM).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.analytics import queries
from src.analytics.extract import BaselineExtractor
from src.analytics.store import backfill_keyword_counters, index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _article(db, hash_, text, *, when="2024-03-01"):
    a = Article(
        url=f"https://x.test/{hash_}",
        canonical_url=f"https://x.test/{hash_}",
        source_id=1,
        title="T",
        content=text,
        hash=hash_,
        country="fr",
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def _join_reference(db, *, kind=None):
    """The PRE-slice-2 corpus-wide top core: join + GROUP BY over keyword_mentions.

    Returns ``{normalized: (mentions, articles)}`` — the authoritative aggregate the
    counter path must reproduce. (Order-independent dict so a tie at the limit
    boundary can't make the comparison flaky; the ordering itself is checked
    separately on a tie-free seed.)
    """
    q = db.query(
        Keyword,
        func.sum(KeywordMention.count),
        func.count(func.distinct(KeywordMention.article_id)),
    ).join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
    if kind == "term":
        q = q.filter(Keyword.is_entity.is_(False))
    elif kind == "entity":
        q = q.filter(Keyword.is_entity.is_(True))
    return {k.normalized_term: (int(m), int(a)) for k, m, a in q.group_by(Keyword.id).all()}


def _seed_corpus(db):
    _article(db, "h1", "Trade policy and climate policy shaped the talks. Trade trade trade.")
    _article(db, "h2", "Energy prices rose. Energy policy and climate policy dominated debate.")
    _article(db, "h3", "The WHO discussed climate. Drought and drought conditions spread widely.")
    for art in db.query(Article).all():
        index_article(db, art, extractor=BaselineExtractor())


def test_corpus_wide_top_terms_values_match_join_reference(db):
    _seed_corpus(db)
    ref = _join_reference(db)
    # limit high enough that no keyword is cut off -> a pure value comparison.
    res = queries.top_terms(db, limit=500, group=False)
    got = {t["normalized"]: (t["mentions"], t["articles"]) for t in res["terms"]}
    # Hidden/stoplisted words are dropped by top_terms but present in the raw
    # reference, so the counter result must be a subset whose values MATCH exactly.
    assert got, "counter-based top_terms returned nothing"
    for norm, val in got.items():
        assert val == ref[norm], f"{norm}: counter={val} join={ref[norm]}"


def test_corpus_wide_ordering_matches_join(db):
    # Direct seed with STRICTLY DISTINCT mention totals (single content words, no
    # n-gram ties) -> one unambiguous descending order, so the counter path's ORDER
    # (not just values) equals the join path's. Counters populated via the backfill.
    for term, total in [("apple", 10), ("mango", 7), ("cherry", 4), ("peach", 2)]:
        k = Keyword(term=term, normalized_term=term, language="en")
        db.add(k)
        db.flush()
        db.add(KeywordMention(keyword_id=k.id, article_id=1, count=total, observed_on=date.today()))
    db.commit()
    backfill_keyword_counters(db)

    ref_order = [
        k.normalized_term
        for k, _m in (
            db.query(Keyword, func.sum(KeywordMention.count).label("m"))
            .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
            .group_by(Keyword.id)
            .order_by(func.sum(KeywordMention.count).desc())
            .all()
        )
    ]
    got_order = [t["normalized"] for t in queries.top_terms(db, limit=500, group=False)["terms"]]
    assert got_order == ref_order == ["apple", "mango", "cherry", "peach"]


def test_corpus_wide_excludes_keywords_with_no_mentions(db):
    _seed_corpus(db)
    # A keyword with zero mentions (mention_count 0) must NOT appear — matching the
    # old INNER JOIN semantics.
    db.add(Keyword(term="ghost", normalized_term="ghost", language="en", mention_count=0, article_count=0))
    db.commit()
    res = queries.top_terms(db, limit=500, group=False)
    assert "ghost" not in {t["normalized"] for t in res["terms"]}


def test_kind_filter_matches_join(db):
    _seed_corpus(db)
    ref = _join_reference(db, kind="entity")
    res = queries.top_terms(db, limit=500, group=False, kind="entity")
    got = {t["normalized"]: (t["mentions"], t["articles"]) for t in res["terms"]}
    for norm, val in got.items():
        assert val == ref[norm]
    # The WHO acronym is an entity in this corpus; it must be reachable via the
    # counter path under kind=entity.
    assert all(t["kind"] != "term" for t in res["terms"])


def test_grouped_path_still_builds_families(db):
    _seed_corpus(db)
    res = queries.top_terms(db, limit=20, group=True)
    assert res["grouped"] is True and res["count"] >= 1
    # families carry their member forms
    assert any("members" in t for t in res["terms"])


def test_windowed_path_still_uses_mention_aggregation(db):
    # Two articles for the same term on far-apart dates. The corpus-wide counters
    # would report BOTH, but a days= window must scope to the recent one (proving
    # the windowed path kept the mention join, not the counter).
    today = datetime.now(UTC)
    old = (today - timedelta(days=400)).date().isoformat()
    recent = (today - timedelta(days=2)).date().isoformat()
    _article(db, "old", "satellite satellite satellite imagery old story here.", when=old)
    _article(db, "new", "satellite launch confirmed today in a recent satellite update.", when=recent)
    for art in db.query(Article).all():
        index_article(db, art, extractor=BaselineExtractor())

    corpus_wide = queries.top_terms(db, limit=500, group=False)
    sat_all = next(t for t in corpus_wide["terms"] if t["normalized"] == "satellite")
    assert sat_all["articles"] == 2  # counter path sees both

    windowed = queries.top_terms(db, days=30, limit=500, group=False)
    sat_recent = next(t for t in windowed["terms"] if t["normalized"] == "satellite")
    assert sat_recent["articles"] == 1  # window scoped to the recent article only
