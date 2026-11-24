"""Row 398 (anti-capping): the corpus-wide Who list and the map's Places say when cut.

``who_aggregate``/``where_aggregate`` keep ``limit`` rows and now also count every group
the same filters and threshold keep (``total``, ``truncated``). ``where_aggregate``'s
``placed_only`` drops places the gazetteer cannot locate BEFORE the limit, so a map's
slots all hold drawable places. The renderers are driven in
``who_where_cut_node_test.js``; this file also drives it.
"""

from __future__ import annotations

import pathlib
import subprocess
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, ArticleEntity, ArticleMentionedPlace, Base, Source
from tests._app_engine import app_sqlite_engine

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _articles(db, n: int) -> list[int]:
    src = Source(name="S", domain="s.test", country="fr")
    db.add(src)
    db.commit()
    ids = []
    for j in range(n):
        a = Article(
            url=f"https://s.test/{j}", canonical_url=f"https://s.test/{j}", source_id=src.id,
            title="T", content="x", hash=f"h{j}", language="en",
            published_at=datetime.now(UTC), created_at=datetime.now(UTC),
        )
        db.add(a)
        db.commit()
        ids.append(a.id)
    return ids


def test_who_counts_every_name_and_honours_the_threshold(db):
    ids = _articles(db, 2)
    for k in range(5):
        db.add(ArticleEntity(article_id=ids[0], name=f"P{k}", entity_class="person"))
    db.add(ArticleEntity(article_id=ids[1], name="P0", entity_class="person"))
    db.commit()
    r = q.who_aggregate(db, limit=2)
    assert r["count"] == 2 and r["total"] == 5 and r["truncated"] is True
    whole = q.who_aggregate(db, limit=50)
    assert whole["total"] == 5 and whole["truncated"] is False
    # the HAVING threshold counts too: only P0 is in two articles
    two = q.who_aggregate(db, limit=50, min_articles=2)
    assert two["total"] == 1 and two["count"] == 1 and two["truncated"] is False


def test_where_counts_every_place_and_placed_only_fills_the_slots(db):
    ids = _articles(db, 3)
    # two unlocated places in the most articles, then two located ones
    for a in ids:
        db.add(ArticleMentionedPlace(article_id=a, name="Nowhere", country="fr", kind="city"))
        db.add(ArticleMentionedPlace(article_id=a, name="Elsewhere", country="fr", kind="city"))
    db.add(ArticleMentionedPlace(article_id=ids[0], name="Paris", country="fr", kind="city", lat=48.86, lon=2.35))
    db.add(ArticleMentionedPlace(article_id=ids[0], name="Lyon", country="fr", kind="city", lat=45.76, lon=4.84))
    db.commit()
    r = q.where_aggregate(db, limit=2)
    assert r["total"] == 4 and r["truncated"] is True and r["placed"] == 0
    m = q.where_aggregate(db, limit=2, placed_only=True)
    assert sorted(p["name"] for p in m["places"]) == ["Lyon", "Paris"]
    assert m["placed"] == 2 and m["total"] == 2 and m["truncated"] is False
    assert m["placed_only"] is True and r["placed_only"] is False


def test_the_renderers_say_when_cut_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "who_where_cut_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "who_where_cut_node_test.js: OK" in proc.stdout
