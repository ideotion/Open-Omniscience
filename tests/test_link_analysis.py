"""Co-citation API: most-cited sources + articles-by-link (the macro Insights view).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest aggregation: "citations" = the number of *distinct articles* that link to a
URL/domain. These lock the contract the "Most-cited sources" UI depends on.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source


def _client(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'links.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        for i in range(3):
            s.add(
                Article(
                    url=f"https://s.test/{i}",
                    canonical_url=f"https://s.test/{i}",
                    source_id=1,
                    title=f"Article {i}",
                    content="x",
                    hash=f"h{i}",
                )
            )
        s.flush()
        reut = "https://www.reuters.com/world/report"
        # Articles 1 and 2 both cite Reuters; article 3 cites AP.
        s.add_all(
            [
                ArticleLink(article_id=1, url=reut, normalized_url=reut, link_type="external"),
                ArticleLink(article_id=2, url=reut, normalized_url=reut, link_type="external"),
                ArticleLink(
                    article_id=3,
                    url="https://apnews.com/x",
                    normalized_url="https://apnews.com/x",
                    link_type="external",
                ),
            ]
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app


def test_top_cited_and_articles_by_link(tmp_path):
    app = _client(tmp_path)
    try:
        with TestClient(app) as c:
            # Shared domain cited by >= 2 distinct articles surfaces; the singleton does not.
            dom = c.get("/api/links/top-cited?by=domain&min_citations=2").json()
            doms = {i["domain"]: i["citations"] for i in dom["items"]}
            assert doms == {"reuters.com": 2}

            by_url = c.get("/api/links/top-cited?by=url&min_citations=2").json()
            assert by_url["items"] and by_url["items"][0]["citations"] == 2
            assert by_url["items"][0]["domain"] == "reuters.com"

            # Assemble every article citing that domain.
            arts = c.get("/api/links/articles-by-link?domain=reuters.com").json()
            assert arts["count"] == 2
            assert {a["id"] for a in arts["articles"]} == {1, 2}

            assert c.get("/api/links/articles-by-link").status_code == 400  # needs url or domain
    finally:
        app.dependency_overrides.clear()
