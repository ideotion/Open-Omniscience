"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

If-this-then-SUGGEST corroboration (maintainer-asked 2026-06-12, slice 1:
weather): the deductive scan is local-only and explainable; the card only
OFFERS the fetch; the fetch is bounded, consent-gated upstream, cache-aware,
and degrades to honest transport verdicts (the T4 taxonomy) — never a crash.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def drought_cluster(client):
    """Three recent articles sharing the 'drought' keyword and a Nairobi place row."""
    from src.database.models import (
        Article,
        ArticleMentionedPlace,
        Keyword,
        KeywordMention,
        Source,
    )
    from src.database.session import session_scope

    today = date.today()
    with session_scope() as s:
        src = Source(name="CorrSeed", domain="corrseed.example", country="ke")
        s.add(src)
        s.flush()
        kw = Keyword(term="drought", normalized_term="drought", frequency=3)
        s.add(kw)
        s.flush()
        art_ids = []
        for i in range(3):
            a = Article(
                url=f"https://corrseed.example/{i}",
                canonical_url=f"https://corrseed.example/{i}",
                source_id=src.id,
                title=f"Drought report {i}",
                content="drought near nairobi",
                language="en",
                hash=f"corr{i}" + "a" * 59,
                published_at=datetime.now(UTC) - timedelta(days=5 + i),
            )
            s.add(a)
            s.flush()
            art_ids.append(a.id)
            s.add(KeywordMention(
                keyword_id=kw.id, article_id=a.id, count=2,
                observed_on=today - timedelta(days=5 + i), extractor="test",
            ))
            s.add(ArticleMentionedPlace(
                article_id=a.id, name="Nairobi", country="ke", kind="city",
                mentions=1, lat=-1.2864, lon=36.8172, extractor="lexical-v1",
            ))
        ids = {"src": src.id, "kw": kw.id, "arts": art_ids}
    yield ids
    with session_scope() as s:
        for aid in ids["arts"]:
            s.execute(text(f"DELETE FROM keyword_mentions WHERE article_id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM article_mentioned_places WHERE article_id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
        s.execute(text(f"DELETE FROM keywords WHERE id = {ids['kw']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {ids['src']}"))  # noqa: S608


def test_rules_file_is_honest_and_consistent():
    """Curated vocabulary: provenance stated, 12 languages on every rule, and
    every requested variable is one the endpoint actually allows."""
    from src.analytics.corroboration import load_rules
    from src.weather.openmeteo import ALLOWED_DAILY

    cfg = load_rules()
    assert cfg["as_of"], "the seed list must be date-stamped"
    assert "seed" in cfg["provenance"].lower()
    rules = cfg["rules"]
    assert {r["id"] for r in rules} >= {"drought", "flood", "heatwave",
                                        "wildfire", "storm", "cold_wave"}
    expected_langs = {"en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"}
    for r in rules:
        assert set(r["terms"].keys()) == expected_langs, r["id"]
        assert r["variables"], r["id"]
        assert set(r["variables"]) <= ALLOWED_DAILY, r["id"]


def test_engine_finds_cluster_discloses_totals(drought_cluster):
    from src.analytics.corroboration import find_weather_opportunities
    from src.database.session import session_scope

    with session_scope() as s:
        found = find_weather_opportunities(s, min_articles=3)
    assert found["clusters_total"] >= 1
    ops = [o for o in found["opportunities"] if o["place"] == "Nairobi"]
    assert ops, found
    op = ops[0]
    assert op["rule"] == "drought"
    assert op["n_articles"] == 3
    assert op["lat"] == pytest.approx(-1.2864) and op["lon"] == pytest.approx(36.8172)
    assert op["geocode"] == "city"
    assert op["terms_matched"] == ["drought"]
    assert sorted(op["article_ids"]) == sorted(drought_cluster["arts"])
    # window = article dates ± pad, never the future
    assert op["window_start"] <= op["window_end"] <= date.today().isoformat()


def test_engine_below_threshold_is_silent(drought_cluster):
    from src.analytics.corroboration import find_weather_opportunities
    from src.database.session import session_scope

    with session_scope() as s:
        found = find_weather_opportunities(s, min_articles=4)
    assert all(o["place"] != "Nairobi" for o in found["opportunities"])


def test_engine_geocode_fallback_states_country_precision(client):
    """A place row with no coordinates and an unknown name falls back to the
    country stand-in point with precision 'country' — or is skipped, never
    pinned to an invented coordinate."""
    from src.analytics.corroboration import find_weather_opportunities
    from src.database.models import (
        Article,
        ArticleMentionedPlace,
        Keyword,
        KeywordMention,
        Source,
    )
    from src.database.session import session_scope

    today = date.today()
    with session_scope() as s:
        src = Source(name="CorrSeed2", domain="corrseed2.example", country="fr")
        s.add(src)
        s.flush()
        kw = s.query(Keyword).filter_by(normalized_term="inondation").first()
        if kw is None:
            kw = Keyword(term="inondation", normalized_term="inondation", frequency=3)
            s.add(kw)
            s.flush()
        ids = []
        for i in range(3):
            a = Article(
                url=f"https://corrseed2.example/{i}",
                canonical_url=f"https://corrseed2.example/{i}",
                source_id=src.id, title=f"crue {i}", content="inondation",
                language="fr", hash=f"cor2{i}" + "b" * 59,
                published_at=datetime.now(UTC) - timedelta(days=3),
            )
            s.add(a)
            s.flush()
            ids.append(a.id)
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1,
                                 observed_on=today - timedelta(days=3), extractor="test"))
            s.add(ArticleMentionedPlace(article_id=a.id, name="Zzz-sur-Loire",
                                        country="fr", kind="city", mentions=1,
                                        lat=None, lon=None, extractor="lexical-v1"))
        kid, sid = kw.id, src.id
    try:
        with session_scope() as s:
            found = find_weather_opportunities(s, min_articles=3)
        ops = [o for o in found["opportunities"] if o["place"] == "Zzz-sur-Loire"]
        if ops:  # gazetteer resolved the country stand-in
            assert ops[0]["geocode"] == "country"
            assert ops[0]["rule"] == "flood"
            assert ops[0]["place_country"] == "fr"
        else:  # no resolvable coordinate -> honestly skipped and counted
            assert found["skipped_no_coords"] >= 1
    finally:
        with session_scope() as s:
            for aid in ids:
                s.execute(text(f"DELETE FROM keyword_mentions WHERE article_id = {aid}"))  # noqa: S608
                s.execute(text(f"DELETE FROM article_mentioned_places WHERE article_id = {aid}"))  # noqa: S608
                s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM keywords WHERE id = {kid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM sources WHERE id = {sid}"))  # noqa: S608


def test_country_level_surface_strings_collapse_to_one_cluster(client):
    """2026-07-18 field export (row 9): "Allemagne" (fr) and "Deutschland" (de) name the
    SAME country -- articles mentioning either must merge into ONE cluster, not two."""
    from src.analytics.corroboration import find_weather_opportunities
    from src.database.models import Article, ArticleMentionedPlace, Keyword, KeywordMention, Source
    from src.database.session import session_scope

    today = date.today()
    with session_scope() as s:
        src = Source(name="AllemagneSrc", domain="allemagnesrc.example", country="fr")
        s.add(src)
        s.flush()
        kw_fr = s.query(Keyword).filter_by(normalized_term="sécheresse").first()
        if kw_fr is None:
            kw_fr = Keyword(term="sécheresse", normalized_term="sécheresse", frequency=1)
            s.add(kw_fr)
        kw_de = s.query(Keyword).filter_by(normalized_term="dürre").first()
        if kw_de is None:
            kw_de = Keyword(term="dürre", normalized_term="dürre", frequency=1)
            s.add(kw_de)
        s.flush()
        ids = []
        # 2 French articles naming "Allemagne", 1 German article naming "Deutschland" --
        # all the SAME country, all the same "drought" rule.
        specs = [("Allemagne", kw_fr, "sécheresse en Allemagne"),
                 ("Allemagne", kw_fr, "sécheresse en Allemagne encore"),
                 ("Deutschland", kw_de, "dürre in Deutschland")]
        for i, (place_name, kw, content) in enumerate(specs):
            a = Article(
                url=f"https://allemagnesrc.example/{i}", canonical_url=f"https://allemagnesrc.example/{i}",
                source_id=src.id, title=f"story {i}", content=content, language="fr",
                hash=f"deu{i}" + "c" * 59, published_at=datetime.now(UTC) - timedelta(days=2 + i),
            )
            s.add(a)
            s.flush()
            ids.append(a.id)
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1,
                                 observed_on=today - timedelta(days=2 + i), extractor="test"))
            s.add(ArticleMentionedPlace(article_id=a.id, name=place_name, country="de",
                                        kind="country", mentions=1, extractor="lexical-v1"))
        kid_fr, kid_de, sid = kw_fr.id, kw_de.id, src.id
    try:
        with session_scope() as s:
            found = find_weather_opportunities(s, min_articles=3)
        de_ops = [o for o in found["opportunities"] if o["place_country"] == "de" and o["rule"] == "drought"]
        assert len(de_ops) == 1, found["opportunities"]  # NOT two clusters
        op = de_ops[0]
        assert op["place"] == "Germany"  # canonical display, never a raw surface string
        assert op["n_articles"] == 3
        assert set(op["article_ids"]) == set(ids)
    finally:
        with session_scope() as s:
            for aid in ids:
                s.execute(text(f"DELETE FROM keyword_mentions WHERE article_id = {aid}"))  # noqa: S608
                s.execute(text(f"DELETE FROM article_mentioned_places WHERE article_id = {aid}"))  # noqa: S608
                s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM keywords WHERE id IN ({kid_fr}, {kid_de})"))  # noqa: S608
            s.execute(text(f"DELETE FROM sources WHERE id = {sid}"))  # noqa: S608


