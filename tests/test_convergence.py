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

from datetime import UTC, date, datetime, timedelta

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
    # Exact-corpus seeding (maintainer 2026-06-16): the card carries the FULL
    # converging article set (not just the 4-item evidence sample) so the UI opens
    # the analysis window over PRECISELY these articles, never a re-run search.
    assert sorted(card.article_ids) == [1, 2, 3]
    assert card.to_dict()["article_ids"] == card.article_ids


def test_empty_corpus_degrades_loudly_not_a_fake_card(session):
    out = find_convergences(session)
    assert out["clusters"] == []
    assert out["clusters_total"] == 0
    assert "never causation" in out["caveat"]


# --------------------------------------------------------------------------- #
#  Convergence-amendment (2026-07-18): C1 exact counts, C2 place canonicalization,
#  C3 span-collapse, C4 baseline-relative ordering, city-over-country dedup.
# --------------------------------------------------------------------------- #
def test_c1_shared_origin_count_is_exact_never_capped(session):
    """The ruling: 'real, reliable data — never capped figures'. A cluster with 60
    distinct shared-origin URLs reports EXACTLY 60, with only the EXAMPLES bounded."""
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    for aid, src in ((1, 1), (2, 2), (3, 1), (4, 2)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid)
        _add_date(s, aid=aid, on=date(2024, 5, 12))
    # 60 DISTINCT outbound URLs, each cited by BOTH article 1 and article 2 (a real
    # shared origin every time -- never the display-cap masquerading as the count).
    for i in range(60):
        url = f"https://wire.example/report-{i}"
        s.add(ArticleLink(article_id=1, url=url, normalized_url=url))
        s.add(ArticleLink(article_id=2, url=url, normalized_url=url))
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    cluster = out["clusters"][0]
    assert cluster["shared_origin_links"] == 60, cluster["shared_origin_links"]
    assert len(cluster["shared_origin_examples"]) <= 3


def test_c2_country_level_surface_strings_collapse_to_one_cluster(session):
    """Row 8: "United States"/"America"/"Usa" name the SAME country -- they must
    merge into ONE cluster, not three, and display the canonical name."""
    s = session
    for sid, cc in ((1, "fr"), (2, "de"), (3, "jp")):
        s.add(Source(id=sid, name=f"Src{sid}", domain=f"s{sid}.test", country=cc))
    s.commit()
    for aid, src, name in ((1, 1, "United States"), (2, 2, "America"), (3, 3, "Usa")):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid, name=name, country="us", kind="country", lat=None, lon=None)
        _add_date(s, aid=aid, on=date(2024, 5, 12))
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    us_clusters = [c for c in out["clusters"] if c["place_country"] == "us"]
    assert len(us_clusters) == 1, out["clusters"]
    assert us_clusters[0]["place"] == "United States"
    assert us_clusters[0]["n_articles"] == 3


def test_c3_sliding_window_fragmentation_collapses_to_one_span(session):
    """Row 3: Iran x3 across contiguous windows must collapse to ONE span entry
    with the full extent + a per-window step breakdown, not three siblings."""
    s = session
    for sid in (1, 2, 3):
        s.add(Source(id=sid, name=f"Src{sid}", domain=f"s{sid}.test", country="us"))
    s.commit()
    # Three CONTIGUOUS 7-day-window steps (each touching the next, like the field
    # export's 06-25→07-02 · 07-03→10 · 07-11→18), 3 distinct sources total.
    aid = 1
    for step_start, srcs in (
        (date(2024, 6, 25), (1, 2, 3)),
        (date(2024, 7, 3), (1, 2, 3)),
        (date(2024, 7, 11), (1, 2, 3)),
    ):
        for i, src in enumerate(srcs):
            _add_article(s, aid=aid, source_id=src)
            _add_place(s, aid=aid, name="Iran", country="ir", kind="country", lat=None, lon=None)
            _add_date(s, aid=aid, on=step_start + timedelta(days=i))
            aid += 1
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    iran_clusters = [c for c in out["clusters"] if c["place_country"] == "ir"]
    assert len(iran_clusters) == 1, out["clusters"]  # ONE span, not three
    span = iran_clusters[0]
    assert span["window_start"] == "2024-06-25"
    assert span["window_end"] == "2024-07-13"
    assert len(span["steps"]) == 3
    assert span["n_articles"] == 9
    assert "peak_step_index" in span


