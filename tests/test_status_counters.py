"""/status: the mention count stays EXACT (honesty) (Item 8 P1; the caching moved to the background pass, A-002).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The field diagnostic showed ``SELECT count(*) FROM keyword_mentions`` (a full scan of the
multi-GB mention table through the SQLCipher codec) as the single slowest query — 724 ms ×
172 polls of /status. The fix is a DATA-AWARE cache at the endpoint that collapses repeat
polls while any write invalidates it — NOT trading the exact count for a maintained-counter
sum (which can drift silently on a cascade delete and would present a wrong number as
exact, breaching the honesty non-negotiable). These tests pin: the counts stay REAL/exact,
and the cache key is stable / write-invalidated / bind-distinct.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.api import insights
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture(autouse=True)
def _clean_status_cache():
    """Isolate every test: clear the endpoint read-cache and close every pinned /status
    probe connection between tests. A GC'd fixture engine's ``id()`` can be recycled, so a
    leftover cache entry or a stale probe connection keyed by that id would make an
    order-dependent flake (the exact hazard the D0 fix guards against)."""
    insights._read_cache.clear()
    insights._reset_status_probe_for_tests()
    yield
    insights._read_cache.clear()
    insights._reset_status_probe_for_tests()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, n=4):
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ex = BaselineExtractor()
    for i in range(n):
        a = Article(
            url=f"https://x.test/{i}",
            canonical_url=f"https://x.test/{i}",
            source_id=1,
            title="Climate policy",
            content=f"The election and climate policy dominated trade talks number {i}. "
            "Inflation and diplomacy featured in the coverage of the summit.",
            hash=f"h{i}",
            country="fr",
            language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC),
            created_at=datetime.now(UTC),
        )
        db.add(a)
        db.commit()
        index_article(db, a, extractor=ex, country="fr")


def test_status_mentions_is_the_real_exact_row_count(db):
    _seed(db)
    st = q.status(db)
    real = db.query(func.count(KeywordMention.id)).scalar() or 0
    assert real > 0
    # The exact count, never a maintained-counter derivation (which could drift).
    assert st["mentions"] == real


def test_status_mentions_stays_exact_even_when_a_counter_has_drifted(db):
    """The honesty guard: a KeywordMention inserted directly (article_count NOT maintained)
    must NOT make 'mentions' disagree with the real row count. A counter-derived sum would
    undercount here and (per the field skeptic) could be mislabelled exact — so we keep the
    real count(*)."""
    _seed(db)
    kw = db.query(Keyword).first()
    # Drift the counters: a raw mention row for a NEW (keyword,article) pair whose
    # article_count is never bumped, so SUM(article_count) would now understate the truth.
    other = Article(
        url="https://x.test/drift", canonical_url="https://x.test/drift", source_id=1,
        title="d", content="d", hash="hdrift", country="fr", language="en",
        published_at=datetime(2024, 3, 2, tzinfo=UTC), created_at=datetime.now(UTC),
    )
    db.add(other)
    db.commit()
    db.add(KeywordMention(keyword_id=kw.id, article_id=other.id, count=1))
    db.commit()

    real = db.query(func.count(KeywordMention.id)).scalar() or 0
    summed = db.query(func.coalesce(func.sum(Keyword.article_count), 0)).scalar() or 0
    assert q.status(db)["mentions"] == real, "mentions must be the exact count, never a drifting sum"
    assert summed < real, "sanity: the counter sum IS now drifted (why we don't serve it)"
    # No score field anywhere.
    assert not any("score" in k.lower() for k in q.status(db))


def test_status_returns_the_real_progress_numbers(db):
    _seed(db, n=3)
    st = q.status(db)
    assert st["total_articles"] == 3
    assert st["indexed_articles"] == 3  # all indexed
    assert st["remaining"] == 0
    assert st["keywords"] > 0


# The endpoint's caching (a data-aware key on PRAGMA data_version, invalidated by any commit) was retired by audit 0.5.0 A-002: a
# commit per batch made every poll a miss, so every poll ran the two whole-index scans. The route now serves the totals at once and
# runs the scans in the background (tests/test_insights_status_served.py pins the cold start, the carry window, the failure window
# and the cross-connection write). The counts' exactness is still pinned above, on the blocking q.status the background pass runs.
