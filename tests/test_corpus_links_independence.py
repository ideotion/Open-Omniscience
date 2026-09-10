"""``/api/links/corpus`` reports independence, not just volume.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Links view exists to make shared-origin structure visible. A distinct-ARTICLE count
alone cannot do that: three articles from one outlet citing a page and three articles
from three outlets citing it produce the same number and mean opposite things. The
retired #corpus-win modal reported the distinct-SOURCE count beside it and said, per
link, which situation it was; the #an window that replaced it reported the article count
under one blanket caveat. These pin the pair, and the exact boundary between the two
verdicts -- including the case that makes the rule non-obvious: MORE articles than
sources is single_origin even when several outlets are involved, because one outlet
citing twice makes the article count overstate the number of independent paths.
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source

# Three sources; six articles; four cited URLs chosen to hit every branch.
_THREE_OUTLETS = "https://example.test/three-outlets"   # 3 articles, 3 sources
_REPEAT_OUTLET = "https://example.test/repeat-outlet"   # 3 articles, 2 sources
_LONE_OUTLET = "https://example.test/lone-outlet"       # 2 articles, 1 source
_SINGLETON = "https://example.test/singleton"           # 1 article -- below min_citations


def _client(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'indep.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        for n in ("Alpha", "Beta", "Gamma"):
            s.add(Source(name=n, domain=f"{n.lower()}.test"))
        s.flush()
        # article id -> source id
        owners = {1: 1, 2: 2, 3: 3, 4: 1, 5: 1, 6: 2}
        for aid, sid in owners.items():
            s.add(
                Article(
                    url=f"https://a.test/{aid}",
                    canonical_url=f"https://a.test/{aid}",
                    source_id=sid,
                    title=f"Article {aid}",
                    content="x",
                    hash=f"h{aid}",
                )
            )
        s.flush()

        def link(aid: int, url: str) -> ArticleLink:
            return ArticleLink(
                article_id=aid, url=url, normalized_url=url, link_type="external"
            )

        s.add_all(
            [
                # 1/2/3 are Alpha/Beta/Gamma -- three articles, three outlets.
                link(1, _THREE_OUTLETS), link(2, _THREE_OUTLETS), link(3, _THREE_OUTLETS),
                # 1 and 4 are both Alpha; 6 is Beta -- three articles, only two outlets.
                link(1, _REPEAT_OUTLET), link(4, _REPEAT_OUTLET), link(6, _REPEAT_OUTLET),
                # 4 and 5 are both Alpha -- two articles, one outlet.
                link(4, _LONE_OUTLET), link(5, _LONE_OUTLET),
                link(2, _SINGLETON),
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


def _items(tmp_path):
    app = _client(tmp_path)
    try:
        with TestClient(app) as c:
            r = c.get("/api/links/corpus?article_ids=1,2,3,4,5,6")
            assert r.status_code == 200, r.text
            body = r.json()
        return body, {i["normalized_url"]: i for i in body["items"]}
    finally:
        app.dependency_overrides.clear()


def test_distinct_source_count_rides_beside_the_article_count(tmp_path):
    _, by_url = _items(tmp_path)
    assert by_url[_THREE_OUTLETS]["citations"] == 3
    assert by_url[_THREE_OUTLETS]["citing_sources"] == 3
    assert by_url[_REPEAT_OUTLET]["citations"] == 3
    assert by_url[_REPEAT_OUTLET]["citing_sources"] == 2
    assert by_url[_LONE_OUTLET]["citations"] == 2
    assert by_url[_LONE_OUTLET]["citing_sources"] == 1


def test_only_one_article_per_outlet_reads_as_distinct_sources(tmp_path):
    _, by_url = _items(tmp_path)
    assert by_url[_THREE_OUTLETS]["independence"] == "distinct_sources"


def test_an_outlet_citing_twice_reads_as_one_path_even_beside_other_outlets(tmp_path):
    """The non-obvious branch: two real outlets, and still not independent paths.

    Three citations from two outlets cannot be three independent paths. Reporting
    distinct_sources here -- on the grounds that "more than one outlet is involved" --
    would let a repeated citation inflate the apparent corroboration, which is the exact
    confusion the Links view exists to prevent.
    """
    _, by_url = _items(tmp_path)
    assert by_url[_REPEAT_OUTLET]["citing_sources"] == 2
    assert by_url[_REPEAT_OUTLET]["independence"] == "single_origin"


def test_a_lone_outlet_reads_as_one_path(tmp_path):
    _, by_url = _items(tmp_path)
    assert by_url[_LONE_OUTLET]["independence"] == "single_origin"


def test_a_single_citation_is_never_reported_as_distinct_sources(tmp_path):
    """The branch the default floor hides, found by a mutant that survived without it.

    ``min_citations`` is a caller-settable Query with ``ge=1``, so a caller asking for
    singly-cited links gets rows where citations == sources == 1. The "more than one
    source" half of the rule is the only thing standing between that and a link cited by
    ONE article from ONE outlet being labelled as coming from distinct outlets -- the
    most misleading verdict this field can carry, on the least corroborated row there is.
    Dropping that half passed every other test here, because the default floor of 2 keeps
    the case out of the fixture.
    """
    app = _client(tmp_path)
    try:
        with TestClient(app) as c:
            body = c.get(
                "/api/links/corpus?article_ids=1,2,3,4,5,6&min_citations=1"
            ).json()
        by_url = {i["normalized_url"]: i for i in body["items"]}
        lone = by_url[_SINGLETON]
        assert lone["citations"] == 1 and lone["citing_sources"] == 1
        assert lone["independence"] == "single_origin"
    finally:
        app.dependency_overrides.clear()


def test_the_join_does_not_inflate_the_article_count(tmp_path):
    """Joining Article to count sources must not fan out the count grouped beside it.

    A link row belongs to exactly one article, so the join is many-to-one and the
    distinct-article count is unchanged -- but a join added for a second aggregate is
    exactly where a duplicated row silently doubles the first one.
    """
    _, by_url = _items(tmp_path)
    # Nine link rows over four URLs; every count is the real number of distinct articles.
    assert sum(i["citations"] for i in by_url.values()) == 3 + 3 + 2
    assert all(i["citing_sources"] <= i["citations"] for i in by_url.values())


def test_a_link_cited_once_stays_below_the_floor(tmp_path):
    body, by_url = _items(tmp_path)
    assert _SINGLETON not in by_url
    assert body["min_citations"] == 2


def test_the_caveat_names_what_the_source_count_does_and_does_not_buy(tmp_path):
    body, _ = _items(tmp_path)
    assert "not independent confirmation" in body["caveat"]
    assert "share an upstream origin" in body["caveat"], (
        "distinct outlets still may not be independent -- the view must say so rather "
        "than let the count read as a guarantee"
    )
