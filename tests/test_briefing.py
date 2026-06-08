"""
Tests for the briefing card framework, producers, cache and draft.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers the §6 honesty guard (no composite-score field), the "now" producers over a
small indexed corpus, the precompute/cache + dismiss flow, and the card→draft→Markdown
export. The DB is in-memory; cache/draft/dismiss state is isolated via OO_DATA_DIR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.briefing import draft as draft_store
from src.briefing import service
from src.briefing.card import Card, CardSchemaError, assert_no_score_fields
from src.database.models import Article, Base, Source


# --------------------------------------------------------------------------- #
#  §6 honesty guard — no composite trust/quality score, enforced in code
# --------------------------------------------------------------------------- #
def test_card_has_no_score_field():
    # The guard runs at import; assert it still holds for the live Card.
    assert_no_score_fields(Card)
    names = set(Card.__dataclass_fields__)
    for banned in ("score", "trust_score", "credibility", "rating", "verdict"):
        assert banned not in names


def test_assert_no_score_fields_rejects_a_score_field():
    @dataclass
    class Bad:
        trust_score: float = 0.0

    with pytest.raises(CardSchemaError):
        assert_no_score_fields(Bad)


def test_card_rejects_unknown_bucket():
    with pytest.raises(ValueError):
        Card(type="x", title="t", summary="s", bucket="not-a-bucket",
             method="m", caveat="c")


def test_card_stable_id_from_type_and_key():
    a = Card(type="rising", title="A", summary="s", bucket="rising", method="m", caveat="c", key="election")
    b = Card(type="rising", title="DIFFERENT", summary="s", bucket="rising", method="m", caveat="c", key="election")
    assert a.id == b.id  # identity is type+key, not the (volatile) title


# --------------------------------------------------------------------------- #
#  Producers over a real, small indexed corpus
# --------------------------------------------------------------------------- #
@pytest.fixture()
def corpus(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(name="Beta", domain="beta.test", country="us"))
    s.commit()

    now = datetime.now(UTC)
    # 12 articles in the last few days; "election" mentioned repeatedly & recently
    # so it trends. Split across two sources for the diet-concentration card.
    for i in range(12):
        src_id = 1 if i % 3 else 2  # Alpha-heavy -> a concentrated diet
        when = now - timedelta(days=i % 5)
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=src_id,
            title=f"Story {i}", hash=f"h{i}", language="en",
            content=("The election dominated the election news as election coverage spread."
                     if i < 6 else "Markets moved on quiet trading and steady prices today."),
            published_at=when, created_at=now,
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=BaselineExtractor(),
                      country="fr" if src_id == 1 else "us")
    return s


def test_rising_producer_surfaces_trending_term(corpus):
    from src.briefing.producers import rising_now

    cards = rising_now(corpus)
    assert cards, "expected at least one rising card from a clearly trending term"
    c = cards[0]
    assert c.bucket == "rising"
    assert c.signal["metric"] == "growth_ratio"
    assert c.method and c.caveat  # honesty: method + caveat always present
    # A rising card links back to evidence in the corpus.
    assert any(ev.get("url") for ev in c.evidence)


def test_diet_self_audit_uses_concentration(corpus):
    from src.briefing.producers import diet_self_audit

    cards = diet_self_audit(corpus)
    assert cards, "expected a diet card with >=10 articles across 2 sources"
    c = cards[0]
    assert c.bucket == "context"
    assert 0.0 <= c.signal["value"] <= 1.0   # a top-share fraction, not a score
    assert c.signal["gini"] is not None
    assert "owner" in c.caveat.lower()       # honest: source != owner


# --------------------------------------------------------------------------- #
#  Service: precompute → cache → serve; dismiss is reversible
# --------------------------------------------------------------------------- #
def test_refresh_then_cached_get(corpus):
    fresh = service.refresh_briefing(corpus)
    assert fresh["cards"], "a real corpus should yield real cards"
    view = service.get_briefing(corpus)  # served from cache, grouped by bucket
    assert view["count"] == len(fresh["cards"])
    assert view["buckets"] and all("label" in b for b in view["buckets"])


def test_dismiss_hides_card_and_is_reversible(corpus):
    view = service.get_briefing(corpus, force=True)
    card_id = view["cards"][0]["id"]
    service.dismiss(card_id)
    after = service.get_briefing(corpus)
    assert all(c["id"] != card_id for c in after["cards"])
    assert after["dismissed_count"] == 1
    service.restore(card_id)
    restored = service.get_briefing(corpus)
    assert any(c["id"] == card_id for c in restored["cards"])


# --------------------------------------------------------------------------- #
#  Draft accumulator → evidence-carrying Markdown
# --------------------------------------------------------------------------- #
def test_draft_add_and_export_markdown(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    card = Card(
        type="rising", title="“election” is rising", summary="Mentions climbing.",
        bucket="rising", method="ratio", caveat="not a significance test",
        signal={"metric": "growth_ratio", "value": 4.2},
        evidence=[{"title": "Story 1", "url": "https://x.test/1", "source": "Alpha"}],
        n=6, key="election",
    ).to_dict()

    draft_store.add_card(card, note="Lead item this week.")
    draft_store.add_card(card)  # idempotent by id
    loaded = draft_store.load_draft()
    assert len(loaded["items"]) == 1

    md = draft_store.export_markdown()
    assert "# Open Omniscience briefing" in md
    assert "“election” is rising" in md
    assert "https://x.test/1" in md        # evidence link travels with the claim
    assert "Method:" in md and "Caveat:" in md
    assert "Lead item this week." in md

    draft_store.remove_card(card["id"])
    assert draft_store.load_draft()["items"] == []
