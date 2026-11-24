"""Row 397 (anti-capping): a Who/Where/When column cut to its biggest values says so.

``corpus_who``/``corpus_where``/``corpus_when`` keep ``limit`` groups for the chips and
now also count EVERY group in the matched set (``total``, ``truncated``), so a cut column
can say "40 of 300 shown". A year the date cannot be read from is dropped BEFORE the
limit, so it no longer takes a place and leaves the column short. The renderer is driven
in ``an_www_cut_node_test.js``; this file also drives it.
"""

from __future__ import annotations

import pathlib
import subprocess
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import (
    Article,
    ArticleEntity,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Source,
)
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
            published_at=datetime(2026, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        db.add(a)
        db.commit()
        ids.append(a.id)
    return ids


def test_who_where_when_report_every_group_when_cut(db):
    ids = _articles(db, 2)
    for k in range(5):
        db.add(ArticleEntity(article_id=ids[0], name=f"P{k}", entity_class="person"))
        db.add(ArticleMentionedPlace(article_id=ids[0], name=f"City{k}", country="fr", kind="city"))
        db.add(ArticleMentionedDate(article_id=ids[0], mentioned_on=date(2000 + k, 1, 1)))
    db.commit()
    for fn, key in ((q.corpus_who, "entities"), (q.corpus_where, "places"), (q.corpus_when, "years")):
        r = fn(db, article_ids=ids, limit=2)
        assert r["count"] == 2 and len(r[key]) == 2, fn.__name__
        assert r["total"] == 5 and r["truncated"] is True, fn.__name__
        whole = fn(db, article_ids=ids, limit=40)
        assert whole["total"] == 5 and whole["count"] == 5 and whole["truncated"] is False


def test_only_the_matched_articles_and_unrejected_dates_count(db):
    ids = _articles(db, 2)
    db.add(ArticleEntity(article_id=ids[0], name="A", entity_class="person"))
    db.add(ArticleEntity(article_id=ids[1], name="B", entity_class="person"))
    db.add(ArticleMentionedDate(article_id=ids[0], mentioned_on=date(2001, 1, 1)))
    db.add(ArticleMentionedDate(article_id=ids[0], mentioned_on=date(2002, 1, 1), status="rejected"))
    db.commit()
    assert q.corpus_who(db, article_ids=ids[:1])["total"] == 1
    assert q.corpus_when(db, article_ids=ids)["total"] == 1


def test_an_unreadable_year_no_longer_takes_a_place(db):
    ids = _articles(db, 3)
    db.add(ArticleMentionedDate(article_id=ids[0], mentioned_on=date(2001, 1, 1)))
    db.add(ArticleMentionedDate(article_id=ids[0], mentioned_on=date(2002, 1, 1)))
    db.commit()
    # A stored value strftime cannot read, ranked first by having the most articles.
    for a in ids:
        db.execute(
            text(
                "INSERT INTO article_mentioned_dates (article_id, mentioned_on, precision, status) "
                "VALUES (:a, 'not-a-date', 'day', 'candidate')"
            ),
            {"a": a},
        )
    db.commit()
    r = q.corpus_when(db, article_ids=ids, limit=2)
    assert [y["year"] for y in r["years"]] == ["2002", "2001"]
    assert r["total"] == 2 and r["truncated"] is False


def test_an_empty_set_carries_the_same_keys(db):
    assert q.corpus_who(db, article_ids=[]) == {"count": 0, "entities": [], "total": 0, "truncated": False}
    assert q.corpus_where(db, article_ids=[]) == {"count": 0, "places": [], "total": 0, "truncated": False}
    assert q.corpus_when(db, article_ids=[]) == {"count": 0, "years": [], "total": 0, "truncated": False}


def test_the_www_columns_say_when_they_were_cut_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "an_www_cut_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "an_www_cut_node_test.js: OK" in proc.stdout
