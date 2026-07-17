"""Flood/bury card #4 — the BURY half: a source under-covering a topic that is big across
the rest of the corpus, screened over every (source, topic) pair with BH-FDR correction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.concentration import find_buried_topics
from src.database.models import Article, Base, Keyword, KeywordMention, Source

WHEN = date.today() - timedelta(days=5)  # inside the 30-day window


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _keyword(db, kid, term):
    db.add(Keyword(id=kid, term=term, normalized_term=term))
    db.commit()


def _source(db, sid, name):
    db.add(Source(id=sid, name=name, domain=f"{name}.test"))
    db.commit()


_ART = [0]


def _articles_with_topic(db, source_id, n, keyword_id):
    """Create ``n`` articles for a source, each mentioning ``keyword_id`` once."""
    for _ in range(n):
        _ART[0] += 1
        aid = _ART[0]
        db.add(Article(
            id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}",
            source_id=source_id, title="T", content="c", hash=f"h{aid}",
            published_at=datetime(WHEN.year, WHEN.month, WHEN.day, tzinfo=UTC),
            created_at=datetime.now(UTC),
        ))
        db.add(KeywordMention(
            keyword_id=keyword_id, article_id=aid, source_id=source_id,
            observed_on=WHEN, count=1,
        ))
    db.commit()


def _articles_no_topic(db, source_id, n, keyword_id):
    """Create ``n`` articles for a source, each mentioning a DIFFERENT topic (not the big one)."""
    for _ in range(n):
        _ART[0] += 1
        aid = _ART[0]
        db.add(Article(
            id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}",
            source_id=source_id, title="T", content="c", hash=f"h{aid}",
            published_at=datetime(WHEN.year, WHEN.month, WHEN.day, tzinfo=UTC),
            created_at=datetime.now(UTC),
        ))
        db.add(KeywordMention(
            keyword_id=keyword_id, article_id=aid, source_id=source_id,
            observed_on=WHEN, count=1,
        ))
    db.commit()


def _seed_bury(db):
    _ART[0] = 0
    _keyword(db, 1, "climate")  # the big topic
    _keyword(db, 2, "sports")   # the target's beat (niche, one source)
    # Six sources cover the big topic heavily -> it is broad (>= 5 sources, >= 25 articles).
    for sid in range(1, 7):
        _source(db, sid, f"broad{sid}")
        _articles_with_topic(db, sid, 20, keyword_id=1)
    # The target source is active (30 articles) but covers the big topic ZERO -> the gap.
    _source(db, 7, "target")
    _articles_no_topic(db, 7, 30, keyword_id=2)


def test_bury_flags_the_under_covering_source(db):
    _seed_bury(db)
    out = find_buried_topics(db)
    assert out["count"] >= 1
    hit = next(i for i in out["items"] if i["source"] == "target")
    assert hit["term"] == "climate"
    assert hit["source_share"] == 0.0          # target covered the big topic zero
    assert hit["corpus_share"] > 0.5           # the rest of the corpus covered it heavily
    assert hit["gap_zscore"] <= -3.0           # the effect gate
    assert hit["fdr_qvalue"] is not None and hit["fdr_qvalue"] <= 0.05  # survived FDR
    assert out["tests"] >= 1                   # the correction ran over the family


def test_a_proportional_source_is_not_buried(db):
    _seed_bury(db)
    # A source that covers the big topic ~proportionally must NOT be flagged.
    _source(db, 8, "proportional")
    _articles_with_topic(db, 8, 16, keyword_id=1)  # 16/20 climate, like the corpus
    _articles_no_topic(db, 8, 4, keyword_id=2)
    out = find_buried_topics(db)
    flagged = {i["source"] for i in out["items"]}
    assert "proportional" not in flagged
    assert "target" in flagged  # the real gap still surfaces


def test_no_broad_topic_no_finding(db):
    # A corpus with no topic broad across >= min_corpus_sources sources yields nothing
    # (honest empty state, not a fabricated flag).
    _ART[0] = 0
    _keyword(db, 1, "climate")
    _source(db, 1, "s1")
    _source(db, 2, "s2")
    _articles_with_topic(db, 1, 30, keyword_id=1)  # only ONE source covers climate
    _articles_no_topic(db, 2, 30, keyword_id=1)    # actually the same kw, 2 sources... keep it niche
    out = find_buried_topics(db, min_corpus_sources=5)
    assert out["count"] == 0
    assert "note" in out


def test_bury_does_not_flag_a_cross_language_source(db):
    """B3 / field test 2026-07-08: a non-English source must NOT be flagged for 'burying'
    an English keyword it simply never uses (it writes in its own language). Same-language
    cohort scoping excludes a pair KNOWN to be in different languages."""
    _ART[0] = 0
    # An English keyword covered heavily by six English sources -> broad.
    db.add(Keyword(id=1, term="election", normalized_term="election", language="en"))
    db.add(Keyword(id=2, term="sports", normalized_term="sports", language="en"))
    db.add(Keyword(id=3, term="verkiezingen", normalized_term="verkiezingen", language="nl"))
    db.commit()
    for sid in range(1, 7):
        db.add(Source(id=sid, name=f"en{sid}", domain=f"en{sid}.test", language="en"))
    db.commit()
    for sid in range(1, 7):
        _articles_with_topic(db, sid, 20, keyword_id=1)  # en sources cover the en keyword
    # A Dutch source, active, covers the EN keyword zero (it writes Dutch) -> would be a
    # false "bury" of "election" WITHOUT language scoping.
    db.add(Source(id=7, name="nl-source", domain="nl.test", language="nl"))
    db.commit()
    _articles_with_topic(db, 7, 30, keyword_id=3)  # covers its OWN-language topic instead

    out = find_buried_topics(db)
    flagged = {i["source"] for i in out["items"]}
    assert "nl-source" not in flagged, "a Dutch source must not be flagged for burying an English keyword"
    assert out.get("same_language_scoped") is True


def test_bury_producer_emits_a_valid_no_score_card(db):
    from src.briefing.producers import buried_topic

    _seed_bury(db)
    cards = buried_topic(db)
    assert cards, "expected a bury card"
    c = cards[0]
    assert c.type == "buried_topic" and c.bucket == "investigate"
    # The signal carries components, never a blended score (Card schema also enforces this).
    assert c.signal["metric"] == "gap_zscore"
    assert "corpus_share" in c.signal and "fdr_qvalue" in c.signal
    assert c.method and c.caveat and c.trigger
    # No score-shaped key anywhere in the signal.
    assert not any(k in ("score", "rating", "rank") for k in c.signal)


def test_bury_card_and_finding_carry_the_exact_analyzed_article_set():
    """Audit finding 2026-07-17: buried_topic's Card never set ``article_ids``, unlike
    its sibling flooded_topic -- so clicking the card fell back to a synthetic
    search-seed key (``f"bury:{source_id}:{term}"``) that re-runs a DIFFERENT query on
    click instead of opening the exact set the finding was actually computed over (the
    "Home cards lose their corpus on click" bug class). The under-covering source's OWN
    on-topic set is typically near-empty by construction (that IS the finding) so the
    useful, honest analyzed set to open is the widely-covered topic's OWN corpus-wide
    articles in the window -- the "elsewhere" the source is missing."""
    from src.briefing.producers import buried_topic

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    _seed_bury(db)

    out = find_buried_topics(db)
    hit = next(i for i in out["items"] if i["source"] == "target")
    assert hit["article_ids"], "the finding must carry the exact analyzed article set"
    # It is the big topic's corpus-wide window articles (6 sources * 20 = 120), never a
    # synthetic placeholder and never the source's own (near-)empty on-topic set.
    assert len(hit["article_ids"]) == 120
    assert len(set(hit["article_ids"])) == len(hit["article_ids"])  # distinct ids

    cards = buried_topic(db)
    c = next(c for c in cards if "target" in c.title)
    assert c.article_ids == hit["article_ids"]
