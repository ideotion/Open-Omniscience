"""Manufactured-emergence detection (manipulation-pattern card #3, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the honest gates: fires on a NEW + born-wide + UN-anchored term; stays silent
when there IS a datable anchor (genuine news), when only one source carries it (not
born-wide), or when the term is not new. No score.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.emergence import find_manufactured_emergence
from src.database.models import (
    Article,
    ArticleMentionedDate,
    Base,
    Keyword,
    KeywordMention,
    Source,
)

TODAY = date.today()
RECENT = TODAY - timedelta(days=2)   # inside the 7-day window
OLD = TODAY - timedelta(days=20)     # inside the prior 30-day window


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for sid in range(1, 6):
        s.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.test"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


def _kw(db, kid, term):
    db.add(Keyword(id=kid, term=term, normalized_term=term))
    db.commit()


def _mention(db, kid, aid, source_id, observed):
    if db.get(Article, aid) is None:
        db.add(Article(
            id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}",
            source_id=source_id, title="T", content="body", hash=f"h{aid}",
            published_at=datetime(observed.year, observed.month, observed.day, tzinfo=UTC),
        ))
        db.flush()
    db.add(KeywordMention(keyword_id=kid, article_id=aid, count=1, observed_on=observed))
    db.commit()


def test_fires_on_new_wide_unanchored_term(db):
    _kw(db, 1, "novelterm")
    for i, sid in enumerate([1, 2, 3, 4, 5]):  # 5 articles across 5 distinct sources
        _mention(db, 1, 100 + i, sid, RECENT)
    res = find_manufactured_emergence(db)
    assert res["count"] == 1, res
    it = res["items"][0]
    assert it["term"] == "novelterm"
    assert it["recent_sources"] == 5 and it["prior_count"] == 0
    assert it["anchored"] is False
    assert len(it["article_ids"]) == 5


def test_silent_when_anchored(db):
    _kw(db, 1, "anchoredterm")
    for i, sid in enumerate([1, 2, 3, 4]):
        _mention(db, 1, 200 + i, sid, RECENT)
    # One article cites a datable event near the onset -> anchored -> suppressed.
    db.add(ArticleMentionedDate(
        article_id=200, mentioned_on=RECENT - timedelta(days=1), precision="day", status="candidate",
    ))
    db.commit()
    assert find_manufactured_emergence(db)["count"] == 0


def test_silent_when_single_source(db):
    _kw(db, 1, "chattyterm")
    for aid in range(300, 306):  # 6 recent articles ALL from source 1
        _mention(db, 1, aid, 1, RECENT)
    assert find_manufactured_emergence(db)["count"] == 0  # not born-wide


def test_silent_when_not_new(db):
    _kw(db, 1, "oldterm")
    for aid in range(400, 405):  # clearly-established prior history (> max_prior)
        _mention(db, 1, aid, 1, OLD)
    for i, sid in enumerate([1, 2, 3, 4]):
        _mention(db, 1, 410 + i, sid, RECENT)
    assert find_manufactured_emergence(db)["count"] == 0  # prior_count > max_prior


def test_no_score_and_caveat_present(db):
    _kw(db, 1, "novelterm")
    for i, sid in enumerate([1, 2, 3]):
        _mention(db, 1, 500 + i, sid, RECENT)
    res = find_manufactured_emergence(db)
    assert res["caveat"] and res["method"]
    for it in res["items"]:
        assert not any("score" in k.lower() for k in it)
