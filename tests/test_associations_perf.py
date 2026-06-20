"""associations() de-N+1 optimization is BYTE-IDENTICAL (data-arch Slice 4 PR-3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The hot ``associations`` endpoint stopped running TWO queries per co-occurring keyword (a
COUNT(DISTINCT article_id) for n_b + a get(Keyword)) — n_b now comes from the maintained
``article_count`` counter (corpus-wide) or one grouped query (windowed), and the keyword
rows are batch-loaded. This proves the OUTPUT is identical to recomputing n_b the live way
(the old behaviour), on both paths.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    texts = [
        "The Senate debated sanctions on Russia over the federal budget crisis.",
        "Russia responded to the sanctions while the budget debate continued.",
        "Sanctions and the budget dominated the Senate session on Russia.",
        "Climate policy entered the budget debate in the Senate.",
    ]
    for i, t in enumerate(texts):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content=t, hash=f"h{i}", language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    return s


def _live_n_b(db, normalized, *, start=None, end=None) -> int:
    """n_b the OLD way: a live COUNT(DISTINCT article_id) for the keyword (windowed)."""
    from src.database.models import Keyword

    kw = db.query(Keyword).filter_by(normalized_term=normalized).first()
    qy = db.query(func.count(func.distinct(KeywordMention.article_id))).filter(
        KeywordMention.keyword_id == kw.id
    )
    if start:
        qy = qy.filter(KeywordMention.observed_on >= start)
    if end:
        qy = qy.filter(KeywordMention.observed_on <= end)
    return int(qy.scalar() or 1) or 1


def _assert_pairs_byte_identical(db, res, *, start=None, end=None):
    total = res["corpus_articles"]
    n_a = res["n_articles_with_term"]
    assert res["pairs"], "fixture should yield co-occurring pairs"
    for p in res["pairs"]:
        live = _live_n_b(db, p["normalized"], start=start, end=end)
        assert p["n_b"] == live, f"n_b drift on {p['normalized']}: {p['n_b']} != live {live}"
        expected_pmi = round(math.log2((p["cooccur"] * total) / (n_a * live)), 3)
        assert p["pmi"] == expected_pmi, f"pmi drift on {p['normalized']}"


def test_associations_corpus_wide_matches_live_n_b(db):
    # The counter path: n_b == the maintained article_count == the live COUNT.
    res = q.associations(db, "budget", min_cooccur=1, group=False)
    _assert_pairs_byte_identical(db, res)


def test_associations_windowed_matches_live_grouped_n_b(db):
    # The windowed path: n_b from one grouped query (not the counter).
    start = date(2024, 1, 1)
    res = q.associations(db, "budget", min_cooccur=1, group=False,
                         start=start, end=date(2024, 12, 31))
    _assert_pairs_byte_identical(db, res, start=start, end=date(2024, 12, 31))


def test_grouped_associations_still_works(db):
    # The family/ring honesty layer (group=True) is unchanged on top of the raw pairs.
    res = q.associations(db, "budget", min_cooccur=1, group=True)
    assert res["grouped"] is True
    assert "Association is not causation" in res["caveat"]


def test_unknown_term_is_honest(db):
    res = q.associations(db, "zzznotaword", min_cooccur=1)
    assert res["pairs"] == [] and res["resolved"] is None
