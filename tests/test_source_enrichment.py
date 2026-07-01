"""
Tests for applying corpus-deduced topics to the live Source.tags (Strategy 1 auto).

Uses an in-memory SQLite corpus (needs sqlalchemy -> runs in CI). The pure
aggregation is covered separately in tests/test_source_topics.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.source_topics import (
    apply_source_topics,
    enrichment_due,
    run_auto_source_enrichment,
)
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordMention,
    KeywordTag,
    Source,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, *, n_articles=6, topic="politics", tags="news"):
    src = Source(name="Src", domain="src.test", tags=tags)
    db.add(src)
    db.flush()
    kw = Keyword(term="election", normalized_term="election", language="en")
    db.add(kw)
    db.flush()
    db.add(KeywordTag(keyword_id=kw.id, axis="topic", tag=topic, source="baseline"))
    for i in range(n_articles):
        a = Article(
            url=f"https://src.test/{i}",
            canonical_url=f"https://src.test/{i}",
            source_id=src.id,
            title="T",
            content="election",
            hash=f"h{i}",
            language="en",
        )
        db.add(a)
        db.flush()
        db.add(
            KeywordMention(keyword_id=kw.id, article_id=a.id, count=1, source_id=src.id)
        )
    db.commit()
    return src


def test_apply_unions_deduced_topic_into_source_tags(db):
    _seed(db, n_articles=6, topic="politics")
    res = apply_source_topics(db, min_articles=5)
    assert res["sources_updated"] == 1
    src = db.query(Source).filter_by(domain="src.test").one()
    tags = [t.strip() for t in (src.tags or "").split(",")]
    assert "news" in tags  # curated tag preserved
    assert "politics" in tags  # deduced topic added


def test_apply_is_idempotent(db):
    _seed(db, n_articles=6, topic="politics")
    apply_source_topics(db, min_articles=5)
    res2 = apply_source_topics(db, min_articles=5)
    assert res2 == {"sources_updated": 0, "tags_added": 0}


def test_apply_respects_min_articles_floor(db):
    _seed(db, n_articles=3, topic="politics")  # below floor
    res = apply_source_topics(db, min_articles=5)
    assert res == {"sources_updated": 0, "tags_added": 0}
    src = db.query(Source).filter_by(domain="src.test").one()
    assert "politics" not in (src.tags or "")


def test_auto_wrapper_is_freshness_gated(db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.analytics.source_topics._state_path", lambda: tmp_path / "enrich.json"
    )
    _seed(db, n_articles=6, topic="politics")
    first = run_auto_source_enrichment(db, min_interval_hours=24)
    assert first["ran"] is True and first["sources_updated"] == 1
    # marker written -> second call within the interval is skipped
    assert enrichment_due(min_interval_hours=24) is False
    second = run_auto_source_enrichment(db, min_interval_hours=24)
    assert second == {"ran": False}
