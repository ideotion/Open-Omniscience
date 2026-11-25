"""Row 399: Agenda deduced dates are never cut silently, and open their exact set.

``upcoming_deduced`` kept 80 dates of a window that holds 121, so later weeks read as
empty; it now keeps every date the window holds by default and says when a smaller
``limit`` cut it. Each date carries at most 200 ids inline (read in ONE query, it was
one per date) with ``ids_complete``; ``deduced_date_article_ids`` and
``GET /api/events/deduced/ids`` give the full set up to the analysis window's 5000, and
the agenda reads it before it opens the date (invariant 13b). The agenda side is driven
in ``ag_deduced_open_node_test.js``; this file also drives it.
"""

from __future__ import annotations

import pathlib
import subprocess
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleMentionedDate, Base, Source
from src.timemap import datestore
from tests._app_engine import app_sqlite_engine

_ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = date(2026, 3, 1)


@pytest.fixture()
def Sess(tmp_path):
    engine = app_sqlite_engine(tmp_path / "d.db", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed(db, n_articles: int, dates: list[date]) -> list[int]:
    src = Source(name="S", domain="s.test")
    db.add(src)
    db.commit()
    ids = []
    for j in range(n_articles):
        a = Article(
            url=f"https://s.test/{j}", canonical_url=f"https://s.test/{j}", source_id=src.id,
            title="T", content="x", hash=f"h{j}", language="en",
            published_at=datetime(2026, 2, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        db.add(a)
        db.commit()
        ids.append(a.id)
        for d in dates:
            db.add(ArticleMentionedDate(article_id=a.id, mentioned_on=d))
    db.commit()
    return ids


def test_a_full_window_is_never_cut(Sess):
    with Sess() as db:
        days = [TODAY + timedelta(days=k) for k in range(121)]
        _seed(db, 2, days)
        r = datestore.upcoming_deduced(db, today=TODAY, days_ahead=120, min_articles=2)
        assert r["count"] == 121 and r["truncated"] is False
        assert r["events"][-1]["date"] == (TODAY + timedelta(days=120)).isoformat()
        cut = datestore.upcoming_deduced(db, today=TODAY, days_ahead=120, min_articles=2, limit=80)
        assert cut["count"] == 80 and cut["truncated"] is True


def test_inline_ids_stop_at_200_and_say_so(Sess):
    with Sess() as db:
        ids = _seed(db, 205, [TODAY + timedelta(days=3)])
        r = datestore.upcoming_deduced(db, today=TODAY, min_articles=2)
        (ev,) = r["events"]
        assert ev["n_articles"] == 205 and len(ev["article_ids"]) == 200
        assert ev["ids_complete"] is False
        full = datestore.deduced_date_article_ids(db, TODAY + timedelta(days=3))
        assert full["total"] == 205 and full["complete"] is True
        assert sorted(full["article_ids"]) == sorted(ids)
        capped = datestore.deduced_date_article_ids(db, TODAY + timedelta(days=3), cap=50)
        assert len(capped["article_ids"]) == 50 and capped["complete"] is False and capped["total"] == 205


def test_a_small_date_is_complete_and_rejected_tags_stay_out(Sess):
    with Sess() as db:
        on = TODAY + timedelta(days=5)
        ids = _seed(db, 3, [on])
        db.query(ArticleMentionedDate).filter(ArticleMentionedDate.article_id == ids[0]).update(
            {"status": "rejected"}
        )
        db.commit()
        (ev,) = datestore.upcoming_deduced(db, today=TODAY, min_articles=2)["events"]
        assert ev["n_articles"] == 2 and ev["ids_complete"] is True
        assert sorted(ev["article_ids"]) == sorted(ids[1:])
        assert sorted(datestore.deduced_date_article_ids(db, on)["article_ids"]) == sorted(ids[1:])


def test_the_ids_endpoint(Sess):
    import src.database.session as _sess
    from src.api.main import app

    with Sess() as db:
        _seed(db, 2, [date(2026, 4, 1)])
    old = _sess.SessionLocal
    _sess.SessionLocal = Sess
    try:
        with TestClient(app) as client:
            r = client.get("/api/events/deduced/ids", params={"date": "2026-04-01"})
            assert r.status_code == 200
            d = r.json()
            assert d["total"] == 2 and d["complete"] is True and len(d["article_ids"]) == 2
            assert client.get("/api/events/deduced/ids", params={"date": "nope"}).status_code == 400
    finally:
        _sess.SessionLocal = old


def test_the_agenda_opens_the_full_set_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "ag_deduced_open_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ag_deduced_open_node_test.js: OK" in proc.stdout
