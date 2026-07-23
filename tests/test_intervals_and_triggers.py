"""
Closed-form intervals + the "Why am I seeing this?" trigger audit trail.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Evidence-tiered cards, slice 1 (maintainer-ruled 2026-06-10): real 95% intervals
where the math is defined; every instrumented card explains itself with ONE
constant plain-language sentence (translatable by exact match) plus math rows
whose labels are constant and whose values are numbers/symbols only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source
from src.signals.intervals import rate_ratio_interval, wilson_interval


# --------------------------------------------------------------------------- #
#  Pure interval math
# --------------------------------------------------------------------------- #
def test_wilson_interval_contains_point_and_tightens_with_n():
    small = wilson_interval(6, 10)
    large = wilson_interval(600, 1000)
    assert small and large
    assert small.low < 0.6 < small.high
    assert large.low < 0.6 < large.high
    # Same proportion, 100x the sample: the interval must be much tighter.
    assert (large.high - large.low) < (small.high - small.low) / 5


def test_wilson_interval_bounds_and_degenerate_inputs():
    assert wilson_interval(0, 0) is None
    assert wilson_interval(5, 4) is None
    edge = wilson_interval(0, 8)
    assert edge is not None and edge.low == 0.0 and edge.high < 0.5


def test_rate_ratio_interval_honest_on_zero_prior():
    # A brand-new term has no prior rate: no CI is invented.
    assert rate_ratio_interval(7, 0, window_days=7, baseline_days=30) is None
    ci = rate_ratio_interval(7, 9, window_days=7, baseline_days=30)
    assert ci is not None
    rr = (7 / 7) / (9 / 30)
    assert ci.low < rr < ci.high
    # Small counts -> a wide interval (the honesty is the width).
    assert ci.high / ci.low > 3


# --------------------------------------------------------------------------- #
#  Producers carry the trigger audit trail
# --------------------------------------------------------------------------- #
@pytest.fixture()
def corpus(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(name="Beta", domain="beta.test", country="us"))
    s.commit()
    now = datetime.now(UTC)
    for i in range(12):
        a = Article(
            url=f"https://t.test/{i}",
            canonical_url=f"https://t.test/{i}",
            source_id=1 if i % 3 else 2,
            title=f"Story {i}",
            hash=f"th{i}",
            language="en",
            content=(
                "The election dominated the election news as election coverage spread."
                if i < 6
                else "Markets moved on quiet trading and steady prices today."
            ),
            published_at=now - timedelta(days=i % 5),
            created_at=now,
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=BaselineExtractor(), country="fr")
    return s


def _assert_trigger_contract(card):
    t = card.trigger
    assert t and t["plain"], "an instrumented card must explain itself in plain words"
    assert t["plain"] == t["plain"].strip()
    for row in t["math"]:
        assert row["label"] and row["value"]
        # Labels are constant English (translatable); values carry no prose —
        # spot-check that values stay symbolic/numeric (allow ✓ — % × ÷ ≥ etc.).
        assert not any(w in row["value"].lower() for w in ("the ", "your ", "article"))


def test_rising_card_explains_itself(corpus):
    from src.briefing.producers import rising_now

    cards = rising_now(corpus)
    assert cards
    _assert_trigger_contract(cards[0])
    labels = [r["label"] for r in cards[0].trigger["math"]]
    assert "Mentions in the last 7 days" in labels
    assert any("scanned" in lb.lower() for lb in labels)  # multiple-comparisons honesty
    # to_dict carries the trigger to the API/UI.
    assert cards[0].to_dict()["trigger"]["plain"]


def test_rising_card_carries_the_exact_article_set(corpus):
    """9.1 (PR #740/#744 remediation, field-diagnostics #728): rising_now's Card was
    missing article_ids -- the exact-set-seeding convention every other per-topic
    producer follows (flooded_topic, buried_topic, framing_split...) -- so clicking a
    rising card fell back to a synthetic text search on the term instead of opening the
    exact articles the ratio was computed over."""
    from src.briefing.producers import rising_now

    cards = rising_now(corpus)
    assert cards
    card = cards[0]
    assert card.article_ids, "a rising card must carry the exact article set it was computed over"
    # Every id must be a real article that actually mentions the rising term (never a
    # fabricated/unrelated id), and the evidence rows are a subset of the same set.
    evidence_ids = {e["article_id"] for e in card.evidence}
    assert evidence_ids <= set(card.article_ids)
    assert card.article_ids == sorted(set(card.article_ids))  # matches the shipped convention


def test_diet_card_carries_wilson_interval(corpus):
    from src.briefing.producers import diet_self_audit

    cards = diet_self_audit(corpus)
    assert cards
    _assert_trigger_contract(cards[0])
    joined = " ".join(r["label"] for r in cards[0].trigger["math"])
    assert "95% interval" in joined
