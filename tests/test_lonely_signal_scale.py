"""Lonely-signal scale-aware selection (Leads-calibration S4.1, row 6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-18 field export: "three cards, all GIGAZINE" -- a prolific single-source
publisher claimed every lonely-signal slot, and at real scale single-source coverage
is the norm, not a signal. These tests pin: at most one card per source per refresh,
and above the large-corpus threshold a candidate needs to intersect a trending term.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.briefing import producers as P
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


# Genuinely DIFFERENT texts (not a shared template with one number swapped) so the
# near-duplicate engine never accidentally clusters distinct stories together --
# each must register as its own independent singleton.
_BODIES = [
    "Municipal engineers began a multi-week inspection of the harbour bridge cabling "
    "after a routine sensor reading flagged unusual vibration patterns overnight. The "
    "crew plans to publish a full structural report once every cable segment has been "
    "checked, and traffic will be rerouted onto the parallel span in the meantime.",
    "A regional grain cooperative reported a sharp jump in warehouse humidity readings "
    "following an unseasonal week of heavy rainfall across the eastern farmland belt. "
    "Managers say dehumidifiers have been brought in and spoilage so far looks limited "
    "to a small fraction of the newest intake, with older stock unaffected.",
    "Archivists at the university library finished digitising a decades-old collection "
    "of shipping manifests donated by a retired harbourmaster earlier this spring. The "
    "scanned pages will be searchable online within a few months, giving researchers a "
    "detailed record of cargo movements through the port across several decades.",
    "A local astronomy club recorded an unusually bright meteor trail over the valley "
    "just after midnight, drawing dozens of amateur observers to the hillside. Members "
    "compared notes on the object's apparent speed and colour, and several are hoping "
    "to submit their footage to a national fireball-tracking network for review.",
]


def _single_source_story(db, aid, source_id, *, body_index=0, days_ago=1):
    db.add(Article(
        id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
        source_id=source_id, title=f"Story {aid}", content=_BODIES[body_index],
        hash=f"h{aid}", language="en",
        published_at=datetime.now(UTC) - timedelta(days=days_ago),
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    ))


def test_at_most_one_card_per_source_per_refresh(db):
    db.add(Source(id=1, name="GIGAZINE", domain="gigazine.test"))
    db.commit()
    # Three separate, non-echoing single-source stories -- all from the SAME source.
    for i, aid in enumerate((101, 102, 103)):
        _single_source_story(db, aid, source_id=1, body_index=i, days_ago=i)
    db.commit()

    cards = P.lonely_signal(db)
    sources = [c.signal["source"] for c in cards]
    assert len(cards) == 1, cards  # never 3 cards from the same publisher
    assert sources == ["GIGAZINE"]


def test_below_large_corpus_threshold_fires_normally(db):
    db.add(Source(id=1, name="A", domain="a.test"))
    db.add(Source(id=2, name="B", domain="b.test"))
    db.commit()
    _single_source_story(db, 201, source_id=1, body_index=0, days_ago=0)
    _single_source_story(db, 202, source_id=2, body_index=1, days_ago=1)
    db.commit()

    cards = P.lonely_signal(db)
    assert len(cards) == 2  # different sources, small corpus -> no trending gate applied


def test_large_corpus_requires_a_trending_term_intersection(db, monkeypatch):
    """S4.1: above the large-corpus threshold, a lonely-signal candidate must
    intersect a currently-trending term to claim a Lead slot -- an isolated,
    non-trending single-source story stays in exploration, never a card."""
    monkeypatch.setattr(P, "_LONELY_LARGE_CORPUS_ARTICLES", 1)  # simulate scale cheaply

    db.add(Source(id=1, name="A", domain="a.test"))
    db.add(Source(id=2, name="B", domain="b.test"))
    db.commit()
    _single_source_story(db, 301, source_id=1, body_index=0, days_ago=0)  # no keywords -> never trends
    _single_source_story(db, 302, source_id=2, body_index=1, days_ago=1)
    db.commit()
    assert P.lonely_signal(db) == []  # neither story intersects any trending term

    # Now make story 301's keyword genuinely trending (a real recent-mentions sum;
    # trending() sums KeywordMention.count over the window -- one row is enough).
    kw = Keyword(term="floodwatch", normalized_term="floodwatch", language="en")
    db.add(kw)
    db.flush()
    today = datetime.now(UTC).date()
    db.add(KeywordMention(keyword_id=kw.id, article_id=301, count=6, observed_on=today))
    db.commit()

    cards = P.lonely_signal(db)
    assert len(cards) == 1
    assert cards[0].article_ids == [301]
