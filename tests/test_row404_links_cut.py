"""Row 404 (anti-capping): shared links say when cut; a branch opens the whole citing set.

``/api/links/corpus`` cut both lists at ``limit`` with no total; it now says how many there
are (``items_total``, ``furniture_total``, ``truncated``). ``/api/links/articles-by-link``
kept the LOWEST ids before dating them, so past ``limit`` it listed the oldest stored; it
now keeps the newest by the article's own published date (undated last, ties by id
descending) and returns every citing id up to the analysis window's 5000
(``article_ids``, ``ids_complete``), which the branch buttons open. The renderers are driven
in ``an_links_cut_node_test.js``; this file also drives it.
"""

from __future__ import annotations

import pathlib
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source
from tests._app_engine import app_sqlite_engine

_ROOT = pathlib.Path(__file__).resolve().parents[1]
ORIGIN = "https://agency.example/report"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture()
def Sess(tmp_path):
    engine = app_sqlite_engine(tmp_path / "l.db", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture()
def client(Sess):
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _article(s, k: int, src: int, published: datetime | None) -> int:
    a = Article(url=f"https://s{src}.example/{k}", canonical_url=f"https://s{src}.example/{k}", source_id=src,
                title=f"A{k}", content="x", hash=f"h{k}", published_at=published)
    s.add(a)
    s.flush()
    return a.id


def test_the_links_tab_says_how_many_links_there_are(Sess, client):
    with Sess() as s:
        s.add_all([Source(name="One", domain="one.example"), Source(name="Two", domain="two.example")])
        s.flush()
        arts = [_article(s, k, 1 + k % 2, T0) for k in range(4)]
        for u in range(5):  # five links, each cited by every article
            for a in arts:
                s.add(ArticleLink(article_id=a, url=f"https://x.example/{u}", normalized_url=f"https://x.example/{u}",
                                  link_type="external"))
        s.commit()
    ids = ",".join(str(a) for a in arts)
    d = client.get("/api/links/corpus", params={"article_ids": ids, "limit": 2}).json()
    assert len(d["items"]) == 2 and d["items_total"] == 5 and d["truncated"] is True
    whole = client.get("/api/links/corpus", params={"article_ids": ids, "limit": 40}).json()
    assert whole["items_total"] == 5 and whole["truncated"] is False and whole["furniture_total"] == 0


def test_citing_articles_keep_the_newest_and_undated_go_last(Sess, client):
    with Sess() as s:
        s.add(Source(name="One", domain="one.example"))
        s.flush()
        # Inserted oldest first, so the lowest ids are the OLDEST: the old cut kept them.
        dated = [_article(s, k, 1, T0 + timedelta(days=k)) for k in range(5)]
        undated = [_article(s, 100 + k, 1, None) for k in range(2)]
        for a in dated + undated:
            s.add(ArticleLink(article_id=a, url=ORIGIN, normalized_url=ORIGIN, link_type="external"))
        s.commit()
    d = client.get("/api/links/articles-by-link", params={"url": ORIGIN, "limit": 3}).json()
    assert d["count"] == 7
    assert [a["id"] for a in d["articles"]] == [dated[4], dated[3], dated[2]], "the newest were not kept"
    # undated never push out a dated one, and come last in the full set, newest id first
    assert d["article_ids"] == list(reversed(dated)) + sorted(undated, reverse=True)
    assert d["ids_complete"] is True
    # same date: ties break by id, newest first
    whole = client.get("/api/links/articles-by-link", params={"url": ORIGIN, "limit": 7}).json()
    assert [a["id"] for a in whole["articles"]] == d["article_ids"]


def test_more_than_200_and_at_most_5000_opens_every_id(Sess, client):
    with Sess() as s:
        s.add(Source(name="One", domain="one.example"))
        s.flush()
        arts = [_article(s, k, 1, T0 + timedelta(minutes=k)) for k in range(250)]
        for a in arts:
            s.add(ArticleLink(article_id=a, url=ORIGIN, normalized_url=ORIGIN, link_type="external"))
        s.commit()
    d = client.get("/api/links/articles-by-link", params={"url": ORIGIN}).json()
    assert d["count"] == 250 and len(d["articles"]) == 200
    assert len(d["article_ids"]) == 250 and set(d["article_ids"]) == set(arts) and d["ids_complete"] is True


def test_the_renderers_say_when_cut_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "an_links_cut_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "an_links_cut_node_test.js: OK" in proc.stdout
