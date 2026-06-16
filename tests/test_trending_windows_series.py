"""
Per-term daily series on the Insights "Trends" 3-window substrate (additive
``series_top`` — feeds a future per-term ooChart). The series REUSES the existing
/trend day buckets, so the numbers match the trend chart; counts only, no score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_WINDOW_DAYS = {"24h": 1, "7d": 7, "30d": 30}


def _seed(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tws.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    today = date.today()
    with Sess() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        s.add(Keyword(id=1, term="surge", normalized_term="surge", language="en"))
        s.add(Keyword(id=2, term="steady", normalized_term="steady", language="en"))
        s.commit()
        # keyword_mentions is UNIQUE on (keyword_id, article_id) — one row per
        # (keyword, article). Spread a term across dates via distinct ARTICLES, each
        # carrying that term's mention with the article's observed_on date.
        aid = 0

        def _article_with(term_id: int, when: date) -> None:
            nonlocal aid
            aid += 1
            s.add(
                Article(
                    url=f"https://x.test/{aid}", canonical_url=f"https://x.test/{aid}",
                    source_id=1, title="t", content="c", hash=f"h{aid}", language="en",
                    created_at=datetime.now(UTC),
                )
            )
            s.commit()
            s.add(KeywordMention(keyword_id=term_id, article_id=aid, count=2, observed_on=when))
            s.commit()

        # surge: daily mentions across the last 10 days (multi-point series in 7d/30d)
        # AND a burst today → rises in every window.
        for d in range(0, 10):
            _article_with(1, today - timedelta(days=d))
        for _ in range(3):  # extra weight today so the 24h window surfaces it
            _article_with(1, today)
        # steady: a flat trickle across the last 60 days.
        for d in range(0, 60, 6):
            _article_with(2, today - timedelta(days=d))
    return Sess


def test_series_top_zero_is_unchanged(tmp_path):
    """Default (series_top=0) carries NO ``series`` keys — the existing contract."""
    Sess = _seed(tmp_path)
    with Sess() as s:
        base = q.trending_windows(s, limit=10)  # no series_top
        zero = q.trending_windows(s, limit=10, series_top=0)
    assert base == zero  # key-equivalence: the additive param at 0 changes nothing
    for w in base["windows"]:
        for t in w["terms"]:
            assert "series" not in t


def test_series_top_attaches_bounded_daily_series(tmp_path):
    Sess = _seed(tmp_path)
    with Sess() as s:
        res = q.trending_windows(s, limit=10, series_top=3)
    for w in res["windows"]:
        with_series = [t for t in w["terms"] if "series" in t]
        # Only the first <=3 terms carry a series.
        assert len(with_series) == min(3, len(w["terms"]))
        assert with_series == w["terms"][: len(with_series)]
        span = _WINDOW_DAYS[w["label"]]
        today = date.today()
        lo = (today - timedelta(days=span)).isoformat()
        hi = today.isoformat()
        for t in with_series:
            series = t["series"]
            assert isinstance(series, list)
            for pt in series:
                assert set(pt) == {"date", "count"}
                assert isinstance(pt["count"], int) and pt["count"] >= 0
                # The series is BOUNDED to the window's date range (span maps to days).
                assert lo <= pt["date"] <= hi
    # No composite score introduced anywhere by the addition.
    import json

    blob = json.dumps(res)
    assert '"score"' not in blob and '"relevance_score"' not in blob


def test_series_matches_trend_over_the_same_window(tmp_path):
    """Consistency: the attached series == /trend (day) sliced to the window — proves
    the series REUSES trend()'s aggregation rather than a parallel one."""
    Sess = _seed(tmp_path)
    with Sess() as s:
        res = q.trending_windows(s, limit=10, series_top=3)
        for w in res["windows"]:
            span = _WINDOW_DAYS[w["label"]]
            today = date.today()
            lo = (today - timedelta(days=span)).isoformat()
            hi = today.isoformat()
            for t in w["terms"]:
                if "series" not in t:
                    continue
                full = q.trend(s, t["normalized"], bucket="day")["points"]
                expected = [p for p in full if lo <= p["date"] <= hi]
                assert t["series"] == expected


def test_endpoint_returns_series(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    Sess = _seed(tmp_path)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/insights/trending-windows?series_top=3")
            assert r.status_code == 200
            data = r.json()
            assert [w["label"] for w in data["windows"]] == ["24h", "7d", "30d"]
            # At least one window has a term carrying a daily series.
            assert any(
                "series" in t for w in data["windows"] for t in w["terms"]
            )
            # Default still omits series.
            d0 = client.get("/api/insights/trending-windows").json()
            assert all("series" not in t for w in d0["windows"] for t in w["terms"])
    finally:
        app.dependency_overrides.clear()
