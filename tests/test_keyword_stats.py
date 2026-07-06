"""Clickable-in-article-keyword hover stats (slice 2).

queries.keyword_stats returns REAL hover facts for one keyword — total mentions,
distinct-article spread, a windowed recent-vs-prior RATE, and top co-occurrences —
counts only, method + caveat, NO score. It reads the article_id-indexed mention
tables, never the keyword_mentions -> articles codec-join.

The report runs over a small indexed corpus (index_article maintains the mention
rows + counters); the endpoint runs in CI (fastapi).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _score_like_keys(obj) -> list[str]:
    found: list[str] = []

    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                kl = str(k).lower()
                if "score" in kl or "ranking" in kl or kl == "rank":
                    found.append(str(k))
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(obj)
    return found


@pytest.fixture()
def db():
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, Source

    engine = sa.create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _mk(db, h, text, days_ago):
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.models import Article

    when = datetime.now(UTC) - timedelta(days=days_ago)
    a = Article(
        url=f"https://x.test/{h}", canonical_url=f"https://x.test/{h}", source_id=1,
        title="T", content=text, hash=h, country="fr", language="en",
        published_at=when, created_at=when,
    )
    db.add(a)
    db.commit()
    index_article(db, a, extractor=BaselineExtractor(), country="fr", city="Paris")
    return a


def _seed(db):
    # "inflation" co-occurs with "markets"; recent AND prior mentions so the rate is real.
    _mk(db, "r1", "Inflation rose as inflation gripped global markets and markets fell.", 2)
    _mk(db, "r2", "Markets watched inflation closely while inflation pressures spread again.", 4)
    _mk(db, "p1", "Inflation dominated last month as inflation worries hit markets hard.", 20)
    _mk(db, "p2", "Analysts said inflation and inflation expectations moved the markets.", 25)
    _mk(db, "w1", "A quiet weather report about rainfall and rainfall patterns on the coast.", 3)


def test_mentions_and_article_spread_are_exact_counts(db):
    from src.analytics import queries as q

    _seed(db)
    r = q.keyword_stats(db, "inflation")
    assert r["resolved"]["normalized"] == "inflation"
    assert r["articles"] == 4, "distinct articles mentioning inflation"
    assert r["mentions"] >= 8, "total inflation mentions across the corpus"


def test_windowed_trend_rate_is_recent_vs_prior(db):
    from src.analytics import queries as q

    _seed(db)
    r = q.keyword_stats(db, "inflation", window_days=7, baseline_days=30)
    t = r["trend"]
    assert t["window_days"] == 7 and t["baseline_days"] == 30
    assert t["recent"] > 0 and t["prior"] > 0
    assert t["recent_per_day"] > 0 and t["prior_per_day"] > 0
    # growth = recent / expected (transparent ratio); a real float, not a score.
    assert isinstance(t["growth"], float)


def test_top_cooccurrences_present(db):
    from src.analytics import queries as q

    _seed(db)
    r = q.keyword_stats(db, "inflation", cooccur_limit=5)
    terms = {c["normalized"] for c in r["cooccurrences"]}
    assert "markets" in terms
    assert "rainfall" not in terms, "an unrelated term must not co-occur"
    for c in r["cooccurrences"]:
        assert set(c) == {"term", "normalized", "cooccur", "pmi"}
        assert c["cooccur"] >= 2


def test_cooccur_limit_zero_skips_the_heavy_path(db):
    from src.analytics import queries as q

    _seed(db)
    r = q.keyword_stats(db, "inflation", cooccur_limit=0)
    assert r["cooccurrences"] == []
    assert r["mentions"] >= 8  # the cheap counts still returned


def test_unknown_term_is_honest_not_a_crash(db):
    from src.analytics import queries as q

    r = q.keyword_stats(db, "zzzznotacorpusterm")
    assert r["resolved"] is None
    assert r["mentions"] == 0 and r["articles"] == 0
    assert r["cooccurrences"] == []
    assert r["trend"]["recent"] == 0


def test_no_score_fields_and_caveat(db):
    from src.analytics import queries as q

    _seed(db)
    r = q.keyword_stats(db, "inflation")
    assert _score_like_keys(r) == []
    assert "never a score" in r["caveat"]
    assert "not causation" in r["caveat"]


# ----------------------------- wiring (no fastapi) ----------------------------- #

def test_endpoint_is_wired():
    ins = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    assert '@router.get("/keyword-stats")' in ins
    assert "q.keyword_stats(" in ins


# ----------------------------- the endpoint (CI) ------------------------------- #

def test_keyword_stats_endpoint(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _seed(db)
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/insights/keyword-stats?term=inflation")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["articles"] == 4
            assert data["trend"]["window_days"] == 7
            assert _score_like_keys(data) == []
    finally:
        app.dependency_overrides.clear()
