"""Tests for weather signal-keywords (Cards batch E, Open-Meteo remainder).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

  * derived from an explicit THRESHOLD rule over the corroboration data (a cluster of
    >= min_articles articles matching a climate term + a place + a window);
  * each row carries a (date, place) ANCHOR by construction;
  * the anomaly is NOT fabricated — it is UNCHECKED against a stated baseline until the
    consented Open-Meteo fetch runs;
  * kept in a SEPARATE store — NEVER mixed with the text keyword tables (no schema).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Article,
    ArticleMentionedPlace,
    Base,
    Keyword,
    KeywordMention,
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
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def _seed_flood_cluster(s, n=3):
    """Seed n articles mentioning the curated 'flood' term together with one place."""
    s.add(Source(id=1, name="Alpha", domain="alpha.test", country="it"))
    kw = Keyword(term="flood", normalized_term="flood", language="en")
    s.add(kw)
    s.flush()
    on = date.today() - timedelta(days=5)
    for i in range(n):
        aid = 8000 + i
        s.add(Article(
            id=aid, url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
            source_id=1, title=f"Flood {aid}", content="the flood hit the city hard",
            hash=f"h{aid}", language="en",
            published_at=datetime.now(UTC), created_at=datetime.now(UTC),
        ))
        s.add(KeywordMention(keyword_id=kw.id, article_id=aid, source_id=1, observed_on=on, count=1))
        s.add(ArticleMentionedPlace(
            article_id=aid, name="Venice", country="it", kind="city",
            mentions=1, lat=45.44, lon=12.33, extractor="lexical-v1",
        ))
    s.commit()
    return kw.id


def test_derive_weather_signals_has_anchor_and_unchecked_anomaly(session):
    from src.analytics.weather_signals import derive_weather_signals

    _seed_flood_cluster(session, n=3)
    records = derive_weather_signals(session, min_articles=3)
    assert records, "expected one derived weather signal"
    rec = records[0]
    assert rec["kind"] == "signal"          # NOT a text keyword
    assert rec["term"] == "signal:flood"
    assert rec["signal"] == "flood"
    # The (date, place) anchor is present by construction.
    assert rec["anchor"]["place"] == "Venice"
    assert rec["anchor"]["date_start"] and rec["anchor"]["date_end"]
    assert rec["place_country"] == "it"
    # The anomaly is UNCHECKED against a stated baseline — never fabricated.
    assert rec["anomaly"]["checked"] is False
    assert "baseline" in rec["anomaly"]
    assert rec["variables"]  # the rule's Open-Meteo variables travel with the row
    assert rec["article_ids"]
    # The explicit threshold rule is stated.
    assert "3 articles" in rec["threshold_rule"]


def test_weather_signals_never_mixed_with_text_keywords(session, data_dir):
    from src.analytics.weather_signals import refresh_weather_signals

    _seed_flood_cluster(session, n=3)
    refresh_weather_signals(session, min_articles=3)
    # The signal rows live in their OWN store — NOT the keyword tables.
    assert session.query(Keyword).filter(Keyword.normalized_term.like("signal:%")).count() == 0
    assert session.query(Keyword).filter(Keyword.normalized_term == "flood").count() == 1


def test_weather_signals_save_load_roundtrip(session, data_dir):
    from src.analytics.weather_signals import load_signals, refresh_weather_signals

    _seed_flood_cluster(session, n=3)
    refresh_weather_signals(session, min_articles=3)
    loaded = load_signals()
    assert loaded["kind"] == "signal"
    assert loaded["signals"] and loaded["signals"][0]["term"] == "signal:flood"
    assert "never proof" in loaded["caveat"]


def test_below_threshold_derives_nothing(session):
    from src.analytics.weather_signals import derive_weather_signals

    _seed_flood_cluster(session, n=2)  # below the min_articles=3 threshold rule
    assert derive_weather_signals(session, min_articles=3) == []


def test_weather_signals_endpoints(session, data_dir):
    from src.database.models import SessionLocal

    # Seed into the shared app DB the endpoint reads — use HIGH UNIQUE ids + a unique
    # place so this never collides with any other test's rows (test isolation).
    s = SessionLocal()
    try:
        s.add(Source(id=88800, name="WeatherAlpha", domain="weatheralpha.test", country="it"))
        # Reuse an existing 'flood' keyword if another test created one; else make it.
        kw = s.query(Keyword).filter_by(normalized_term="flood").first()
        if kw is None:
            kw = Keyword(term="flood", normalized_term="flood", language="en")
            s.add(kw)
        s.flush()
        on = date.today() - timedelta(days=5)
        for i in range(3):
            aid = 88800 + i
            s.add(Article(
                id=aid, url=f"https://w.test/{aid}", canonical_url=f"https://w.test/{aid}",
                source_id=88800, title=f"Flood {aid}", content="the flood hit the city hard",
                hash=f"wh{aid}", language="en",
                published_at=datetime.now(UTC), created_at=datetime.now(UTC),
            ))
            s.add(KeywordMention(keyword_id=kw.id, article_id=aid, source_id=88800, observed_on=on, count=1))
            s.add(ArticleMentionedPlace(article_id=aid, name="Weathertown", country="it", kind="city",
                                        mentions=1, lat=45.44, lon=12.33, extractor="lexical-v1"))
        s.commit()
    finally:
        s.close()

    from src.api.main import app

    with TestClient(app) as c:
        # Read is empty until derived.
        assert c.get("/api/signals/weather-signals").json()["signals"] == []
        refreshed = c.post("/api/signals/weather-signals/refresh", params={"min_articles": 3}).json()
        assert refreshed["derived"] >= 1
        signals = c.get("/api/signals/weather-signals").json()["signals"]
        assert any(x["term"] == "signal:flood" for x in signals)
        assert all(x["anomaly"]["checked"] is False for x in signals)
