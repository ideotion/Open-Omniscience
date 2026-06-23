"""Source flood detection (manipulation-pattern card #4, ruling #13 + Q8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the honest gates: fires when a source's recent share of a topic jumps far above
its OWN prior share; stays silent when the share is consistently high (no jump), when
there's too little baseline, or when the share is small. No score; the comparison is
the source's own history; reads only the denormalised source_id.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.concentration import find_flooded_topics
from src.database.models import Base, Keyword, KeywordMention, Source

TODAY = date.today()
RECENT = TODAY - timedelta(days=2)
PRIOR = TODAY - timedelta(days=30)
K = 1       # the flooded keyword
FILLER = 99  # other coverage (denominator filler)

# Looser thresholds so the scenarios stay small.
KW = dict(min_recent_articles=4, min_prior_articles=6, min_share=0.25, z_min=2.5)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    for sid in range(1, 5):
        s.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.test"))
    s.add(Keyword(id=K, term="floodterm", normalized_term="floodterm"))
    s.add(Keyword(id=FILLER, term="other", normalized_term="other"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


_aid = [1000]


def _km(db, source_id, keyword_id, observed):
    _aid[0] += 1
    db.add(KeywordMention(
        source_id=source_id, keyword_id=keyword_id, article_id=_aid[0], count=1, observed_on=observed,
    ))


def _spread(db, source_id, when, n, k_hits):
    """n distinct articles for `source_id` at `when`: k_hits mention K, the rest FILLER."""
    for i in range(n):
        _km(db, source_id, K if i < k_hits else FILLER, when)
    db.commit()


def test_fires_when_a_source_floods_a_topic(db):
    # Source 1: recently ALL about K (5/5), but historically rare (1/8).
    _spread(db, 1, RECENT, n=5, k_hits=5)
    _spread(db, 1, PRIOR, n=8, k_hits=1)
    res = find_flooded_topics(db, **KW)
    assert res["count"] == 1, res
    it = res["items"][0]
    assert it["term"] == "floodterm" and it["source"] == "S1"
    assert it["share_now"] > it["baseline_share"] and it["share_zscore"] >= KW["z_min"]
    assert len(it["article_ids"]) == 5


def test_silent_when_share_is_consistently_high(db):
    # Source 2: K is its beat both now AND before -> no jump -> no flood.
    _spread(db, 2, RECENT, n=5, k_hits=5)
    _spread(db, 2, PRIOR, n=8, k_hits=8)
    assert find_flooded_topics(db, **KW)["count"] == 0


def test_silent_without_enough_baseline(db):
    # Source 3: floods K recently but has < min_prior_articles of history.
    _spread(db, 3, RECENT, n=5, k_hits=5)
    _spread(db, 3, PRIOR, n=3, k_hits=0)
    assert find_flooded_topics(db, **KW)["count"] == 0


def test_silent_below_min_share(db):
    # Source 4: K is a small share of recent coverage -> not a flood.
    _spread(db, 4, RECENT, n=8, k_hits=1)
    _spread(db, 4, PRIOR, n=8, k_hits=1)
    assert find_flooded_topics(db, **KW)["count"] == 0


def test_no_score_and_caveat(db):
    _spread(db, 1, RECENT, n=5, k_hits=5)
    _spread(db, 1, PRIOR, n=8, k_hits=1)
    res = find_flooded_topics(db, **KW)
    assert res["caveat"] and res["method"]
    for it in res["items"]:
        assert not any(k.lower() == "score" or k.lower().endswith("_score") for k in it)
