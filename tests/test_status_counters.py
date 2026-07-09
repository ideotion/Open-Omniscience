"""/status serves the mention total from maintained counters + a data-aware cache (Item 8 P1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The field diagnostic showed ``SELECT count(*) FROM keyword_mentions`` (a full scan of the
multi-GB mention table through the SQLCipher codec) as the single slowest query — 724 ms ×
172 polls of /status. These tests pin the two fixes: (1) ``mentions`` is served from the
maintained per-keyword counter and is EXACT-equal to the real row count; (2) the /status
cache key is data-aware, so repeat polls hit the cache but any WRITE (or a different DB)
invalidates it — never a stale-through-a-write count, never a wrong-corpus serve.
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
from src.database.models import Article, Base, KeywordMention, Source


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


def test_status_mentions_equals_the_real_mention_row_count(db):
    _seed(db)
    st = q.status(db)
    real = db.query(func.count(KeywordMention.id)).scalar() or 0
    summed = db.query(func.coalesce(func.sum(insights.q.Keyword.article_count), 0)).scalar() or 0
    assert real > 0
    # The maintained-counter derivation is EXACT-equal to count(*) FROM keyword_mentions.
    assert st["mentions"] == real == int(summed)


def test_status_reports_the_counter_honesty_envelope(db):
    _seed(db)
    st = q.status(db)
    assert "counters" in st
    env = st["counters"]
    assert env["basis"] in ("exact", "estimated")
    assert env["as_of"] and "method" in env  # a real as_of, never fabricated
    assert st["mentions_basis"].startswith("maintained per-keyword counters")
    # No score field anywhere in the disclosure.
    assert not any("score" in k.lower() for k in st)
    assert not any("score" in k.lower() for k in env)


def test_status_returns_the_real_progress_numbers(db):
    _seed(db, n=3)
    st = q.status(db)
    assert st["total_articles"] == 3
    assert st["indexed_articles"] == 3  # all indexed
    assert st["remaining"] == 0
    assert st["keywords"] > 0


def test_status_cache_key_is_data_aware():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()

    k1 = insights._status_cache_key(s)
    k2 = insights._status_cache_key(s)
    assert k1 == k2, "no write between polls -> the same key (a cache HIT)"

    s.add(Source(name="S", domain="x.test"))
    s.commit()
    k3 = insights._status_cache_key(s)
    assert k3 != k1, "a write must bump the key so progress stays live"

    # A different DB (its own engine) must never collide with this one's cached status.
    engine2 = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine2)
    s2 = sessionmaker(bind=engine2, future=True)()
    assert insights._status_cache_key(s2) != k3


def test_status_endpoint_caches_identical_polls(db):
    _seed(db, n=2)
    if insights._CACHE_TTL_S <= 0:
        pytest.skip("insights read-cache disabled in this env")
    first = insights.insights_status(db)
    second = insights.insights_status(db)
    assert first["mentions"] == second["mentions"]
    assert first.get("cached") is False and second.get("cached") is True
