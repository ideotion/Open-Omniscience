"""Audit finding 2026-07-17: two whole-corpus attention producers -- diet_self_audit
(concentration over your own reading diet) and capacity_implausible (a source
publishing implausibly fast) -- never set ``article_ids`` on their Card, unlike
the per-topic producers (flooded_topic, buried_topic, rising_now...). Clicking such a
card fell back to a synthetic literal-text search on the card's ``key`` (``"diet"``
/ ``"capacity"``), which re-runs an unrelated query instead of opening the exact
set the signal was actually computed over (the "Home cards lose their corpus on
click" bug class).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _article(db, source_id, aid, *, days_ago=1):
    now = datetime.now(UTC)
    db.add(Article(
        id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
        source_id=source_id, title="T", content="c", hash=f"h{aid}",
        published_at=now - timedelta(days=days_ago),
        created_at=now - timedelta(days=days_ago),
    ))


def test_diet_self_audit_carries_the_exact_windowed_article_set(db):
    from src.briefing.producers import diet_self_audit

    db.add(Source(id=1, name="Big", domain="big.test"))
    db.add(Source(id=2, name="Small", domain="small.test"))
    db.commit()
    aid = 0
    for _ in range(8):
        aid += 1
        _article(db, 1, aid)
    for _ in range(2):
        aid += 1
        _article(db, 2, aid)
    db.commit()

    cards = diet_self_audit(db)
    assert cards, "expected a diet_self_audit card"
    c = cards[0]
    assert c.article_ids, "must carry the exact set the concentration stat was computed over"
    assert len(c.article_ids) == 10  # every article in the 30-day window, not a placeholder
    assert set(c.article_ids) == set(range(1, 11))
    assert c.key == "diet"  # the key stays a stable per-type id; the click no longer uses it as a query


def test_capacity_implausible_carries_the_flagged_sources_own_articles(db):
    from src.briefing.producers import capacity_implausible

    # Three normal-rate sources (median ~1/day) + one implausibly fast source.
    db.add(Source(id=1, name="Normal1", domain="n1.test"))
    db.add(Source(id=2, name="Normal2", domain="n2.test"))
    db.add(Source(id=3, name="Normal3", domain="n3.test"))
    db.add(Source(id=4, name="Firehose", domain="firehose.test"))
    db.commit()
    aid = 0
    for sid in (1, 2, 3):
        for day in range(14):
            aid += 1
            _article(db, sid, aid, days_ago=day)
    firehose_ids = []
    for _ in range(400):  # ~29/day over 14 days, well above the 20/day floor and the median*8 gate
        aid += 1
        firehose_ids.append(aid)
        _article(db, 4, aid, days_ago=aid % 14)
    db.commit()

    cards = capacity_implausible(db)
    assert cards, "expected a capacity_implausible card"
    c = cards[0]
    assert "Firehose" in c.summary
    assert c.article_ids, "must carry the flagged source's own articles, not a placeholder"
    assert set(c.article_ids) == set(firehose_ids)
    assert c.key == "capacity"


def test_capacity_implausible_quiet_without_an_implausible_source(db):
    from src.briefing.producers import capacity_implausible

    db.add(Source(id=1, name="A", domain="a.test"))
    db.add(Source(id=2, name="B", domain="b.test"))
    db.add(Source(id=3, name="C", domain="c.test"))
    db.commit()
    aid = 0
    for sid in (1, 2, 3):
        for day in range(14):
            aid += 1
            _article(db, sid, aid, days_ago=day)
    db.commit()
    assert capacity_implausible(db) == []
