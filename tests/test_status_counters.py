"""/status is cached data-aware; the mention count stays EXACT (honesty) (Item 8 P1).

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
from sqlalchemy.pool import NullPool

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


def test_status_cache_key_invalidates_across_connections(tmp_path):
    """The #595/A3 fix, in the shape production actually takes: the WRITER commits on a
    DIFFERENT connection than the poller, over a FILE-backed store with a real pool that
    hands out fresh connections. The pinned data_version probe must still bump the key.

    The old same-connection probe passed a same-session test yet went blind here: a poll on
    a fresh pooled connection after another connection's commit re-read total_changes()==0
    and a connection-local data_version, so the key never moved and the stale count was
    served for the whole TTL. NullPool = a fresh connection per session, exactly the
    production overflow pool that closes connections on return (verified: under it the old
    probe returns the SAME key across the write; this fix returns a bumped one)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'oo.db'}", future=True, poolclass=NullPool)
    Base.metadata.create_all(engine)
    with engine.connect() as c:  # WAL, like production, so a writer never blocks the probe
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
    Sess = sessionmaker(bind=engine, future=True)

    poller_a = Sess()
    k1 = insights._status_cache_key(poller_a)
    assert insights._status_cache_key(Sess()) == k1, "no write between polls -> the same key (a cache HIT)"

    # A DIFFERENT session/connection writes and commits (the production shape).
    writer = Sess()
    writer.add(Source(name="S", domain="x.test"))
    writer.commit()
    writer.close()

    # A FRESH poller on a FRESH connection must see the bumped key (never the stale count).
    k3 = insights._status_cache_key(Sess())
    assert k3 != k1, "a commit on another connection must bump the key so progress stays live"

    # A different DB (its own engine) must never collide with this one's cached status.
    engine2 = create_engine(f"sqlite:///{tmp_path / 'oo2.db'}", future=True)
    Base.metadata.create_all(engine2)
    assert insights._status_cache_key(sessionmaker(bind=engine2, future=True)()) != k3
    engine.dispose()
    engine2.dispose()


def test_status_endpoint_serves_fresh_count_after_a_cross_connection_write(tmp_path):
    """End-to-end: two polls of the cached endpoint straddling a commit on a DIFFERENT
    connection return DIFFERENT (live) counts — the cache never serves the stale number
    through a write it could not see on the poller's own fresh connection."""
    if insights._CACHE_TTL_S <= 0:
        pytest.skip("insights read-cache disabled in this env")
    engine = create_engine(f"sqlite:///{tmp_path / 'oo.db'}", future=True, poolclass=NullPool)
    Base.metadata.create_all(engine)
    with engine.connect() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
    Sess = sessionmaker(bind=engine, future=True)

    first = insights.insights_status(Sess())
    assert first["keywords"] == 0 and first.get("cached") is False

    writer = Sess()
    writer.add(Keyword(term="Election", normalized_term="election", language="en"))
    writer.commit()
    writer.close()

    second = insights.insights_status(Sess())
    assert second["keywords"] == 1, "the fresh poll must reflect the other connection's commit"
    assert second.get("cached") is False, "the key changed -> a real recompute, not a stale hit"
    engine.dispose()


def test_status_endpoint_caches_identical_polls(db):
    _seed(db, n=2)
    if insights._CACHE_TTL_S <= 0:
        pytest.skip("insights read-cache disabled in this env")
    first = insights.insights_status(db)
    second = insights.insights_status(db)
    assert first["mentions"] == second["mentions"]
    assert first.get("cached") is False and second.get("cached") is True
