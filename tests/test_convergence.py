"""
Tests for space-time co-occurrence (convergence slice 1, read-only).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers the binding ethics:
  * a place mentioned by TWO distinct sources in the same window => ONE cluster
    with distinct_sources=2 (the honest independence measure);
  * a single source mentioning a place many times => NO cluster (the
    anti-false-triangulation gate: one source wearing many hats is not
    convergence);
  * shared outbound links across members are FLAGGED (common-origin structure);
  * the producer emits a schema-valid Card with a _trigger and NO score field,
    carrying the verbatim "never causation" caveat.

The When×Where×Who substrate (article_mentioned_places + article_mentioned_dates)
is seeded directly here — its ingest-time PERSISTENCE is already covered by the
T12 tests; this file tests the convergence READ logic over those rows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.convergence import find_convergences
from src.database.models import (
    Article,
    ArticleLink,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Source,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def client():
    # The shared app DB (TestClient) -- the endpoint test seeds via SessionLocal and
    # asserts membership by a unique place marker, so other rows never interfere.
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _add_article(s, *, aid: int, source_id: int) -> Article:
    a = Article(
        id=aid,
        url=f"https://x.test/{aid}",
        canonical_url=f"https://x.test/{aid}",
        source_id=source_id,
        title=f"Story {aid}",
        content="Body text about an event.",
        hash=f"h{aid}",
        language="en",
        published_at=datetime(2024, 5, 10, tzinfo=UTC),
        created_at=datetime(2024, 5, 10, tzinfo=UTC),
    )
    s.add(a)
    return a


def _add_place(s, *, aid: int, name="Gaza", country="ps", kind="city",
               lat=31.5, lon=34.45):
    s.add(
        ArticleMentionedPlace(
            article_id=aid, name=name, country=country, kind=kind,
            mentions=1, lat=lat, lon=lon, extractor="lexical-v1",
        )
    )


def _add_date(s, *, aid: int, on: date, status="candidate"):
    s.add(
        ArticleMentionedDate(
            article_id=aid, mentioned_on=on, precision="day",
            extractor="dateextract", status=status,
        )
    )


def test_two_distinct_sources_same_place_window_make_one_cluster(session):
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()

    # Three articles, two distinct sources, all on Gaza within a 7-day window.
    for aid, src in ((1, 1), (2, 2), (3, 1)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid)
        _add_date(s, aid=aid, on=date(2024, 5, 10 + aid))  # 11, 12, 13 May
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    assert out["clusters_total"] == 1, out
    cluster = out["clusters"][0]
    assert cluster["place"] == "Gaza"
    assert cluster["distinct_sources"] == 2  # the honest independence measure
    assert cluster["n_articles"] == 3
    assert sorted(cluster["source_names"]) == ["Alpha", "Beta"]
    assert cluster["window_start"] == "2024-05-11"
    assert cluster["window_end"] == "2024-05-13"
    # The verbatim non-negotiables travel on every cluster.
    assert "never causation" in cluster["caveat"]
    assert "independent sources" in cluster["caveat"]
    assert "deduced" in cluster["method"].lower()


def test_single_chatty_source_makes_no_cluster_independence_gate(session):
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.commit()

    # ONE source mentions Gaza in five articles in the window: many hats, one
    # voice. The independence gate (>= 2 distinct sources) must reject it.
    for aid in range(1, 6):
        _add_article(s, aid=aid, source_id=1)
        _add_place(s, aid=aid)
        _add_date(s, aid=aid, on=date(2024, 5, 10))
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    assert out["clusters"] == []
    assert out["clusters_total"] == 0
    # The place WAS scanned — it just failed the independence gate (honest total).
    assert out["scanned_places"] == 1


def test_different_window_does_not_converge(session):
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    # Same place, two sources, but the dates are months apart => no single window
    # gathers >= 3 articles.
    for aid, src, on in ((1, 1, date(2024, 1, 1)), (2, 2, date(2024, 6, 1)),
                         (3, 1, date(2024, 12, 1))):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid)
        _add_date(s, aid=aid, on=on)
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    assert out["clusters"] == []


def test_shared_outbound_links_are_flagged(session):
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    for aid, src in ((1, 1), (2, 2), (3, 1)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid)
        _add_date(s, aid=aid, on=date(2024, 5, 12))
    # Two of the three members cite the SAME outbound origin — false-triangulation.
    for aid in (1, 2):
        s.add(
            ArticleLink(
                article_id=aid,
                url="https://wire.example/report",
                normalized_url="https://wire.example/report",
            )
        )
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    cluster = out["clusters"][0]
    assert cluster["shared_origin_links"] == 1
    assert "https://wire.example/report" in cluster["shared_origin_examples"]


def test_rejected_date_tags_excluded(session):
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    # Three articles share the place, but article 3's only date is REJECTED, so
    # only two dated articles remain in the window => below the article gate.
    for aid, src in ((1, 1), (2, 2), (3, 1)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid)
    _add_date(s, aid=1, on=date(2024, 5, 11))
    _add_date(s, aid=2, on=date(2024, 5, 12))
    _add_date(s, aid=3, on=date(2024, 5, 13), status="rejected")
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    assert out["clusters"] == []


# --------------------------------------------------------------------------- #
#  The producer surfaces a schema-valid, score-free card with a trigger.
# --------------------------------------------------------------------------- #
def test_producer_emits_valid_card_with_trigger_and_no_score(session):
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    for aid, src in ((1, 1), (2, 2), (3, 2)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid, name="Lyon", country="fr")
        _add_date(s, aid=aid, on=date(2024, 5, 12))
    s.commit()

    from src.briefing.card import Card, assert_no_score_fields
    from src.briefing.producers import space_time_convergence

    cards = space_time_convergence(s)
    assert cards, "expected one convergence card"
    card = cards[0]
    assert isinstance(card, Card)
    assert card.type == "space_time_convergence"
    assert card.bucket == "investigate"
    # No composite score, ever (the §6 honesty guard).
    assert_no_score_fields(Card)
    assert "score" not in card.signal  # the metric is a real count, not a blend
    assert card.signal["metric"] == "distinct_sources"
    assert card.signal["value"] == 2
    # method + caveat always present; caveat carries the non-negotiable.
    assert card.method and card.caveat
    assert "never causation" in card.caveat
    # The evidence-tier trigger contract: a plain sentence + >=1 real math row.
    assert card.trigger is not None
    assert card.trigger["plain"].strip()
    rows = card.trigger["math"]
    assert rows and all(r.get("label") and "value" in r for r in rows)
    # The distinct-source row is present and real.
    assert any(r["value"] == "2" for r in rows)
    # Evidence links back to the corpus.
    assert any(ev.get("url") for ev in card.evidence)


def test_empty_corpus_degrades_loudly_not_a_fake_card(session):
    out = find_convergences(session)
    assert out["clusters"] == []
    assert out["clusters_total"] == 0
    assert "never causation" in out["caveat"]


def test_convergences_endpoint(client):
    """The read-only /api/insights/convergences view surfaces find_convergences over
    the seeded When×Where×Who substrate, with the honest gates + caveat preserved and
    NO score — and the distinct-sources independence gate is enforced through the API."""
    from src.database.models import SessionLocal

    s = SessionLocal()
    try:
        s.add(Source(id=901, name="ConvAlpha", domain="convalpha.test", country="fr"))
        s.add(Source(id=902, name="ConvBeta", domain="convbeta.test", country="us"))
        s.flush()
        # 3 articles, 2 distinct sources, all on "Convtown" within a 7-day window.
        for aid, src in ((9001, 901), (9002, 902), (9003, 901)):
            s.add(Article(
                id=aid, url=f"https://conv.test/{aid}", canonical_url=f"https://conv.test/{aid}",
                source_id=src, title=f"Conv {aid}", content="event body text",
                hash=f"convh{aid}", language="en",
                published_at=datetime(2024, 5, 10, tzinfo=UTC),
                created_at=datetime(2024, 5, 10, tzinfo=UTC),
            ))
            s.add(ArticleMentionedPlace(
                article_id=aid, name="Convtown", country="ps", kind="city",
                mentions=1, lat=31.5, lon=34.45, extractor="lexical-v1",
            ))
            s.add(ArticleMentionedDate(
                article_id=aid, mentioned_on=date(2024, 5, 10 + (aid - 9000)),
                precision="day", extractor="dateextract", status="candidate",
            ))
        s.commit()
    finally:
        s.close()

    out = client.get(
        "/api/insights/convergences",
        params={"window_days": 7, "min_articles": 3, "min_sources": 2},
    ).json()
    mine = [c for c in out["clusters"] if c["place"] == "Convtown"]
    assert mine, out
    c = mine[0]
    assert c["distinct_sources"] == 2 and c["n_articles"] == 3   # honest independence measure
    assert "never causation" in c["caveat"] and "score" not in c
    # The independence gate flows through the API: require 3 distinct sources and the
    # 2-source cluster is no longer surfaced (a chatty source can't manufacture one).
    out2 = client.get("/api/insights/convergences", params={"min_sources": 3}).json()
    assert not [c for c in out2["clusters"] if c["place"] == "Convtown"]
