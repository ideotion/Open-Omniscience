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


def test_min_recent_count_floor_blocks_a_small_sample(db):
    """Row 5 (2026-07-18 field export): a two-proportion z-test on 2-3 articles is not a
    valid sample for the normal approximation, however large z comes out — a count floor
    on the keyword's OWN recent mentions (not just the source's total article count) is
    required."""
    db.add(Source(id=5, name="S5", domain="s5.test"))
    db.add(Keyword(id=502, term="rareterm", normalized_term="rareterm"))
    db.commit()
    for aid in range(1, 5):  # 4 recent articles, 3 mention the candidate keyword
        _km(db, 5, 502 if aid <= 3 else FILLER, RECENT)
    for _ in range(8):  # 8 prior articles, the keyword essentially absent
        _km(db, 5, FILLER, PRIOR)
    db.commit()
    assert find_flooded_topics(db, **KW)["count"] == 0


def test_generic_furniture_term_never_floods_but_a_real_event_term_does(db):
    """Row 4 (2026-07-18 field export, RTV SLO "vir"/"lani"): a term carried by nearly
    every active same-language source is publishing furniture, not a real topic, even
    when its own per-source z-test would otherwise fire — while a term concentrated in
    ONE source (a genuine event) still surfaces."""
    for sid in (10, 11, 12):
        db.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.test", language="sl"))
    db.add(Keyword(id=601, term="vir", normalized_term="vir", language="sl"))
    db.add(Keyword(id=602, term="event602", normalized_term="event602", language="sl"))
    db.commit()

    # Source 10: a real jump on BOTH terms (so the generic gate — not an earlier gate —
    # is what has to stop "vir").
    for _ in range(15):
        _km(db, 10, 602, RECENT)  # event602
    for _ in range(15):
        _km(db, 10, 601, RECENT)  # vir
    for _ in range(20):
        _km(db, 10, FILLER, PRIOR)  # both essentially absent historically

    # Sources 11/12: only "vir" (attribution-line furniture on nearly every article,
    # regardless of publisher) — never "event602" (which stays a single-source story).
    _km(db, 11, 601, RECENT)
    _km(db, 12, 601, RECENT)
    db.commit()

    res = find_flooded_topics(db, **KW)
    terms = {it["term"] for it in res["items"]}
    assert "vir" not in terms, res["items"]  # ubiquitous across active sl sources -> gated
    assert "event602" in terms, res["items"]  # concentrated in one source -> a real flood
    assert "carried by" in res["method"] or "same-language" in res["method"]


def test_internal_channel_source_is_exempt_from_flood_candidacy(db):
    """Row 7 (2026-07-18 field export): a newsletter import / law tracker / wiki edition
    is the user's own import channel, not a publisher whose 'conduct' this producer
    should be judging."""
    db.add(Source(id=6, name="Law tracker", domain="law.us.local", source_type="legal"))
    db.commit()
    _spread(db, 6, RECENT, n=5, k_hits=5)
    _spread(db, 6, PRIOR, n=8, k_hits=1)
    res = find_flooded_topics(db, **KW)
    assert res["count"] == 0, res
    assert "publisher" in res["method"]


def test_no_score_and_caveat(db):
    _spread(db, 1, RECENT, n=5, k_hits=5)
    _spread(db, 1, PRIOR, n=8, k_hits=1)
    res = find_flooded_topics(db, **KW)
    assert res["caveat"] and res["method"]
    for it in res["items"]:
        assert not any(k.lower() == "score" or k.lower().endswith("_score") for k in it)
