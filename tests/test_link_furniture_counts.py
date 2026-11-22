"""Row 99: an outlet's page furniture is listed apart wherever citations are counted.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

PR #2053 kept an outlet's footer (an app badge on 494 of 495 hbl.fi articles) out of the reader's "Sources this article
cites". The same footer still inflated three other counts: the convergence shared-origin flag, the link preview's
"Articles in your corpus citing this URL" and Explore > Links. Each now asks the ONE measure
(``link_furniture.furniture_pairs``) and shows what it set aside, with its count.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source
from tests._app_engine import app_sqlite_engine

FOOTER = "https://apps.example/outlet-app"  # on every article of the big outlet
REPORT = "https://agency.example/report"  # cited by one big-outlet article and two small-outlet ones
BIG = 20  # exactly FURNITURE_MIN_ARTICLES


def _sessionmaker(tmp_path, *, big: int = BIG):
    engine = app_sqlite_engine(tmp_path / 'f.db', future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add_all([Source(name="Big", domain="big.example"), Source(name="Small", domain="small.example")])
        s.flush()
        aid = 0
        for _ in range(big):
            aid += 1
            s.add(Article(url=f"https://big.example/{aid}", canonical_url=f"https://big.example/{aid}", source_id=1,
                          title=f"Big {aid}", content="x", hash=f"b{aid}"))
        for _ in range(2):
            aid += 1
            s.add(Article(url=f"https://small.example/{aid}", canonical_url=f"https://small.example/{aid}", source_id=2,
                          title=f"Small {aid}", content="x", hash=f"s{aid}"))
        s.flush()
        for a in range(1, big + 1):
            s.add(ArticleLink(article_id=a, url=FOOTER, normalized_url=FOOTER, link_type="external"))
        for a in (1, big + 1, big + 2):
            s.add(ArticleLink(article_id=a, url=REPORT, normalized_url=REPORT, link_type="external"))
        s.commit()
    return Sess


def _client(Sess):
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app


def test_the_shared_origin_flag_counts_the_footer_apart(tmp_path):
    from src.analytics.convergence import _shared_origin, shared_origin_detail

    Sess = _sessionmaker(tmp_path)
    ids = [1, 2, BIG + 1, BIG + 2]
    with Sess() as s:
        d = shared_origin_detail(s, ids)
        assert d["count"] == 1 and d["examples"] == [REPORT]
        assert d["furniture_count"] == 1 and d["furniture_examples"] == [FOOTER]
        assert _shared_origin(s, ids) == (1, [REPORT]), "the card audit's reading drops the footer too"


def test_a_small_outlets_shared_link_is_still_a_shared_origin(tmp_path):
    from src.analytics.convergence import shared_origin_detail

    Sess = _sessionmaker(tmp_path, big=19)  # one short of the minimum: nothing is furniture
    with Sess() as s:
        d = shared_origin_detail(s, [1, 2, 20, 21])
        assert d["count"] == 2 and d["furniture_count"] == 0


def test_explore_links_lists_the_footer_apart_with_its_count(tmp_path):
    app = _client(_sessionmaker(tmp_path))
    try:
        with TestClient(app) as c:
            ids = ",".join(str(i) for i in range(1, BIG + 3))
            body = c.get(f"/api/links/corpus?article_ids={ids}").json()
    finally:
        app.dependency_overrides.clear()
    by_url = {i["normalized_url"]: i for i in body["items"]}
    assert set(by_url) == {REPORT}
    assert by_url[REPORT]["citations"] == 3 and by_url[REPORT]["citing_sources"] == 2
    assert by_url[REPORT]["furniture_carriers"] == 0, "one big-outlet article citing a report is a citation"
    apart = {i["normalized_url"]: i for i in body["furniture_items"]}
    assert set(apart) == {FOOTER}
    assert apart[FOOTER]["carried_by"] == BIG and apart[FOOTER]["citations"] == 0
    assert body["furniture_method"]


def test_the_link_preview_counts_the_footer_apart(tmp_path):
    app = _client(_sessionmaker(tmp_path))
    try:
        with TestClient(app) as c:
            footer = c.get("/api/links/preview", params={"url": FOOTER}).json()
            report = c.get("/api/links/preview", params={"url": REPORT}).json()
    finally:
        app.dependency_overrides.clear()
    assert footer["cited_by_articles"] == 0
    assert footer["furniture_articles"] == BIG and footer["furniture_sources"] == 1
    assert report["cited_by_articles"] == 3 and report["furniture_articles"] == 0


def test_every_surface_asks_the_one_measure():
    import inspect

    from src.analytics import convergence
    from src.api import link_analysis, link_preview

    for mod in (convergence, link_analysis, link_preview):
        assert "furniture_pairs" in inspect.getsource(mod), mod.__name__