def test_c4_baseline_relative_ordering_hub_never_outranks_a_real_spike(session):
    """C4 negative-space: a hub place at its NORMAL share must not outrank a small
    place at several times its own baseline -- and full recall is preserved (both
    remain in the list)."""
    s = session
    for sid in range(1, 5):
        s.add(Source(id=sid, name=f"Src{sid}", domain=f"s{sid}.test", country="us"))
    s.commit()
    aid = 1
    # HUB: mentioned constantly across many separate, far-apart windows (each span
    # is a small fraction of its own huge all-time total -- the base rate).
    hub_windows = [date(2024, m, 5) for m in range(1, 10)]  # 9 separate months
    for w in hub_windows:
        for src in (1, 2, 3):
            _add_article(s, aid=aid, source_id=src)
            _add_place(s, aid=aid, name="Germany", country="de", kind="country", lat=None, lon=None)
            _add_date(s, aid=aid, on=w)
            aid += 1
    # SMALL PLACE: normally never mentioned, but ALL its (small) history concentrates
    # into one recent span -- a genuine, surprising spike.
    for src in (1, 2, 3):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid, name="Tuvalu", country="tv", kind="country", lat=None, lon=None)
        _add_date(s, aid=aid, on=date(2024, 10, 1))
        aid += 1
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    places = [c["place"] for c in out["clusters"]]
    assert "Germany" in places and "Tuvalu" in places  # full recall — nothing dropped
    hub = next(c for c in out["clusters"] if c["place"] == "Germany")
    small = next(c for c in out["clusters"] if c["place"] == "Tuvalu")
    assert small["baseline_share"] > hub["baseline_share"]
    # Tuvalu's spike (100% of its own history) outranks Germany's routine slice.
    assert places.index("Tuvalu") < places.index("Germany")


def test_city_over_country_dedup_drops_a_fully_explained_country_span(session):
    """A country-level span whose evidence is entirely covered by an overlapping
    city-level span (same country) is dropped -- Paris explains all of France."""
    s = session
    for sid in (1, 2, 3):
        s.add(Source(id=sid, name=f"Src{sid}", domain=f"s{sid}.test", country="fr"))
    s.commit()
    for aid, src in ((1, 1), (2, 2), (3, 3)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid, name="Paris", country="fr", kind="city", lat=48.85, lon=2.35)
        _add_place(s, aid=aid, name="France", country="fr", kind="country", lat=None, lon=None)
        _add_date(s, aid=aid, on=date(2024, 5, 12))
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    kinds = {c["place"]: c["place_kind"] for c in out["clusters"]}
    assert "Paris" in kinds
    assert "France" not in kinds  # fully explained by Paris -- no added precision


def test_country_span_kept_when_it_adds_breadth_beyond_any_city(session):
    """France is KEPT when its evidence goes beyond what Paris alone covers -- a
    country span genuinely adding precision beyond any single city."""
    s = session
    for sid in (1, 2, 3, 4, 5):
        s.add(Source(id=sid, name=f"Src{sid}", domain=f"s{sid}.test", country="fr"))
    s.commit()
    for aid, src in ((1, 1), (2, 2), (3, 3)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid, name="Paris", country="fr", kind="city", lat=48.85, lon=2.35)
        _add_place(s, aid=aid, name="France", country="fr", kind="country", lat=None, lon=None)
        _add_date(s, aid=aid, on=date(2024, 5, 12))
    # Two MORE articles mention France but NOT Paris -- real breadth beyond the city.
    for aid, src in ((4, 4), (5, 5)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid, name="France", country="fr", kind="country", lat=None, lon=None)
        _add_date(s, aid=aid, on=date(2024, 5, 12))
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2)
    kinds = {c["place"]: c["place_kind"] for c in out["clusters"]}
    assert "Paris" in kinds and "France" in kinds
    france = next(c for c in out["clusters"] if c["place"] == "France")
    assert france["n_articles"] == 5


def test_c5_source_country_spread_and_future_dated_flag(session):
    s = session
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="fr"))
    s.add(Source(id=2, name="Beta", domain="beta.test", country="us"))
    s.commit()
    future = date.today() + timedelta(days=5)
    for aid, src in ((1, 1), (2, 2), (3, 1)):
        _add_article(s, aid=aid, source_id=src)
        _add_place(s, aid=aid)
        _add_date(s, aid=aid, on=future)
    s.commit()

    out = find_convergences(s, window_days=7, min_articles=3, min_sources=2, lookback_days=None)
    cluster = out["clusters"][0]
    assert cluster["source_countries"] == {"fr": 2, "us": 1}
    assert cluster["includes_future_mentions"] is True


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
