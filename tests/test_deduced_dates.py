"""
The agenda's article-extracted DEDUCED-dates layer (RC-BLOCKING agenda content):
future dates an article MENTIONS, grouped and surfaced as agenda events — deduced
from text, never confirmed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleMentionedDate, Base, Source
from src.timemap import datestore


def _seed(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dd.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    today = date.today()
    with Sess() as s:
        s.add(Source(name="A", domain="a.test"))
        s.add(Source(name="B", domain="b.test"))
        s.commit()
        # 3 articles (2 sources) mention a date 10 days out → passes the ≥2 gate.
        soon = today + timedelta(days=10)
        for i, src in enumerate([1, 1, 2], start=1):
            s.add(
                Article(
                    url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=src,
                    title="t", content="c", hash=f"h{i}", language="en",
                    created_at=datetime.now(UTC),
                )
            )
            s.commit()
            s.add(ArticleMentionedDate(article_id=i, mentioned_on=soon, precision="day",
                                       status="candidate", extractor="regex"))
        # A single-mention future date → BELOW the gate, must not surface.
        s.add(
            Article(url="https://x/9", canonical_url="https://x/9", source_id=1, title="t",
                    content="c", hash="h9", language="en", created_at=datetime.now(UTC))
        )
        s.commit()
        s.add(ArticleMentionedDate(article_id=9, mentioned_on=today + timedelta(days=20),
                                   precision="day", status="candidate", extractor="regex"))
        # A PAST date (2 articles) → out of the forward window, must not surface.
        past = today - timedelta(days=30)
        for i in (10, 11):
            s.add(Article(url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=1,
                          title="t", content="c", hash=f"h{i}", language="en",
                          created_at=datetime.now(UTC)))
            s.commit()
            s.add(ArticleMentionedDate(article_id=i, mentioned_on=past, precision="day",
                                       status="candidate", extractor="regex"))
        s.commit()
    return Sess, soon


def test_upcoming_deduced_gates_and_counts(tmp_path):
    Sess, soon = _seed(tmp_path)
    with Sess() as s:
        res = datestore.upcoming_deduced(s, days_ahead=120, min_articles=2)
    dates = {e["date"]: e for e in res["events"]}
    # Only the ≥2-article future date surfaces (single-mention + past are excluded).
    assert set(dates) == {soon.isoformat()}
    ev = dates[soon.isoformat()]
    assert ev["n_articles"] == 3 and ev["n_sources"] == 2
    assert sorted(ev["article_ids"]) == [1, 2, 3]
    assert res["method"] and res["caveat"]
    # Counts only — no composite score anywhere.
    assert "score" not in ev
    assert "never confirmed" in res["caveat"] or "not proof" in res["caveat"]


def test_deduced_endpoint(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    Sess, _ = _seed(tmp_path)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    # The endpoint uses session_scope internally, so patch SessionLocal too.
    import src.database.session as _sess

    app.dependency_overrides[get_db] = _db
    old = _sess.SessionLocal
    _sess.SessionLocal = Sess
    try:
        with TestClient(app) as client:
            r = client.get("/api/events/deduced")
            assert r.status_code == 200
            data = r.json()
            assert "events" in data and data["method"] and data["caveat"]
            assert all("article_ids" in e and "n_sources" in e for e in data["events"])
    finally:
        _sess.SessionLocal = old
        app.dependency_overrides.clear()
