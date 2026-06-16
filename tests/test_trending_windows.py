"""
The Insights "Trends" 3-window substrate (maintainer-ruled 2026-06-16): rising
keywords across past 24h · past week · past month, side by side.

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


def _seed(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tw.db'}", future=True, connect_args={"check_same_thread": False}
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
        # (keyword, article). So spread a term across dates via distinct ARTICLES,
        # each carrying that term's mention with the article's observed_on date.
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

        # surge: a burst TODAY, nothing in the prior window → high recent-vs-prior ratio.
        for _ in range(4):
            _article_with(1, today)
        # steady: a flat trickle across the last 60 days (no spike).
        for d in range(0, 60, 6):
            _article_with(2, today - timedelta(days=d))
    return Sess


def test_trending_windows_three_presets_and_rising_term(tmp_path):
    Sess = _seed(tmp_path)
    with Sess() as s:
        res = q.trending_windows(s, limit=10)
    labels = [w["label"] for w in res["windows"]]
    assert labels == ["24h", "7d", "30d"]  # the three preset windows, in order
    for w in res["windows"]:
        assert {"window_days", "baseline_days", "terms", "count", "scanned"} <= set(w)
    # The 24h burst term surfaces in the 24h window.
    h24 = next(w for w in res["windows"] if w["label"] == "24h")
    assert any(t["term"] == "surge" for t in h24["terms"])
    # Honest method + caveat, and no composite score anywhere in the payload.
    assert res["method"] and res["caveat"]
    for w in res["windows"]:
        for t in w["terms"]:
            assert "growth" in t and "recent" in t  # disclosed ratio + raw n
            assert "score" not in t and "relevance_score" not in t


def test_trending_windows_endpoint(tmp_path):
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
            r = client.get("/api/insights/trending-windows")
            assert r.status_code == 200
            data = r.json()
            assert [w["label"] for w in data["windows"]] == ["24h", "7d", "30d"]
            assert data["method"] and data["caveat"]
    finally:
        app.dependency_overrides.clear()
