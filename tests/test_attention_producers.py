"""
S6.4 — the two attention producers ("On the horizon" + "Through time").

Both are secondary sense-making lenses (buckets watch/context) — never promoted into an
urgent alert (the ruled boundary). Counts only, no score; honest empty states; cross-time
recall stays sacred (Through time is a lens, never a reweighting).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.briefing import producers as P
from src.briefing.card import BUCKETS
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    try:
        yield s
    finally:
        s.close()


def _article(s, n, when):
    a = Article(
        url=f"https://s.test/{n}", canonical_url=f"https://s.test/{n}", source_id=1,
        title=f"Story {n}", content="body", hash=f"h{n}", published_at=when,
    )
    s.add(a)
    s.flush()
    return a


def _no_score(card):
    d = card.to_dict()
    banned = ("score", "rating", "ranking", "verdict", "credibility")

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in banned), f"score key {k!r}"
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(d)


# --- Through time (anniversary lens) ------------------------------------------------- #
def test_through_time_fires_on_this_day_in_past_years(db):
    from datetime import datetime

    today = date.today()
    for i, yr in enumerate((today.year - 1, today.year - 2, today.year - 3)):
        _article(db, i, datetime(yr, today.month, today.day, 9, 0))
    # a decoy on a different day + one in the CURRENT year (must be excluded)
    _article(db, 8, datetime(today.year - 1, today.month, max(1, (today.day % 27) + 1), 9))
    _article(db, 9, datetime(today.year, today.month, today.day, 9))
    db.commit()

    cards = P.through_time(db, today=today)
    assert len(cards) == 1
    c = cards[0]
    assert c.bucket == "context" and c.bucket in BUCKETS
    assert c.signal["value"] == 3 and len(c.article_ids) == 3  # current-year + decoy excluded
    assert today.year not in c.signal["years"]  # past years only
    _no_score(c)


def test_through_time_floor_is_honest_empty(db):
    from datetime import datetime

    today = date.today()
    _article(db, 0, datetime(today.year - 1, today.month, today.day, 9))
    db.commit()
    assert P.through_time(db, today=today) == []  # < 3 -> no card


# --- On the horizon (upcoming event ∩ trending keyword) ------------------------------ #
def _seed_trending(db, term, normalized):
    kw = Keyword(term=term, normalized_term=normalized, language="en")
    db.add(kw)
    db.flush()
    today = date.today()
    for i in range(4):  # >= min_recent, all recent, no prior -> trends
        a = _article(db, 100 + i, None)
        db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=2, observed_on=today))
    db.commit()
    return kw


def test_on_the_horizon_matches_a_trending_keyword_to_an_upcoming_event(db):
    _seed_trending(db, "election", "election")
    today = date.today()
    event = {
        "title": "General election 2026",
        "tags": ["election", "politics"],
        "next_occurrence": (today + timedelta(days=10)).isoformat(),
    }
    cards = P.on_the_horizon(db, today=today, events=[event])
    assert len(cards) == 1
    c = cards[0]
    assert c.bucket == "watch" and c.type == "on_the_horizon"
    assert c.signal["value"] == 10 and c.signal["term"] == "election"
    assert "election" in c.key
    _no_score(c)


def test_on_the_horizon_empty_when_no_event_or_no_match(db):
    _seed_trending(db, "election", "election")
    today = date.today()
    # an upcoming event that does NOT mention any trending term
    far = {"title": "Rugby final", "tags": ["sport"], "next_occurrence": (today + timedelta(days=5)).isoformat()}
    assert P.on_the_horizon(db, today=today, events=[far]) == []
    # a matching event but too far out (beyond the 45-day horizon)
    late = {"title": "General election", "tags": ["election"], "next_occurrence": (today + timedelta(days=120)).isoformat()}
    assert P.on_the_horizon(db, today=today, events=[late]) == []
    # no events at all
    assert P.on_the_horizon(db, today=today, events=[]) == []


def test_both_producers_are_registered_fail_safe_last(db):
    names = [n for n, _ in P._DEFAULT_PRODUCERS]
    assert "on_the_horizon" in names and "through_time" in names
    # registered after the core producers (fail-safe order — Home never goes blank)
    assert names.index("on_the_horizon") > names.index("rising_now")
