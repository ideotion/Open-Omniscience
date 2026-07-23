"""
Tests for analytics queries + the Insights API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Builds a small indexed corpus, then pins trend buckets, top/associations (PMI
sign), context snippets, map aggregation, and the API status/reindex flow.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _mk(db, h, text, when, country="fr"):
    a = Article(
        url=f"https://x.test/{h}",
        canonical_url=f"https://x.test/{h}",
        source_id=1,
        title="T",
        content=text,
        hash=h,
        country=country,
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    index_article(db, a, extractor=BaselineExtractor(), country=country, city="Paris")
    return a


def test_trend_and_top(db):
    _mk(
        db,
        "a1",
        "Inflation rose. Inflation worries grew as inflation spread across markets here.",
        "2024-01-03",
    )
    _mk(
        db,
        "a2",
        "Inflation again dominated headlines while inflation pressures intensified sharply.",
        "2024-01-10",
    )
    tr = q.trend(db, "inflation", bucket="week")
    assert tr["resolved"]["normalized"] == "inflation"
    assert tr["total"] >= 4 and len(tr["points"]) >= 1
    top = q.top_terms(db, limit=10)
    assert any(t["normalized"] == "inflation" for t in top["terms"])


def test_associations_pmi_positive_for_cooccurring(db):
    # "sanctions" and "nickel" always co-occur -> positive PMI.
    for i, when in enumerate(["2024-02-01", "2024-02-02", "2024-02-03"]):
        _mk(
            db,
            f"c{i}",
            "New sanctions hit supply. Sanctions affected nickel and nickel exports broadly.",
            when,
        )
    _mk(
        db,
        "d0",
        "Unrelated weather report about rainfall and rainfall patterns over the coast today.",
        "2024-02-04",
    )
    assoc = q.associations(db, "sanctions", min_cooccur=2)
    pairs = {p["normalized"]: p for p in assoc["pairs"]}
    assert "nickel" in pairs and pairs["nickel"]["pmi"] > 0
    assert assoc["method"].startswith("pointwise mutual information")


def test_context_snippet_contains_term(db):
    _mk(
        db,
        "x1",
        "The committee discussed wildfire response and wildfire funding for the affected region.",
        "2024-03-01",
    )
    ctx = q.context(db, "wildfire", limit=5)
    assert ctx["count"] >= 1
    assert "wildfire" in ctx["mentions"][0]["snippet"].lower()
    assert ctx["mentions"][0]["country"] == "fr" and ctx["mentions"][0]["city"] == "Paris"


def test_map_data_groups_by_area(db):
    _mk(
        db,
        "m1",
        "Election campaigns and election rallies filled the capital this election season now.",
        "2024-03-05",
        country="fr",
    )
    _mk(
        db,
        "m2",
        "Drought worsened. Drought and drought relief efforts dominated the regional agenda.",
        "2024-03-06",
        country="ke",
    )
    data = q.map_data(db, days=3650)
    codes = {c["code"] for c in data["countries"]}
    assert {"fr", "ke"} <= codes
    assert any(c["name"] == "Paris" for c in data["cities"])


def test_insights_api_status_and_reindex(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ins.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="x.test", country="fr"))
        s.commit()
        s.add(
            Article(
                url="https://x.test/p",
                canonical_url="https://x.test/p",
                source_id=1,
                title="T",
                content="Diplomacy and diplomacy talks shaped the summit agenda this week here.",
                hash="hh",
                country="fr",
                language="en",
                published_at=datetime(2024, 4, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
        s.commit()

    def _override():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            st = client.get("/api/insights/status").json()
            assert st["total_articles"] == 1 and st["remaining"] == 1
            re = client.post("/api/insights/reindex?limit=50").json()
            assert re["indexed"] == 1 and re["remaining"] == 0
            top = client.get("/api/insights/top?limit=5").json()
            assert any(t["normalized"] == "diplomacy" for t in top["terms"])
    finally:
        app.dependency_overrides.clear()


def test_corpus_keywords_scopes_to_article_set(db):
    """corpus_keywords aggregates over a GIVEN article set, not the whole corpus."""
    a1 = _mk(db, "ck1", "tariff tariff steel industry policy", "2026-01-01")
    a2 = _mk(db, "ck2", "tariff steel industry", "2026-01-02")
    _mk(db, "ck3", "weather sunshine beaches holiday", "2026-01-03")  # excluded set
    res = q.corpus_keywords(db, article_ids=[a1.id, a2.id], limit=20)
    assert res["n_articles"] == 2
    assert res["count"] > 0
    norms = {t["normalized"] for t in res["terms"]}
    # terms come only from the two selected articles, never the third
    assert "weather" not in norms and "sunshine" not in norms and "beaches" not in norms
    # the shared subject surfaces
    assert any(("tariff" in n) or ("steel" in n) or ("industry" in n) for n in norms), norms
    # empty set is handled
    assert q.corpus_keywords(db, article_ids=[], limit=10)["count"] == 0


def test_corpus_who_and_where_scope_to_article_set(db):
    a1 = _mk(db, "ww1", "President visited Paris with officials.", "2026-02-01")
    a2 = _mk(db, "ww2", "Officials met in Paris.", "2026-02-02")
    _mk(db, "ww3", "Quiet day in Tokyo.", "2026-02-03")
    who = q.corpus_who(db, article_ids=[a1.id, a2.id], limit=20)
    where = q.corpus_where(db, article_ids=[a1.id, a2.id], limit=20)
    assert isinstance(who["entities"], list) and isinstance(where["places"], list)
    # Tokyo (only in the excluded a3) must not appear in the {a1,a2} where-set
    assert all(pl["name"].lower() != "tokyo" for pl in where["places"])
    assert q.corpus_who(db, article_ids=[], limit=5)["count"] == 0
    assert q.corpus_where(db, article_ids=[], limit=5)["count"] == 0


def test_corpus_sentiment_distribution_and_english_disclosure(db):
    a1 = _mk(db, "se1", "Great news.", "2026-03-01")
    a2 = _mk(db, "se2", "Terrible disaster.", "2026-03-02")
    a3 = _mk(db, "se3", "Une nouvelle.", "2026-03-03")
    a1.sentiment_score, a1.sentiment_label = 0.8, "positive"
    a2.sentiment_score, a2.sentiment_label = -0.7, "negative"
    a3.sentiment_score, a3.sentiment_label, a3.language = 0.1, "neutral", "fr"
    db.commit()
    r = q.corpus_sentiment(db, article_ids=[a1.id, a2.id, a3.id])
    assert r["n_articles"] == 3 and r["n_scored"] == 3
    assert r["labels"] == {"positive": 1, "negative": 1, "neutral": 1}
    assert r["english_scored"] == 2  # a3 is fr -> outside the reliable (English) share
    assert r["mean_score"] == round((0.8 - 0.7 + 0.1) / 3, 3)
    assert "VADER" in r["caveat"]
    # an article with no stored score is excluded from n_scored. (Sentiment is now
    # computed AT INGEST for English text via index_article, so every English article
    # gets a stored score by default; we explicitly clear a4's score to represent an
    # article the scorer left unscored — e.g. a non-English article, or a CORE install
    # without the optional VADER extra — and assert it is excluded.)
    a4 = _mk(db, "se4", "No score.", "2026-03-04")
    a4.sentiment_score, a4.sentiment_label = None, None
    db.commit()
    assert q.corpus_sentiment(db, article_ids=[a1.id, a4.id])["n_scored"] == 1
    assert q.corpus_sentiment(db, article_ids=[])["n_scored"] == 0


def test_corpus_sources_groups_matched_articles_by_source(db):
    a1 = _mk(db, "sc1", "Story one.", "2026-04-01")
    a2 = _mk(db, "sc2", "Story two.", "2026-04-05")
    a1.sentiment_score, a2.sentiment_score = 0.5, -0.1
    db.add(Source(name="S2", domain="y.test", country="us"))
    db.commit()
    a3 = Article(
        url="https://y.test/1", canonical_url="https://y.test/1", source_id=2,
        title="T", content="Story three.", hash="sc3", language="en",
        published_at=datetime.fromisoformat("2026-04-03").replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a3)
    db.commit()
    r = q.corpus_sources(db, article_ids=[a1.id, a2.id, a3.id])
    assert r["count"] == 2
    by = {s["name"]: s for s in r["sources"]}
    assert by["S"]["articles"] == 2 and by["S2"]["articles"] == 1
    assert r["sources"][0]["name"] == "S"  # ordered by volume desc (no ranking by quality)
    assert by["S"]["mean_tone"] == round((0.5 - 0.1) / 2, 3)
    assert by["S"]["first"] and by["S"]["last"]  # timing span present
    assert "credibility" in r["caveat"]
    assert q.corpus_sources(db, article_ids=[])["count"] == 0


def test_corpus_endpoints_accept_explicit_article_ids(tmp_path):
    """Exact-corpus card seeding (maintainer-ruled 2026-06-16): the analysis-window
    endpoints take an EXPLICIT article-id set (a card / agenda event's precise
    selection) instead of re-running a search, so the corpus is exactly the articles
    the card identified. Parsing is robust (dedupe, whitespace, non-numeric dropped)
    and totals stay honest."""
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ex.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="x.test", country="fr"))
        s.commit()
        for i in range(1, 4):  # articles 1, 2, 3
            s.add(Article(
                url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}",
                source_id=1, title=f"T{i}", content="Body text about an event here.",
                hash=f"h{i}", country="fr", language="en",
                published_at=datetime(2024, 4, i, tzinfo=UTC), created_at=datetime.now(UTC),
            ))
        s.commit()

    def _override():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            # Explicit set of exactly two articles -> the corpus IS those two.
            r = client.get("/api/insights/corpus-www", params={"article_ids": "1,2"}).json()
            assert r["n_articles"] == 2 and r["total_matched"] == 2 and r["capped"] is False
            # Robust parse: whitespace, duplicates and non-numeric tokens are handled;
            # {2, 1} dedups to 2 valid ids (order preserved, bogus dropped).
            r2 = client.get("/api/insights/corpus-www", params={"article_ids": " 2, 2 ,1, foo, -5 "}).json()
            assert r2["n_articles"] == 2
            # The same param flows through the other analysis subtabs (counts only).
            ks = client.get("/api/insights/corpus-keywords", params={"article_ids": "1,2,3"}).json()
            assert ks["total_matched"] == 3 and "score" not in ks
            src = client.get("/api/insights/corpus-sources", params={"article_ids": "1"}).json()
            assert src["total_matched"] == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_graph_endpoint_honours_the_analysis_windows_own_scope(tmp_path):
    """an-mindmap-wrong-corpus-scope (P1, PR #744 remediation): a query/source/
    language/date-scoped analysis window used to fall through to the CORPUS-WIDE
    keyword/level branch of /api/insights/graph, silently dropping the window's own
    scope -- a search for "harvest" showed a mindmap built from the WHOLE corpus,
    "election" included. The endpoint must now route ANY of the analysis-window
    scope params (not just an explicit article_ids set) into the exact-article-set
    branch, exactly like its corpus-keywords/corpus-www siblings."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'graph.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(id=1, name="A", domain="a.test", country="fr"))
        s.add(Source(id=2, name="B", domain="b.test", country="fr"))
        s.commit()
        s.add(Article(
            id=1, url="https://a.test/1", canonical_url="https://a.test/1",
            source_id=1, title="Election piece", content="Election coverage.",
            hash="ga1", country="fr", language="en",
            published_at=datetime(2024, 4, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        ))
        s.add(Article(
            id=2, url="https://b.test/1", canonical_url="https://b.test/1",
            source_id=2, title="Harvest piece", content="Harvest coverage.",
            hash="ga2", country="fr", language="en",
            published_at=datetime(2024, 4, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        ))
        s.commit()
        s.add(Keyword(id=1, term="election", normalized_term="election", language="en"))
        s.add(Keyword(id=2, term="harvest", normalized_term="harvest", language="en"))
        s.commit()
        s.add(KeywordMention(keyword_id=1, article_id=1, count=9))
        s.add(KeywordMention(keyword_id=2, article_id=2, count=7))
        s.commit()

    def _override():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app
    from src.database.session import get_db

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            # source= alone (no article_ids) must scope the graph to THAT source's
            # article -- the exact-article branch, never the corpus-wide one.
            # (_query_articles's ``source`` filter matches Source.name, not domain.)
            ra = client.get("/api/insights/graph", params={"source": "A"}).json()
            assert ra["level"] == "article" and ra["n_articles"] == 1
            terms_a = {n["label"] for n in ra["nodes"]}
            assert "election" in terms_a and "harvest" not in terms_a

            rb = client.get("/api/insights/graph", params={"source": "B"}).json()
            assert rb["level"] == "article" and rb["n_articles"] == 1
            terms_b = {n["label"] for n in rb["nodes"]}
            assert "harvest" in terms_b and "election" not in terms_b

            # No scope param at all still requires the classic level/term contract
            # (the Insights tab's own corpus-wide "explore this term everywhere").
            r_missing_term = client.get("/api/insights/graph", params={"level": "keyword"})
            assert r_missing_term.status_code == 400
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_top_terms_non_term_kind_aggregates_before_the_limit(db):
    """2026-07-18 field fix (Families §0 row 1): a term-dominated corpus must not starve
    the entity view down to a handful of stray survivors. The Families 'all' view used
    to fetch the raw top-N (terms included) then filter kind!=='term' CLIENT-side --
    filter-AFTER-limit -- so with terms outnumbering entities 100:1 only the rare
    entities that happened to land in that raw top-N survived. kind='non_term' (what
    'all' now sends) must apply the is_entity filter BEFORE the limit, so with a small
    limit every real entity still surfaces even against a swamp of high-mention terms."""
    for i in range(100):
        db.add(Keyword(
            term=f"topic{i}", normalized_term=f"topic{i}", language="en",
            is_entity=False, mention_count=1000, article_count=50,
        ))
    for name in ("FIFA", "NATO"):
        db.add(Keyword(
            term=name, normalized_term=name, language="en",
            is_entity=True, entity_type="entity", mention_count=1, article_count=1,
        ))
    db.commit()

    # A naive "no kind filter, then trim" approach (mirroring the OLD client-side bug)
    # would only see the top 5 by mention_count -- all terms, zero entities.
    naive_top5 = q.top_terms(db, limit=5, group=False)["terms"]
    assert all(t["kind"] == "term" for t in naive_top5), "sanity: the swamp is real"

    out = q.top_terms(db, kind="non_term", limit=5, group=False)["terms"]
    names = {t["normalized"] for t in out}
    assert names == {"FIFA", "NATO"}, f"non_term must filter BEFORE the limit, got {names}"
    assert all(t["kind"] != "term" for t in out)
