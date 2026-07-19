"""Headline-body mismatch detection (manipulation-pattern card #7, ruling #13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Names the STRUCTURE: a headline that leads with content the body does not
substantiate. These tests pin the honest gates — lexical divergence d_lex fires a
clear mismatch and stays silent on an on-topic headline; a thin headline never
fires; the sentiment gap is English-only; and the item carries components, never a
score.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.headline_body import find_headline_body_mismatch
from src.database.models import Article, Base, Source

# A rich economics body (clears min_chars; its top keywords are bank/interest/rates…).
BODY = (
    "The central bank announced on Monday that it would hold interest rates steady for "
    "the rest of the quarter, citing persistent uncertainty in global energy markets and "
    "a softer-than-expected reading on consumer demand. Officials said they would reassess "
    "the stance at the next scheduled meeting in the autumn before any further decision."
)

NOW = datetime.now().replace(microsecond=0)


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


def _src(db, sid, domain):
    db.add(Source(id=sid, name=f"Src{sid}", domain=domain))
    db.commit()


def _art(db, aid, title, body, *, lang="en", days_ago=1):
    db.add(
        Article(
            id=aid,
            url=f"https://x/{aid}",
            canonical_url=f"https://x/{aid}",
            source_id=1,
            title=title,
            content=body,
            hash=f"h{aid}",
            language=lang,
            published_at=NOW - timedelta(days=days_ago),
        )
    )
    db.commit()


def test_fires_on_lexical_divergence(db):
    _src(db, 1, "a.test")
    # Headline is about aliens/Pentagon; the body is about interest rates -> no overlap.
    _art(db, 1, "Pentagon aliens hijack interest rates in shocking new footage tonight", BODY)
    res = find_headline_body_mismatch(db)
    assert res["count"] == 1, res
    it = res["items"][0]
    assert it["article_id"] == 1
    assert it["lexical_div"] >= res["d_min"]
    # The exact divergent headline terms travel with the item (explorable, honest).
    assert "pentagon" in it["absent_terms"] and "aliens" in it["absent_terms"]


def test_no_fire_when_headline_matches_body(db):
    _src(db, 1, "a.test")
    # The headline's content words ARE the body's top keywords -> low d_lex, no fire.
    _art(db, 1, "Central bank holds interest rates steady amid global uncertainty", BODY)
    res = find_headline_body_mismatch(db)
    assert res["count"] == 0, res["items"]


def test_thin_headline_never_fires(db):
    _src(db, 1, "a.test")
    # Fewer than min_headline_terms content words -> stays silent (precision-biased).
    _art(db, 1, "Aliens!", BODY)
    assert find_headline_body_mismatch(db, min_headline_terms=3)["count"] == 0


def test_sentiment_gap_is_english_only(db):
    _src(db, 1, "a.test")
    # A non-English article never computes a sentiment gap (VADER English-only),
    # never a fabricated neutral. Lexically on-topic (German), so it does not fire.
    de_body = (
        "Die Zentralbank teilte am Montag mit, dass sie die Zinsen für den Rest des "
        "Quartals unverändert lassen werde. Beamte sagten, sie würden die Haltung bei "
        "der nächsten Sitzung im Herbst erneut bewerten, bevor weitere Entscheidungen fallen."
    )
    _art(db, 1, "Zentralbank lässt die Zinsen im Quartal unverändert", de_body, lang="de")
    res = find_headline_body_mismatch(db)
    for it in res["items"]:
        if it["lang"] != "en":
            assert it["sentiment_gap"] is None


def test_item_carries_components_never_a_score(db):
    _src(db, 1, "a.test")
    _art(db, 1, "Pentagon aliens hijack interest rates in shocking new footage tonight", BODY)
    res = find_headline_body_mismatch(db)
    it = res["items"][0]
    # Components present (incl. the SECONDARY outrage annotation)...
    assert {"lexical_div", "sentiment_gap", "lang", "absent_terms", "headline_terms", "outrage"} <= set(it)
    # ...and NO composite-score field name anywhere in the item, including the outrage sub-dict.
    def _no_score_key(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert "score" not in str(k).lower() and "ranking" not in str(k).lower()
                _no_score_key(v)
        elif isinstance(o, list):
            for x in o:
                _no_score_key(x)
    _no_score_key(it)
    # The outrage annotation is a measured component (English article) or an honest gap.
    assert "measured" in it["outrage"]
    assert res["caveat"] and res["method"]


def test_bounded_scan_only_recent(db):
    _src(db, 1, "a.test")
    # An OLD mismatching article is outside the recent window -> not scanned.
    _art(db, 1, "Pentagon aliens hijack interest rates in shocking new footage tonight", BODY, days_ago=400)
    assert find_headline_body_mismatch(db, recent_days=14)["count"] == 0


def test_high_inflection_language_is_gated_not_a_finding(db):
    """Row 12 (2026-07-18 field export): four cards, all lexical_div == 1.0, including
    two Estonian -- a highly-inflected language where bare surface-form comparison is
    unreliable. An Estonian article must produce NO card, regardless of how divergent
    the (unreliable) measure would otherwise look."""
    _src(db, 1, "a.test")
    _art(db, 1, "Pentagon aliens hijack interest rates in shocking new footage tonight",
         BODY, lang="et")
    res = find_headline_body_mismatch(db)
    assert res["count"] == 0, res["items"]
    assert res["excluded_high_inflection_language"] >= 1
    assert "et" in res["method"]


def test_complete_non_overlap_is_a_method_failure_not_a_finding(db):
    """A d_lex of EXACTLY 1.0 against a real, non-empty body is treated as a method-
    failure signal, never a finding -- a genuine mismatch almost always shares SOME
    word (a name, a place) with the body; total non-overlap is the extraction bug's
    own fingerprint."""
    _src(db, 1, "a.test")
    # Zero shared vocabulary at all with the economics BODY (not even one word).
    _art(db, 1, "Wizards summon a dragon over the castle in a spectacular parade", BODY)
    res = find_headline_body_mismatch(db)
    assert res["count"] == 0, res["items"]
    assert res["excluded_method_failure"] >= 1


def test_producer_emits_a_valid_debunk_card(db):
    # The Home-Lead producer wraps the finding in a schema-valid, no-score Card.
    from src.briefing.card import assert_no_score_fields
    from src.briefing.producers import headline_body_mismatch

    _src(db, 1, "a.test")
    _art(db, 1, "Pentagon aliens hijack interest rates in shocking new footage tonight", BODY)
    cards = headline_body_mismatch(db)
    assert len(cards) == 1
    card = cards[0]
    assert card.type == "headline_body_mismatch" and card.bucket == "debunk"
    assert card.article_ids == [1]  # opens the analysis window over the exact article
    assert "score" not in card.signal and "value" in card.signal
    assert_no_score_fields(type(card))  # the Card class carries no banned score field
    d = card.to_dict()  # serialisable, caveat + method present
    assert d["caveat"] and d["method"]