def test_non_article_member_excluded_and_disclosed(client):
    """Row 10: a suspected homepage/section capture never counts as evidence -- it is
    excluded from a cluster's members and the exclusion is disclosed, not silent."""
    from src.analytics.corroboration import find_weather_opportunities
    from src.database.models import Article, ArticleMentionedPlace, Keyword, KeywordMention, Source
    from src.database.session import session_scope

    today = date.today()
    with session_scope() as s:
        src = Source(name="NonArtSrc", domain="nonartsrc.example", country="ke")
        s.add(src)
        s.flush()
        kw = s.query(Keyword).filter_by(normalized_term="drought").first()
        if kw is None:
            kw = Keyword(term="drought", normalized_term="drought", frequency=1)
            s.add(kw)
        s.flush()
        ids = []
        urls = [
            "https://nonartsrc.example/story-a",
            "https://nonartsrc.example/story-b",
            "https://nonartsrc.example/story-c",
            "https://nonartsrc.example/",  # a bare homepage capture -- suspected non-article
        ]
        for i, url in enumerate(urls):
            is_home = url.endswith("/")
            a = Article(
                url=url, canonical_url=url, source_id=src.id, title=f"story {i}",
                content="drought near nairobi" if not is_home else "home",
                language="en", hash=f"nona{i}" + "d" * 59,
                published_at=datetime.now(UTC) - timedelta(days=1 + i),
                word_count=5 if is_home else 400,
            )
            s.add(a)
            s.flush()
            ids.append(a.id)
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1,
                                 observed_on=today - timedelta(days=1 + i), extractor="test"))
            s.add(ArticleMentionedPlace(article_id=a.id, name="Nairobi", country="ke",
                                        kind="city", mentions=1, lat=-1.2864, lon=36.8172,
                                        extractor="lexical-v1"))
        kid, sid = kw.id, src.id
        real_ids = ids[:3]
        home_id = ids[3]
    try:
        with session_scope() as s:
            found = find_weather_opportunities(s, min_articles=3)
        ops = [o for o in found["opportunities"] if o["place"] == "Nairobi" and set(real_ids) <= set(o["article_ids"] + [home_id])]
        assert ops, found
        op = ops[0]
        assert home_id not in op["article_ids"]
        assert set(op["article_ids"]) == set(real_ids)
        assert op["n_articles"] == 3
        assert op["excluded_non_articles"] >= 1
        assert found["excluded_non_articles"] >= 1
    finally:
        with session_scope() as s:
            for aid in ids:
                s.execute(text(f"DELETE FROM keyword_mentions WHERE article_id = {aid}"))  # noqa: S608
                s.execute(text(f"DELETE FROM article_mentioned_places WHERE article_id = {aid}"))  # noqa: S608
                s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM keywords WHERE id = {kid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM sources WHERE id = {sid}"))  # noqa: S608


def test_producer_emits_schema_valid_offer_cards(drought_cluster):
    from src.briefing.card import Card
    from src.briefing.producers import _DEFAULT_PRODUCERS, weather_corroboration
    from src.database.session import session_scope

    assert dict(_DEFAULT_PRODUCERS).get("weather_corroboration") is weather_corroboration

    with session_scope() as s:
        cards = weather_corroboration(s)
    ours = [c for c in cards if c.signal.get("place") == "Nairobi"]
    assert ours, "the seeded cluster must surface a card"
    card = ours[0]
    assert isinstance(card, Card)
    assert card.type == "weather_corroboration"
    assert card.bucket == "investigate"
    assert card.n == 3
    assert "no network call" in card.method
    assert "never proof" in card.caveat
    assert card.signal["lat"] is not None and card.signal["window_start"]
    assert card.signal["clusters_total"] >= 1
    assert card.trigger and card.trigger["plain"]
    assert any(e.get("article_id") in drought_cluster["arts"] for e in card.evidence)


def test_endpoint_validation_bounds(client):
    base = {"lat": 0.0, "lon": 0.0, "start_date": "2024-01-01",
            "end_date": "2024-01-31", "variables": ["precipitation_sum"]}
    assert client.post("/api/weather/context", json={**base, "lat": 91}).status_code == 422
    assert client.post("/api/weather/context",
                       json={**base, "end_date": "2025-06-01"}).status_code == 422  # >366 d
    assert client.post("/api/weather/context",
                       json={**base, "end_date": "2023-12-01"}).status_code == 422  # end<start
    assert client.post("/api/weather/context",
                       json={**base, "start_date": "1890-01-01",
                             "end_date": "1890-02-01"}).status_code == 422  # pre-archive
    assert client.post("/api/weather/context",
                       json={**base, "variables": ["evil_param"]}).status_code == 422
    future = (date.today() + timedelta(days=10)).isoformat()
    assert client.post("/api/weather/context",
                       json={**base, "start_date": future,
                             "end_date": future}).status_code == 422


def test_endpoint_fetch_then_cache_then_kill_switch(client, monkeypatch, tmp_path):
    """First call fetches (stubbed transport) and states license + provenance;
    second call is served from the cache WITHOUT touching the fetch factory;
    with the kill switch engaged a forced refetch returns the 'offline' verdict."""
    import src.safety.fetcher as sf
    from src.ingest import FetchResult, activate_kill_switch, clear_kill_switch
    from src.weather.openmeteo import build_archive_url, cache_path

    body = {"lat": -1.2864, "lon": 36.8172, "start_date": "2024-02-01",
            "end_date": "2024-02-10", "variables": ["precipitation_sum"],
            "label": "Drought"}
    url = build_archive_url(-1.2864, 36.8172, date(2024, 2, 1), date(2024, 2, 10),
                            ["precipitation_sum"])
    cache_path(url).unlink(missing_ok=True)

    upstream = ('{"daily":{"time":["2024-02-01","2024-02-02"],'
                '"precipitation_sum":[0.0,1.2]},'
                '"daily_units":{"precipitation_sum":"mm"}}')

    class StubFetcher:
        def fetch(self, u, *, require_html=True):
            assert u == url and require_html is False
            return FetchResult(requested_url=u, final_url=u, status_code=200,
                               content=upstream, content_type="application/json",
                               fetched_at=datetime.now(UTC))

    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: StubFetcher())
    d = client.post("/api/weather/context", json=body).json()
    assert d["ok"] is True and d["cached"] is False
    assert d["daily"]["precipitation_sum"] == [0.0, 1.2]
    assert d["units"]["precipitation_sum"] == "mm"
    assert "CC BY 4.0" in d["provenance"]["license"]
    assert "reanalysis" in d["provenance"]["dataset"]
    assert cache_path(url).exists()

    def _explode(**kw):
        raise AssertionError("cache hit must not construct a fetcher")

    monkeypatch.setattr(sf, "make_fetcher", _explode)
    d2 = client.post("/api/weather/context", json=body).json()
    assert d2["ok"] is True and d2["cached"] is True
    assert d2["provenance"]["fetched_at"] == d["provenance"]["fetched_at"]

    monkeypatch.undo()
    activate_kill_switch()
    try:
        d3 = client.post("/api/weather/context", json={**body, "force": True}).json()
        assert d3["ok"] is False
        assert d3["verdict"] == "offline"
        assert d3["retryable"] is False
    finally:
        clear_kill_switch()
        cache_path(url).unlink(missing_ok=True)


def test_parse_failure_is_a_verdict_not_a_crash(client, monkeypatch):
    import src.safety.fetcher as sf
    from src.ingest import FetchResult
    from src.weather.openmeteo import build_archive_url, cache_path

    body = {"lat": 10.0, "lon": 20.0, "start_date": "2024-03-01",
            "end_date": "2024-03-05", "variables": ["temperature_2m_max"]}
    url = build_archive_url(10.0, 20.0, date(2024, 3, 1), date(2024, 3, 5),
                            ["temperature_2m_max"])
    cache_path(url).unlink(missing_ok=True)

    class HtmlFetcher:
        def fetch(self, u, *, require_html=True):
            return FetchResult(requested_url=u, final_url=u, status_code=200,
                               content="<html>not json</html>", content_type="text/html",
                               fetched_at=datetime.now(UTC))

    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: HtmlFetcher())
    d = client.post("/api/weather/context", json=body).json()
    assert d["ok"] is False and d["verdict"] == "parse-failed"
    assert not cache_path(url).exists(), "failures are never cached"
