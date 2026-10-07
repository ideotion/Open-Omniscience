"""A stand-in row is never shown as data (the delta read of E3 fold 3, B; the coordinator's check of fold 3, item 4).

A salvage copy keeps a row whose parent could not be read and writes ONE stand-in row into the parent table at the lost id
(:mod:`src.database.salvage`). The stand-in is a place-holder: this file makes a REAL salvage copy of a real damaged store (the newest
articles lost, so there is a stand-in article under a stand-in source) and asks every reader that could show it: the article list and
browse, an explicit id set, a query with only negative terms, a query of field filters only, the export, the advanced search that INCLUDES
quarantined articles, the source lists and facets and counts, the qualification passes and the collection pass. Each claim has a positive
control (the same call shows real rows), so a reader that stopped answering at all cannot pass for one that leaves the stand-in out.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import salvage, stand_in
from src.database.salvage import Salvage

from . import damaged_store_helpers as H

STAND_IN_ARTICLE = 1500  # the newest of the 1,500 articles of the store: its pages are the ones lost
LOST_SOURCES_DOMAIN = "(lost sources 13)"


@pytest.fixture(scope="module")
def salvaged(tmp_path_factory) -> Path:
    """A salvage copy of a store whose newest articles are unreadable: 1,499 real articles, one stand-in article (id 1500) under a
    stand-in source (id 13), beside 12 real sources."""
    root = tmp_path_factory.mktemp("stand-in-rows")
    pristine = root / "pristine.db"
    H.build_app_store(pristine, articles=1500)
    src = H.copy_store(pristine, root / "damaged.db")
    con = sqlite3.connect(src)
    con.executemany("INSERT INTO article_links (article_id, url, normalized_url) VALUES (?, ?, ?)", [(i, f"https://l.example/{i}", f"l.example/{i}") for i in range(1, 1501)])
    con.commit()
    con.close()
    H.overwrite_pages(src, H.leaf_pages(src, "articles")[-2:], H.PLAIN_PAGE)
    out = root / "salvaged.db"
    report = Salvage(src, out).run()
    assert report["stand_ins"] == {"articles": STAND_IN_ARTICLE, "sources": 13}, report.get("stand_ins")
    return out


@pytest.fixture()
def db(salvaged, tmp_path):
    """A session on a throw-away copy of the salvage copy (a test may change a row)."""
    path = H.copy_store(salvaged, tmp_path / "copy.db")
    engine = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(salvaged, tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    path = H.copy_store(salvaged, tmp_path / "api.db")
    engine = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, future=True)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def _real_articles(path: Path) -> int:
    con = H.open_store(path)
    try:
        return int(con.execute("SELECT count(*) FROM articles WHERE quarantined IS NOT 1").fetchone()[0])
    finally:
        con.close()


def _ids(payload) -> list[int]:
    rows = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
    return [int(r["id"]) for r in rows]


# --------------------------------------------------------------------------- #
#  what the copy writes
# --------------------------------------------------------------------------- #
def test_a_stand_in_article_is_quarantined_and_a_stand_in_source_is_not_enabled_and_both_say_they_are_lost(salvaged):
    con = H.open_store(salvaged)
    try:
        art = con.execute("SELECT quarantined, quarantine_reason, url, title FROM articles WHERE id = ?", (STAND_IN_ARTICLE,)).fetchone()
        assert art[0] == 1 and art[1] == stand_in.ARTICLE_REASON and art[2].startswith("(lost articles") and art[3] is None, art
        src = con.execute("SELECT enabled, name, domain, status FROM sources WHERE id = 13").fetchone()
        assert src[0] == 0 and src[1] == LOST_SOURCES_DOMAIN and src[2] == LOST_SOURCES_DOMAIN and src[2].startswith(stand_in.SOURCE_DOMAIN_PREFIX), src
        # the note the report carries says what holds (the OPEN_QUEUE entry says the same)
        for claim in ("quarantined", "stand-in for a lost row", "source lists", "never collected or qualified", "deleted", "signed evidence bundle", "AI routes", "date tags", "finds it by its number", "deleted with a database tool", "still include it"):
            assert claim in salvage.STAND_IN_NOTE, f"the report's note does not say {claim!r}"
        # the real rows carry none of these marks
        assert con.execute("SELECT count(*) FROM articles WHERE quarantine_reason = ?", (stand_in.ARTICLE_REASON,)).fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM sources WHERE enabled = 0").fetchone()[0] == 1
    finally:
        con.close()


def test_the_text_a_stand_in_source_carries_starts_with_the_prefix_the_readers_leave_out():
    """The copy writes ``(lost sources 13)`` through ``stand_in.lost_text`` and the readers leave out by ``SOURCE_DOMAIN_PREFIX``: two names for one fact."""
    assert stand_in.lost_text("sources", 13).startswith(stand_in.SOURCE_DOMAIN_PREFIX)


def test_a_table_without_the_mark_columns_is_given_none_of_them(tmp_path):
    """The marks go only where the table has the column (a store from before a column existed is still salvaged, and the copy is never refused for it)."""
    src = tmp_path / "old.db"
    con = sqlite3.connect(src)
    con.executescript(
        "CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL, domain TEXT NOT NULL UNIQUE);"
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), url TEXT NOT NULL);"
    )
    con.executemany("INSERT INTO sources (name, domain) VALUES (?, ?)", [(f"s{i}", f"s{i}.example") for i in range(3)])
    con.executemany("INSERT INTO articles (source_id, url) VALUES (?, ?)", [(3, f"https://e.org/{i}") for i in range(3)])
    con.execute("DELETE FROM sources WHERE id = 3")  # the articles' source is the newest one and is lost
    con.commit()
    con.close()
    out = tmp_path / "out.db"
    report = Salvage(src, out).run()
    assert report["stand_ins"] == {"sources": 3}, report.get("stand_ins")
    con = sqlite3.connect(out)
    try:
        assert [r[1] for r in con.execute("PRAGMA table_info(sources)")] == ["id", "name", "domain"]
        assert con.execute("SELECT domain FROM sources WHERE id = 3").fetchone()[0] == "(lost sources 3)"
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  the article readers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("include", [False, True], ids=["default", "includes-quarantined"])
def test_the_article_list_the_browse_and_an_explicit_id_set_never_show_the_stand_in(client, salvaged, include):
    flag = {"include_quarantined": "true"} if include else {}
    # an ascending date browse puts a row with no date FIRST: a stand-in that got through would head the list
    browse = client.get("/api/articles", params={"sort_by": "date", "sort_dir": "asc", "limit": 50, **flag})
    assert browse.status_code == 200, browse.text
    ids = _ids(browse.json())
    assert len(ids) == 50 and STAND_IN_ARTICLE not in ids, "the browse lost its rows or listed the stand-in"
    assert browse.json()["total"] == _real_articles(salvaged), browse.json()["total"]
    by_id = client.get("/api/articles", params={"ids": f"{STAND_IN_ARTICLE},1,2", **flag})
    assert by_id.status_code == 200, by_id.text
    assert sorted(_ids(by_id.json())) == [1, 2], "an explicit id set must give the real rows and never the stand-in"


@pytest.mark.parametrize("include", [False, True], ids=["default", "includes-quarantined"])
@pytest.mark.parametrize("query", ["NOT zzzqq", "url:lost", "url:lost NOT zzzqq", "source:lost"], ids=["negative-only", "field-only", "field-and-negative", "source-field"])
def test_a_query_of_negative_terms_or_field_filters_only_never_returns_the_stand_in(client, query, include):
    flag = {"include_quarantined": "true"} if include else {}
    got = client.get("/api/articles", params={"query": query, "limit": 100, **flag})
    assert got.status_code == 200, got.text
    assert STAND_IN_ARTICLE not in _ids(got.json())
    if query == "NOT zzzqq":  # the positive control: a query with nothing but a negative term lists real rows
        assert len(_ids(got.json())) == 100


@pytest.mark.parametrize("include", [False, True], ids=["default", "includes-quarantined"])
@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_the_export_never_holds_the_stand_in(client, fmt, include):
    flag = {"include_quarantined": "true"} if include else {}
    got = client.get("/api/articles/export", params={"format": fmt, "ids": f"{STAND_IN_ARTICLE},1,2", **flag})
    assert got.status_code == 200, got.text
    assert "(lost articles" not in got.text, "the export holds the stand-in"
    assert "https://e.org/0" in got.text or "e.org" in got.text, "the positive control: the export holds the real rows"
    got = client.get("/api/articles/export", params={"format": fmt, "query": "NOT zzzqq", **flag})
    assert got.status_code == 200 and "(lost articles" not in got.text and "e.org" in got.text


def test_the_counts_of_what_the_app_judged_not_an_article_do_not_count_the_stand_in(db):
    """Quarantine is a judgement the app made; a stand-in is quarantined only so that no reader shows it, and is not counted as one."""
    from src.analytics.article_length import article_length_report
    from src.analytics.figures import quarantine_composition
    from src.api.feed import _held_back
    from src.database.models import Article, Source

    assert db.query(Article).filter(Article.quarantined.is_(True)).count() == 1, "the premise: the stand-in is the one quarantined row"
    assert _held_back(db, Article, Source)["quarantined"] == 0
    composition = quarantine_composition(db)
    assert composition["rows"] == [] and composition["n"] == 0, composition["rows"]
    assert article_length_report(db)["excluded_quarantined"] == 0
    # the positive control: a quarantine the app judged IS counted, and the stand-in still is not
    db.query(Article).filter(Article.id == 1).update({"quarantined": True, "quarantine_reason": "nav_soup"}, synchronize_session=False)
    db.commit()
    assert _held_back(db, Article, Source)["quarantined"] == 1
    assert [r["reason"] for r in quarantine_composition(db)["rows"]] == ["nav_soup"]
    assert article_length_report(db)["excluded_quarantined"] == 1


# --------------------------------------------------------------------------- #
#  the source readers
# --------------------------------------------------------------------------- #
def test_the_source_lists_the_facets_the_counts_and_the_export_never_hold_the_stand_in_source(client):
    bare = client.get("/api/sources").json()
    assert len(bare) == 12 and all(s["domain"] != LOST_SOURCES_DOMAIN for s in bare), [s["domain"] for s in bare]
    paged = client.get("/api/sources/", params={"limit": 1000})
    assert paged.status_code == 200, paged.text
    domains = [s["domain"] for s in paged.json()]
    assert len(domains) == 12 and LOST_SOURCES_DOMAIN not in domains
    by_name = client.get("/api/sources/", params={"q": "lost", "limit": 1000}).json()
    assert by_name == [], "a search of the source list by the stand-in's name found it"
    listed = client.get("/api/catalog/sources", params={"limit": 1000})  # the Sources tab's filterable list
    assert listed.status_code == 200, listed.text
    assert LOST_SOURCES_DOMAIN not in listed.text and "s0.example.org" in listed.text
    csv = client.get("/api/catalog/export.csv")
    assert csv.status_code == 200 and LOST_SOURCES_DOMAIN not in csv.text and "s0.example.org" in csv.text
    facets = client.get("/api/sources/facets")
    assert facets.status_code == 200, facets.text
    assert "lost" not in facets.text, "the facets count the stand-in source's name or tags"


def test_the_facets_do_not_count_a_stand_in_source_that_carries_facet_values(client):
    """The stand-in a salvage writes has no language, country, type or tags today, so the facets could not show it anyway; the gate is for
    the day it does (a copy that gave it a default type, an edit by hand): the facets count real sources only."""
    from src.api.main import app
    from src.database.models import Source
    from src.database.session import get_db

    before = client.get("/api/sources/facets").json()
    session = next(app.dependency_overrides[get_db]())
    try:
        row = session.query(Source).filter(Source.domain == LOST_SOURCES_DOMAIN).one()
        row.language, row.country, row.source_type, row.tags = "xx", "ZZ", "lostkind", "losttag"
        session.commit()
    finally:
        session.close()
    after = client.get("/api/sources/facets").json()
    assert after == before, "a stand-in source carrying facet values was counted by the facets"
    assert "lostkind" not in str(after) and "losttag" not in str(after)
    assert before["types"] == [{"key": "news", "n": 12}], before  # positive control: the real sources are counted


def _give_the_stand_in_what_its_kept_children_leave_behind(session) -> int:
    """The kept children of a lost source (a group membership, a metadata row) and the values a copy or an edit could give its stand-in: a
    group of one real source and the stand-in, metadata for both, a tag, a country and a region on the stand-in. Returns the group's id."""
    from src.database.models import Source, SourceGroup, SourceMetadata

    lost = session.query(Source).filter(Source.domain == LOST_SOURCES_DOMAIN).one()
    real = session.query(Source).filter(Source.id == 1).one()
    group = SourceGroup(name="g1")
    session.add(group)
    session.flush()
    group.sources.append(real)
    group.sources.append(lost)
    session.add(SourceMetadata(source_id=lost.id, language="xx", country="zz", robots_allowed=True))
    session.add(SourceMetadata(source_id=real.id, language="en", country="fr", robots_allowed=True))
    lost.tags, real.tags = "losttag", "realtag"
    lost.country, lost.region = "zz", "lostregion"
    session.commit()
    return int(group.id)


def _api_session(client):
    """A session on the very store the client reads (the dependency override the fixture installed)."""
    from src.api.main import app
    from src.database.session import get_db

    return next(app.dependency_overrides[get_db]())


def test_the_source_manager_leaves_the_stand_in_out_of_every_reader_the_counts_and_the_export(db, tmp_path):
    from src.database.models import Source
    from src.database.source_manager import SourceManager

    gid = _give_the_stand_in_what_its_kept_children_leave_behind(db)
    with SourceManager(session=db) as m:
        assert len(m.get_all_sources()) == 12 and all(s.domain != LOST_SOURCES_DOMAIN for s in m.get_all_sources())
        assert [s.id for s in m.get_sources_by_tags(["realtag"])] == [1]  # the positive control: the same call finds a real source
        assert [s.id for s in m.get_sources_by_tags(["realtag"], match_all=True)] == [1]  # the positive control of the match-all branch
        assert m.get_sources_by_tags(["losttag"]) == [] and m.get_sources_by_tags(["losttag"], match_all=True) == []
        assert [s.id for s in m.get_sources_by_group(gid)] == [1] and [s.id for s in m.get_sources_by_group_name("g1")] == [1]
        assert [s.id for s in m.get_sources_by_country("FR")] == [1] and m.get_sources_by_country("zz") == []
        assert m.get_sources_by_language("xx") == [] and [s.id for s in m.get_sources_by_language("en")] == [1]
        assert [s.id for s in m.get_sources_robots_allowed(True)] == [1]
        assert m.get_source_by_id(1) is not None and m.get_source_by_id(13) is None
        assert m.get_metadata(1) is not None and m.get_metadata(13) is None
        stats = m.get_source_statistics()
        # 12 real sources and the stand-in (not enabled): the stand-in would be a 13th source, a disabled one, a tag, a metadata row
        assert stats["total_sources"] == 12 and stats["disabled_sources"] == 0 and stats["enabled_sources"] == 12, stats
        assert "losttag" not in stats["tag_counts"] and stats["tag_counts"] == {"realtag": 1}, stats
        assert stats["with_metadata"] == 1 and stats["with_country"] == 1 and stats["with_language"] == 1, stats
        out = tmp_path / "sources.yml"
        assert m.export_sources_to_yaml(str(out)) == 12 and "(lost" not in out.read_text(encoding="utf-8")
        assert m.export_sources_to_yaml(str(out), group_id=gid) == 1
        # a bulk change by group never enables, or changes, the stand-in
        assert m.enable_groups([gid]) == 1 and m.disable_groups([gid]) == 1
        assert m.set_group_priority([gid], 3) == 1 and m.set_group_rate_limit([gid], 5000) == 1
    assert db.query(Source).filter(Source.domain == LOST_SOURCES_DOMAIN).one().enabled in (0, False)


def test_a_source_is_not_found_by_the_id_of_the_stand_in_in_any_of_its_routes(client):
    _give_the_stand_in_what_its_kept_children_leave_behind(_api_session(client))
    for suffix in ("", "/metadata", "/observed-ips", "/provenance", "/citation-tally"):
        lost = client.get(f"/api/sources/13{suffix}")
        assert lost.status_code == 404, (suffix, lost.status_code, lost.text)
        real = client.get(f"/api/sources/1{suffix}")  # the positive control: the same route answers for a real source
        assert real.status_code == 200, (suffix, real.status_code, real.text)


def _give_real_articles_to_the_stand_in_source(session, ids=(2, 3, 4)) -> int:
    """Real articles kept for the lost source (the stand-in owns them, so deleting it would cascade to them). Returns how many articles the
    stand-in source owns now: the stand-in article beside the ones given."""
    from src.database.models import Article

    session.query(Article).filter(Article.id.in_(ids)).update({"source_id": 13}, synchronize_session=False)
    session.commit()
    return _owned_by_the_stand_in_source(session)


def _owned_by_the_stand_in_source(session) -> int:
    from src.database.models import Article

    session.expire_all()
    return session.query(Article).filter(Article.source_id == 13).count()


def test_a_source_is_not_updated_or_deleted_by_the_id_of_the_stand_in_and_the_articles_kept_for_it_stay(client):
    """PUT and DELETE start from ``get_source_by_id``, as the readers do. A delete of the stand-in would cascade to the real articles kept for
    the lost source (``articles.source_id`` is ``ON DELETE CASCADE``), which is the damage a place-holder must never do."""
    from src.database.models import Source

    session = _api_session(client)
    owned = _give_real_articles_to_the_stand_in_source(session)
    assert owned == 4  # the stand-in article and the three real ones
    stand_in_row = session.query(Source).filter(Source.id == 13).one()
    before = (stand_in_row.name, stand_in_row.domain, stand_in_row.enabled, stand_in_row.priority)
    put = client.put("/api/sources/13", json={"name": "renamed", "enabled": True, "priority": 3})
    assert put.status_code == 404, put.text
    gone = client.delete("/api/sources/13")
    assert gone.status_code == 404, gone.text
    session.expire_all()
    row = session.query(Source).filter(Source.id == 13).one()
    assert (row.name, row.domain, row.enabled, row.priority) == before, "a write reached the stand-in"
    assert _owned_by_the_stand_in_source(session) == owned, "articles kept for the lost source were deleted with it"
    # the twin: the same two routes answer for a real source
    real = client.put("/api/sources/1", json={"priority": 3})
    assert real.status_code == 200, real.text
    session.expire_all()
    assert session.query(Source).filter(Source.id == 1).one().priority == 3
    session.add(Source(name="twin", domain="twin.example.org"))
    session.commit()
    twin = session.query(Source).filter(Source.domain == "twin.example.org").one().id
    assert client.delete(f"/api/sources/{twin}").status_code == 200
    session.expire_all()
    assert session.query(Source).filter(Source.id == twin).count() == 0


def test_a_source_gets_no_metadata_and_is_put_in_no_group_by_the_id_of_the_stand_in(client):
    from sqlalchemy import select

    from src.database.models import SourceGroup, SourceMetadata, source_group_association

    session = _api_session(client)
    gid = _give_the_stand_in_what_its_kept_children_leave_behind(session)
    other = SourceGroup(name="g2")
    session.add(other)
    session.commit()
    gid2 = int(other.id)

    def groups_of(source_id):
        session.expire_all()
        return sorted(session.execute(select(source_group_association.c.group_id).where(source_group_association.c.source_id == source_id)).scalars())

    def metadata_of(source_id):
        session.expire_all()
        row = session.query(SourceMetadata).filter(SourceMetadata.source_id == source_id).first()
        return None if row is None else row.language

    assert groups_of(13) == [gid] and metadata_of(13) == "xx"  # what the stand-in keeps
    assert client.post("/api/sources/13/metadata", json={"language": "fr"}).status_code == 404
    assert client.put("/api/sources/13/metadata", json={"language": "fr"}).status_code == 404
    assert client.delete("/api/sources/13/metadata").status_code == 404
    assert metadata_of(13) == "xx", "a metadata write reached the stand-in"
    assert client.post("/api/sources/13/groups", json=[gid2]).status_code == 404
    assert client.request("DELETE", "/api/sources/13/groups", json=[gid]).status_code == 404
    assert groups_of(13) == [gid], "a group change reached the stand-in"
    # the twins: the same routes answer for a real source
    assert client.put("/api/sources/1/metadata", json={"language": "de"}).status_code == 200 and metadata_of(1) == "de"
    assert client.post("/api/sources/2/metadata", json={"language": "en"}).status_code == 200 and metadata_of(2) == "en"
    assert client.post("/api/sources/1/groups", json=[gid2]).json() == {"message": "Added source 1 to 1 groups"}
    assert groups_of(1) == [gid, gid2]
    assert client.request("DELETE", "/api/sources/1/groups", json=[gid2]).json() == {"message": "Removed source 1 from 1 groups"}
    assert groups_of(1) == [gid]
    assert client.delete("/api/sources/1/metadata").status_code == 200 and metadata_of(1) is None


def test_the_manager_puts_the_stand_in_in_no_group_and_takes_it_out_of_none(db):
    """The routes check the source before they call the manager; the manager refuses it on its own as well (a caller that is not the route)."""
    from sqlalchemy import select

    from src.database.models import SourceGroup, source_group_association
    from src.database.source_manager import SourceManager

    gid = _give_the_stand_in_what_its_kept_children_leave_behind(db)
    other = SourceGroup(name="g2")
    db.add(other)
    db.commit()
    gid2 = int(other.id)

    def groups_of(source_id):
        db.expire_all()
        return sorted(db.execute(select(source_group_association.c.group_id).where(source_group_association.c.source_id == source_id)).scalars())

    with SourceManager(session=db) as m:
        assert m.add_source_to_groups(13, [gid2]) == 0 and m.remove_source_from_groups(13, [gid]) == 0
        assert m.get_source_groups(13) == []  # the groups the stand-in was kept in are not listed for it
        assert groups_of(13) == [gid], "a group change reached the stand-in"
        assert m.add_source_to_groups(1, [gid2]) == 1  # the twins: the same calls act on a real source
        assert sorted(g.id for g in m.get_source_groups(1)) == [gid, gid2]
        assert m.remove_source_from_groups(1, [gid2]) == 1


def test_no_ingest_route_takes_the_stand_in_source_for_a_source(client):
    from src.api.ingestion import get_fetcher
    from src.api.main import app

    class _MustNotFetch:
        def __getattr__(self, name):
            raise AssertionError(f"the fetcher was used ({name}) for a source that is not one")

    app.dependency_overrides[get_fetcher] = lambda: _MustNotFetch()
    mailbox = {"host": "imap.invalid", "user": "u", "password": "x"}
    assert client.post("/api/sources/13/ingest").status_code == 404
    assert client.post("/api/ingest", json={"source_id": 13, "url": "https://e.org/x"}).status_code == 404
    assert client.post("/api/sources/13/ingest-email", json=mailbox).status_code == 404
    batch = client.post("/api/sources/ingest-batch", json={"source_ids": [13, 1]}).json()
    assert [(r["source_id"], r["status"]) for r in batch["results"]] == [(13, "not_found"), (1, "no_feed")], batch
    # the twin: the lookup finds a real source, which has no feed to read (so the route answers before any fetch)
    real = client.post("/api/sources/1/ingest")
    assert real.status_code == 400 and "no rss_url" in real.text, real.text


def test_the_id_list_writers_never_write_to_the_stand_in_and_do_not_count_it(db):
    from src.database.models import Source
    from src.database.source_manager import SourceManager

    ids = [1, 13]
    with SourceManager(session=db) as m:
        assert m.enable_sources(ids) == 1 and m.disable_sources(ids) == 1 and m.enable_sources(ids) == 1  # the real source only
        assert m.set_source_priority(ids, 3) == 1 and m.set_source_rate_limit(ids, 7000) == 1
        assert m.add_tags_to_sources(ids, ["newtag"]) == 1 and m.remove_tags_from_sources(ids, ["newtag"]) == 1
        assert m.add_tags_to_sources(ids, ["newtag"]) == 1
    db.expire_all()
    lost = db.query(Source).filter(Source.id == 13).one()
    assert lost.enabled in (0, False) and lost.priority != 3 and lost.rate_limit_ms != 7000 and not lost.tags, (lost.enabled, lost.priority, lost.rate_limit_ms, lost.tags)
    real = db.query(Source).filter(Source.id == 1).one()  # the positive control: the same calls changed the real source
    assert real.enabled and real.priority == 3 and real.rate_limit_ms == 7000 and real.tags == "newtag", (real.enabled, real.priority, real.rate_limit_ms, real.tags)


def test_the_batch_routes_say_they_changed_the_real_source_only(client):
    from src.database.models import Source

    session = _api_session(client)
    assert client.post("/api/sources/batch/enable", json=[1, 13]).json() == {"message": "Enabled 1 sources"}
    assert client.post("/api/sources/batch/disable", json=[1, 13]).json() == {"message": "Disabled 1 sources"}
    assert client.post("/api/sources/batch/priority", params={"priority": 3}, json=[1, 13]).json() == {"message": "Set priority 3 for 1 sources"}
    added = client.post("/api/sources/batch/tags/add", json={"source_ids": [1, 13], "tags": ["t"]})
    assert added.json() == {"message": "Added tags ['t'] to 1 sources"}, added.text
    removed = client.post("/api/sources/batch/tags/remove", json={"source_ids": [1, 13], "tags": ["t"]})
    assert removed.json() == {"message": "Removed tags ['t'] from 1 sources"}, removed.text
    session.expire_all()
    assert session.query(Source).filter(Source.id == 13).one().enabled in (0, False)


def test_an_admission_kept_for_the_stand_in_cannot_be_undone_and_is_listed_as_gone(db):
    """The undo writes ``enabled`` back to the value the event replaced: for a stand-in whose kept event says True, that would turn it ON for
    collection. The stand-in is given the state that makes the undo otherwise allowed (qualified, enabled), so only the gate refuses it."""
    from datetime import datetime

    from src.catalog.qualification import AdmissionUndoRefused, admission_audit, undo_admission
    from src.database.models import Source, SourceAdmissionEvent

    now = datetime(2026, 10, 7, 12, 0, 0)
    for sid in (1, 13):
        row = db.query(Source).filter(Source.id == sid).one()
        row.status, row.enabled = "qualified", True
        db.add(SourceAdmissionEvent(source_id=sid, occurred_at=now, verdict="qualified", criteria_version="v", prior_enabled=False, prior_status="unqualified"))
    db.commit()
    events = {e["source_id"]: e for e in admission_audit(db)["events"]}
    assert events[13]["reversible"] is False and events[13]["blocked_by"] == "source-no-longer-exists" and events[13]["name"] == "", events[13]
    assert events[1]["reversible"] is True and events[1]["blocked_by"] is None, events[1]  # the positive control: a real source's admission is reversible
    stand_in_event = db.query(SourceAdmissionEvent).filter(SourceAdmissionEvent.source_id == 13).one()
    with pytest.raises(AdmissionUndoRefused, match="no longer exists"):
        undo_admission(db, int(stand_in_event.id), now=now)
    db.expire_all()
    assert db.query(Source).filter(Source.id == 13).one().enabled is True and stand_in_event.undone_at is None  # nothing was written
    real_event = db.query(SourceAdmissionEvent).filter(SourceAdmissionEvent.source_id == 1).one()
    undo_admission(db, int(real_event.id), now=now)
    db.expire_all()
    assert db.query(Source).filter(Source.id == 1).one().enabled is False  # the same call undid the real one


def test_the_groups_count_and_list_real_sources_only(client):
    gid = _give_the_stand_in_what_its_kept_children_leave_behind(_api_session(client))
    listed = client.get("/api/sources/groups/").json()
    assert [g["source_count"] for g in listed if g["id"] == gid] == [1], listed
    one = client.get(f"/api/sources/groups/{gid}").json()
    assert one["source_count"] == 1 and [s["id"] for s in one["sources"]] == [1], one


def test_the_catalogue_total_counts_the_rows_it_lists_and_no_stand_in(client):
    listed = client.get("/api/catalog/sources", params={"limit": 1000}).json()
    assert listed["total"] == 12 and len(listed["sources"]) == 12, listed["total"]
    # the stand-in is the one source that is not enabled: the filter that asks for exactly that finds none
    assert client.get("/api/catalog/sources", params={"enabled": "false"}).json()["total"] == 0
    assert client.get("/api/catalog/sources", params={"q": "lost"}).json()["total"] == 0


def test_the_advanced_search_facets_offer_no_stand_in_source_country_or_region(client):
    _give_the_stand_in_what_its_kept_children_leave_behind(_api_session(client))
    facets = client.get("/api/search/facets").json()
    assert len(facets["sources"]) == 12 and all(s["domain"] != LOST_SOURCES_DOMAIN and s["id"] != 13 for s in facets["sources"]), facets["sources"]
    assert "zz" not in [c["code"] for c in facets["countries"]] and "lostregion" not in str(facets["regions"]), (facets["countries"], facets["regions"])
    assert any(r["region"] == "global" for r in facets["regions"]), facets["regions"]  # the positive control: the real sources' region is offered


# --------------------------------------------------------------------------- #
#  the signed outputs
# --------------------------------------------------------------------------- #
def _bundle_ids(response) -> list[int]:
    assert response.status_code == 200, response.text
    return [int(i["id"]) for i in response.json()["manifest"]["items"]]


def test_a_signed_evidence_bundle_never_holds_the_stand_in_by_id_or_by_query(client):
    assert _bundle_ids(client.post("/api/reports/evidence", json={"article_ids": [1, STAND_IN_ARTICLE]})) == [1]  # the control: the real one is there
    assert client.post("/api/reports/evidence", json={"article_ids": [STAND_IN_ARTICLE]}).status_code == 404
    # a field filter finds the stand-in by its address while nothing excludes it: the query path must not reach it
    assert client.post("/api/reports/evidence", json={"query": "url:lost"}).status_code == 404


def test_the_evidence_plan_and_the_methods_appendix_never_count_or_list_the_stand_in(client, salvaged):
    plan = client.post("/api/reports/evidence/plan", json={"article_ids": [1, STAND_IN_ARTICLE]}).json()
    assert plan["articles"] == 1 and plan["sources"] == 1, plan
    assert client.post("/api/reports/evidence/plan", json={"article_ids": [STAND_IN_ARTICLE]}).status_code == 404
    assert client.post("/api/reports/evidence/plan", json={"query": "url:lost"}).status_code == 404
    methods = client.post("/api/reports/methods", json={"article_ids": [1, STAND_IN_ARTICLE], "include_bundle": True})
    assert methods.status_code == 200, methods.text
    out = methods.json()
    assert out["article_count"] == 1 and "lost articles" not in out["markdown"], out["article_count"]
    assert [int(i["id"]) for i in out["bundle"]["manifest"]["items"]] == [1]
    # the corpus total the appendix states is the real articles: the stand-in is no article of the corpus
    assert f"**Corpus at generation time:** {_real_articles(salvaged)} stored articles" in out["markdown"], out["markdown"]
    assert client.post("/api/reports/methods", json={"query": "url:lost"}).status_code == 404


def test_each_selection_of_a_signed_output_asks_the_search_for_articles_that_are_not_quarantined_and_drops_a_stand_in_it_is_handed(client, monkeypatch):
    """Two layers, each checked alone: the search is asked to leave out quarantined articles, and a stand-in id the search hands over
    anyway is left out by the article query."""
    import src.api.reporting as reporting

    seen: list[object] = []

    def handing_over_the_stand_in(db, query, *a, **kw):
        seen.append(kw.get("exclude_quarantined"))
        return [1, STAND_IN_ARTICLE]

    monkeypatch.setattr(reporting, "search_ids", handing_over_the_stand_in)
    assert _bundle_ids(client.post("/api/reports/evidence", json={"query": "anything"})) == [1]
    assert client.post("/api/reports/evidence/plan", json={"query": "anything"}).json()["articles"] == 1
    methods = client.post("/api/reports/methods", json={"query": "anything"}).json()
    assert methods["article_count"] == 1
    assert seen == [True, True, True], seen


def test_the_reader_answers_the_stand_in_article_as_not_found(client):
    assert client.get(f"/api/articles/{STAND_IN_ARTICLE}/view").status_code == 404
    assert client.get("/api/articles/1/view").status_code == 200  # the positive control: the reader answers for a real article


STAND_IN_MARKER = "zzzqq"  # a word only the stand-in's text carries, so a prompt that holds it was built from the stand-in


class _FakeLlm:
    """Stands in for the local model: offline, and it keeps every prompt it was handed so a test can say what the model never saw."""

    base_url = "http://127.0.0.1:11434"

    def __init__(self):
        self.prompts: list[str] = []

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        from src.llm.ollama import GenerationResult

        self.prompts.append(prompt)
        return GenerationResult(model=model, text="FAKE")


def _give_articles_what_a_stand_in_could_carry(session, ids=(1, STAND_IN_ARTICLE)) -> None:
    """Text, a title and the kept children of an article (a summary, an AI keyword, a date tag) on each of ``ids``: the stand-in a salvage
    copy writes has none of them today (its text is NULL, so an AI call would refuse it for having no text, whatever the gate does), and the
    gate is for the day a copy or an edit gives it some. Article 1 is the positive control: the same routes answer for it."""
    from datetime import UTC, date, datetime

    from src.database.models import AiKeyword, Article, ArticleAnalysis, ArticleMentionedDate

    for aid in ids:
        art = session.get(Article, aid)
        marker = STAND_IN_MARKER if aid == STAND_IN_ARTICLE else "realword"
        art.content, art.title, art.language = f"On 5 March 2026 the ministry said {marker} was kept.", "A title", "en"
        session.add(ArticleAnalysis(article_id=aid, kind="summary", result="r", model="m", prompt_version="v", created_at=datetime.now(UTC)))
        session.add(AiKeyword(article_id=aid, term="kept term", kind="keyword", model="m"))
        session.add(ArticleMentionedDate(article_id=aid, mentioned_on=date(2026, 3, 5), precision="day", snippet="5 March 2026", confidence=0.9))
    session.commit()


@pytest.fixture()
def fake_llm():
    from src.api.llm import get_llm_client, get_llm_client_with_name
    from src.api.main import app

    fake = _FakeLlm()
    app.dependency_overrides[get_llm_client] = lambda: fake
    app.dependency_overrides[get_llm_client_with_name] = lambda: ("ollama", fake)
    yield fake
    app.dependency_overrides.pop(get_llm_client, None)
    app.dependency_overrides.pop(get_llm_client_with_name, None)


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("POST", "/api/llm/articles/{}/summarize", {"model": "m"}),
        ("POST", "/api/llm/articles/{}/translate", {"model": "m", "target_language": "French"}),
        ("GET", "/api/llm/articles/{}/analyses", None),
        ("GET", "/api/ai/articles/{}/keywords", None),
        ("GET", "/api/article-dates/article/{}", None),
        ("POST", "/api/article-dates/article/{}", None),
        ("GET", "/api/insights/subjectivity?article_id={}", None),
    ],
    ids=["summarize", "translate", "analyses", "ai-keywords", "date-tags", "extract-dates", "subjectivity"],
)
def test_an_article_by_id_route_answers_the_stand_in_as_not_found(client, fake_llm, method, path, body):
    _give_articles_what_a_stand_in_could_carry(_api_session(client))
    lost = client.request(method, path.format(STAND_IN_ARTICLE), json=body)
    assert lost.status_code == 404, (lost.status_code, lost.text)
    assert STAND_IN_MARKER not in lost.text
    assert all(STAND_IN_MARKER not in p for p in fake_llm.prompts), "the model was handed the stand-in's text"
    real = client.request(method, path.format(1), json=body)  # the positive control: the same route answers for a real article
    assert real.status_code == 200, (real.status_code, real.text)


def _make_article_2_a_link_list(session) -> None:
    """Article 2 is quarantined for what it is (a link list), with the text and kept children a stand-in could carry: a real row that is not a
    stand-in, so a gate that read ``quarantined`` instead of the stand-in's own reason would turn it into a not-found."""
    from src.database.models import Article

    _give_articles_what_a_stand_in_could_carry(session, ids=(1, 2))
    row = session.get(Article, 2)
    row.quarantined, row.quarantine_reason = True, "link list"
    session.commit()


def test_an_article_the_app_judged_not_an_article_is_still_reached_by_its_id_in_every_gate_that_leaves_the_stand_in_out(client, db, fake_llm, monkeypatch):
    """Only the stand-in is refused: an article that was quarantined for what it is (a link list) is a real row, and an explicit id reaches it
    (the reader and the explicit id sets of the signed outputs do the same). Every gate of the by-id routes and the id sets is asked here, so
    none of them can read ``quarantined`` instead of the stand-in's own reason and still pass."""
    import json

    from src.api.ai import _resolve_work

    session = _api_session(client)
    _make_article_2_a_link_list(session)
    _make_article_2_a_link_list(db)
    for method, path, body in [
        ("POST", "/api/llm/articles/{}/summarize", {"model": "m"}),
        ("POST", "/api/llm/articles/{}/translate", {"model": "m", "target_language": "French"}),
        ("GET", "/api/llm/articles/{}/analyses", None),
        ("GET", "/api/ai/articles/{}/keywords", None),
        ("GET", "/api/article-dates/article/{}", None),
        ("POST", "/api/article-dates/article/{}", None),
        ("GET", "/api/insights/subjectivity?article_id={}", None),
    ]:
        reached = client.request(method, path.format(2), json=body)
        assert reached.status_code == 200, (method, path, reached.status_code, reached.text)
    synth = client.post("/api/llm/synthesize", json={"article_ids": [2]})
    assert synth.status_code == 200 and [m["id"] for m in synth.json()["members"]] == [2], synth.text
    monkeypatch.setattr("src.database.session.SessionLocal", lambda: _api_session(client))  # the bulk run writes through its own session
    run = client.post("/api/llm/bulk", json={"op": "summarize", "model": "m", "article_ids": [2], "skip_existing": False})
    assert run.status_code == 200, run.text
    items = [json.loads(line) for line in run.text.splitlines() if line.strip()]
    assert [i["article_id"] for i in items if i.get("event") == "item"] == [2], items
    work = _resolve_work(db, article_ids=[2], query=None, source=None, language=None, start_date=None, end_date=None, cap=None)
    assert [w.article_id for w in work] == [2], work
    # the date lists and the id set of the corpus analyses reach it too
    assert [a["article_id"] for a in client.get("/api/article-dates/by-date", params={"date": "2026-03-05"}).json()["articles"]] == [1, 2]
    facets = client.get("/api/insights/corpus-source-language-facets", params={"article_ids": "2"}).json()
    assert facets["corpus_n"] == 1 and facets["corpus_total"] == 1, facets
    link = client.get("/api/links/articles-by-link", params={"url": "https://l.example/2"}).json()
    assert [a["id"] for a in link["articles"]] == [2], link
    # and so does the agenda's deduced-events layer: a date two articles mention, one of them a link list, is still an event of the two
    from datetime import date

    from src.timemap import datestore

    agenda = datestore.upcoming_deduced(db, today=date(2026, 3, 1), min_articles=2)["events"]
    assert [(e["date"], e["n_articles"], e["n_sources"], e["article_ids"]) for e in agenda] == [("2026-03-05", 2, 2, [1, 2])], agenda


def test_the_kept_children_of_the_stand_in_are_not_listed_by_the_routes_that_read_them_by_the_stand_ins_id(client, fake_llm):
    """The summary, the AI keyword and the date tag the stand-in kept are in the tables (nothing is deleted), and the routes that list them
    by the article's id answer a real article's and no stand-in's."""
    _give_articles_what_a_stand_in_could_carry(_api_session(client))
    assert client.get("/api/llm/articles/1/analyses").json()["count"] == 1
    assert [k["term"] for k in client.get("/api/ai/articles/1/keywords").json()["keywords"]] == ["kept term"]
    assert [t["date"] for t in client.get("/api/article-dates/article/1").json()["tags"]] == ["2026-03-05"]
    for path in ("/api/llm/articles/{}/analyses", "/api/ai/articles/{}/keywords", "/api/article-dates/article/{}"):
        lost = client.get(path.format(STAND_IN_ARTICLE))
        assert lost.status_code == 404 and "kept term" not in lost.text and "2026-03-05" not in lost.text, (path, lost.text)


def test_an_explicit_id_set_handed_to_the_synthesis_the_bulk_run_and_the_keyword_extraction_never_reaches_the_stand_in(client, db, fake_llm, monkeypatch):
    import json

    from fastapi import HTTPException

    from src.api.ai import _resolve_work

    _give_articles_what_a_stand_in_could_carry(_api_session(client))
    both = client.post("/api/llm/synthesize", json={"article_ids": [STAND_IN_ARTICLE, 1]})
    assert both.status_code == 200, both.text
    assert [m["id"] for m in both.json()["members"]] == [1], both.json()["members"]  # the stand-in is no member of the synthesis
    only = client.post("/api/llm/synthesize", json={"article_ids": [STAND_IN_ARTICLE]})
    assert only.status_code == 404, only.text
    monkeypatch.setattr("src.database.session.SessionLocal", lambda: _api_session(client))  # the bulk run writes through its own session
    run = client.post("/api/llm/bulk", json={"op": "summarize", "model": "m", "article_ids": [STAND_IN_ARTICLE, 1], "skip_existing": False})
    assert run.status_code == 200, run.text
    items = [json.loads(line) for line in run.text.splitlines() if line.strip()]
    assert [i["article_id"] for i in items if i.get("event") == "item"] == [1], items
    assert fake_llm.prompts and all(STAND_IN_MARKER not in p for p in fake_llm.prompts), "the model was handed the stand-in's text"
    assert any("realword" in p for p in fake_llm.prompts)  # the positive control: the real article's text did reach the model
    # the keyword extraction's own selection (a database session on a copy of the store: the same rows)
    _give_articles_what_a_stand_in_could_carry(db)
    work = _resolve_work(db, article_ids=[STAND_IN_ARTICLE, 1], query=None, source=None, language=None, start_date=None, end_date=None, cap=None)
    assert [w.article_id for w in work] == [1], work
    with pytest.raises(HTTPException) as refused:
        _resolve_work(db, article_ids=[STAND_IN_ARTICLE], query=None, source=None, language=None, start_date=None, end_date=None, cap=None)
    assert refused.value.status_code == 404


@pytest.fixture()
def similarity_client(client, monkeypatch):
    """The article-similarity router, mounted in an app of its own on the same store: the main app mounts it only with the ``[analysis]`` extra,
    and the analyzer needs scikit-learn, so the comparison itself is stood in for (the gate under test is the route's own, not the analyzer's)."""
    from fastapi import FastAPI

    from src.api import keyword_analysis
    from src.api.main import app as main_app
    from src.api.ratelimit import limiter
    from src.database.session import get_db

    monkeypatch.setattr(keyword_analysis.article_intelligence_analyzer, "calculate_similarity", lambda a, b, method="cosine": 0.5)
    mini = FastAPI()
    mini.state.limiter = limiter
    mini.include_router(keyword_analysis.router)
    mini.dependency_overrides[get_db] = main_app.dependency_overrides[get_db]
    with TestClient(mini) as c:
        yield c


def test_the_article_similarity_route_answers_the_stand_in_as_not_found_in_either_position(client, similarity_client):
    from src.database.models import Article

    session = _api_session(client)
    _give_articles_what_a_stand_in_could_carry(session, ids=(1, 2, STAND_IN_ARTICLE))
    url = "/api/analysis/articles/similarity"
    for first, second in ((STAND_IN_ARTICLE, 1), (1, STAND_IN_ARTICLE), (STAND_IN_ARTICLE, STAND_IN_ARTICLE)):
        lost = similarity_client.post(url, params={"article_id1": first, "article_id2": second})
        assert lost.status_code == 404, (first, second, lost.status_code, lost.text)
    real = similarity_client.post(url, params={"article_id1": 1, "article_id2": 2})  # the positive control: two real articles are compared
    assert real.status_code == 200 and "similarity" in real.json(), real.text
    row = session.get(Article, 2)  # an article quarantined for what it is (a link list) is a real row, and is compared in either position
    row.quarantined, row.quarantine_reason = True, "link list"
    session.commit()
    for first, second in ((2, 1), (1, 2)):
        kept = similarity_client.post(url, params={"article_id1": first, "article_id2": second})
        assert kept.status_code == 200, (first, second, kept.status_code, kept.text)


def _keep_the_keyword_mentions_of(session, article_ids) -> None:
    """One keyword that each of ``article_ids`` mentions (the rows a lost article's mentions leave in the table, whose parent is the stand-in)."""
    from src.database.models import Keyword, KeywordMention

    kw = Keyword(term="sharedterm", normalized_term="sharedterm", language="en")
    session.add(kw)
    session.flush()
    for aid in article_ids:
        session.add(KeywordMention(keyword_id=kw.id, article_id=aid, count=1))
    session.commit()


def test_the_readers_related_list_and_near_copies_never_offer_the_stand_in_whose_keyword_mentions_were_kept(client):
    from src.database.models import Article

    session = _api_session(client)
    _give_articles_what_a_stand_in_could_carry(session, ids=(1, 2, STAND_IN_ARTICLE))
    session.get(Article, STAND_IN_ARTICLE).content = session.get(Article, 1).content  # a text that is a copy of article 1's, so the copy check would group it
    session.commit()
    _keep_the_keyword_mentions_of(session, (1, 2, STAND_IN_ARTICLE))
    page = client.get("/api/articles/1/view")
    assert page.status_code == 200
    stand_in_link = f"/api/articles/{STAND_IN_ARTICLE}/view"
    related = page.text.split("Related in your corpus", 1)[1]
    assert "/api/articles/2/view" in related.split("</section>", 1)[0], "the positive control: a real article that shares the keyword is related"
    assert stand_in_link not in page.text, "the stand-in is offered as a related article or as a copy"
    assert 'class="dup-badge"' in page.text and "/api/articles/2/view" in page.text.split('class="dup-badge"', 1)[1], "the positive control: the real copy is named"


def test_the_date_lists_and_the_agendas_deduced_events_never_hold_the_stand_in_whose_date_tag_was_kept(client, db):
    """The date tag a stand-in kept is in the table (nothing is deleted); the lists that join it to its article would show the stand-in as an
    article that mentions the date, count it in the agenda's articles and sources, and put its number in the set the agenda opens."""
    from datetime import date

    from src.database.models import Article
    from src.timemap import datestore

    _give_articles_what_a_stand_in_could_carry(_api_session(client), ids=(1, 2, STAND_IN_ARTICLE))
    listed = client.get("/api/article-dates/by-date", params={"date": "2026-03-05"}).json()
    assert [a["article_id"] for a in listed["articles"]] == [1, 2] and listed["count"] == 2, listed  # the real articles; not 1500
    assert STAND_IN_MARKER not in str(listed)

    _give_articles_what_a_stand_in_could_carry(db, ids=(1, 2, STAND_IN_ARTICLE))
    today = date(2026, 3, 1)
    real_sources = {db.get(Article, i).source_id for i in (1, 2)}
    assert len(real_sources) == 2  # two articles of two sources: the stand-in's source would make it three
    pair = datestore.upcoming_deduced(db, today=today, min_articles=2)["events"]
    assert [(e["date"], e["n_articles"], e["n_sources"], sorted(e["article_ids"])) for e in pair] == [("2026-03-05", 2, 2, [1, 2])], pair  # the positive control
    # a date only the real article 1 and the stand-in mention: the stand-in cannot make it a pair
    db.query(datestore.ArticleMentionedDate).filter(datestore.ArticleMentionedDate.article_id == 2).delete()
    db.commit()
    assert datestore.upcoming_deduced(db, today=today, min_articles=2)["events"] == []
    alone = datestore.upcoming_deduced(db, today=today, min_articles=1)["events"]
    assert alone == [{"date": "2026-03-05", "n_articles": 1, "n_sources": 1, "article_ids": [1]}], alone


def test_an_explicit_id_set_of_the_corpus_analyses_never_holds_the_stand_in_nor_its_lost_source(client):
    """``_resolve_corpus`` feeds the corpus-* analyses, the link graph and the source coverage: the stand-in is dropped from a set it is named
    in (before the cap and the total), so the "(lost sources N)" row never shows in the coverage of the sources of the set."""
    named = f"1,{STAND_IN_ARTICLE},2"
    facets = client.get("/api/insights/corpus-source-language-facets", params={"article_ids": named}).json()
    assert facets["corpus_n"] == 2 and facets["corpus_total"] == 2, facets
    assert [f["domain"] for f in facets["sources"]] == ["s0.example.org", "s1.example.org"], facets  # the two real articles' sources, no "(lost sources 13)"
    only = client.get("/api/insights/corpus-source-language-facets", params={"article_ids": str(STAND_IN_ARTICLE)}).json()
    assert only["corpus_n"] == 0 and only["corpus_total"] == 0 and only["sources"] == [], only
    twin = client.get("/api/insights/corpus-source-language-facets", params={"article_ids": "1,2"}).json()  # the positive control
    assert twin["corpus_n"] == 2 and twin["corpus_total"] == 2 and twin["sources"] == facets["sources"], twin
    coverage = client.get("/api/insights/corpus-sources", params={"article_ids": named}).json()
    assert coverage["count"] == 2 and sorted(c["domain"] for c in coverage["sources"]) == ["s0.example.org", "s1.example.org"], coverage
    links = client.get("/api/links/corpus", params={"article_ids": named}).json()
    assert links["n_articles"] == 2 and links["total_matched"] == 2, links


def test_the_hash_range_finds_the_stand_in_a_salvage_copy_wrote_and_no_real_quarantined_article(db):
    """The helper reads the mark through the hash index (the placeholder text IS the stand-in's hash): it finds what the copy wrote, never an
    article the app only judged not to be one, and it names the same articles as the reason the copy also wrote."""
    from src.database.models import Article

    assert stand_in.stand_in_article_ids(db) == {STAND_IN_ARTICLE}
    real = db.get(Article, 3)
    real.quarantined, real.quarantine_reason = True, "judged not an article"
    db.commit()
    assert stand_in.stand_in_article_ids(db) == {STAND_IN_ARTICLE}, "a real quarantined article is found as a stand-in"
    by_reason = {int(i) for (i,) in db.query(Article.id).filter(~stand_in.not_a_stand_in_article())}
    assert by_reason == stand_in.stand_in_article_ids(db) == {STAND_IN_ARTICLE}
    assert db.get(Article, STAND_IN_ARTICLE).hash == stand_in.lost_text("articles", STAND_IN_ARTICLE)


def test_the_hash_range_holds_every_placeholder_text_of_the_articles_table_and_no_hex_digest():
    assert stand_in.ARTICLE_HASH_END == stand_in.ARTICLE_HASH_PREFIX + ":" and ord(":") == ord("9") + 1
    for row_id in (0, 1, 9, 10, 99, 1500, 123456789, 99999999999999999999):
        text = stand_in.lost_text("articles", row_id)
        assert text.startswith(stand_in.ARTICLE_HASH_PREFIX)
        assert stand_in.ARTICLE_HASH_PREFIX <= text < stand_in.ARTICLE_HASH_END, text
    for outside in ("0" * 64, "f" * 64, "(lost sources 13)", "(lost articles", "(lost articles :", "(lost articles ;"):
        assert not (stand_in.ARTICLE_HASH_PREFIX <= outside < stand_in.ARTICLE_HASH_END), outside


def test_the_condition_for_a_child_table_leaves_out_the_stand_ins_rows_and_keeps_a_row_that_names_no_article(db):
    """``child.article_id NOT IN (the stand-in ids)`` without a join: the kept links of the stand-in go, the rows of real articles stay, and
    a child row whose column is NULL names no article and stays."""
    from sqlalchemy import column, select, table, text

    from src.database.models import ArticleLink

    kept = db.query(ArticleLink).filter(stand_in.not_a_stand_in_article_id(ArticleLink.article_id)).count()
    assert kept == 1499 and db.query(ArticleLink).count() == 1500
    assert db.query(ArticleLink).filter(ArticleLink.article_id == STAND_IN_ARTICLE, stand_in.not_a_stand_in_article_id(ArticleLink.article_id)).count() == 0
    db.execute(text("CREATE TEMP TABLE kept_rows (article_id INTEGER)"))
    db.execute(text("INSERT INTO kept_rows VALUES (1), (NULL), (:lost)"), {"lost": STAND_IN_ARTICLE})
    rows = table("kept_rows", column("article_id"))
    left = [r[0] for r in db.execute(select(rows.c.article_id).where(stand_in.not_a_stand_in_article_id(rows.c.article_id)).order_by(rows.c.article_id))]
    assert left == [None, 1], left


def _plan(db, statement) -> list[str]:
    from sqlalchemy import text

    sql = str(statement.compile(dialect=db.get_bind().dialect, compile_kwargs={"literal_binds": True}))
    return [str(r[-1]) for r in db.execute(text("EXPLAIN QUERY PLAN " + sql))]


def test_both_forms_of_the_helper_seek_the_hash_index_and_read_no_article_row(db):
    """The point of the range is the plan: a SEARCH on the unique hash index, covering (the id is the row id), for the enumerator and for the
    condition inside a child scan, never a scan of ``articles``, a lookup of an article row, or a join to it (which reads whole rows)."""
    from sqlalchemy import func, select, text

    from src.database.models import ArticleLink

    plans = {
        "the enumerator": _plan(db, stand_in._stand_in_article_id_select()),
        "the child condition": _plan(db, select(func.count()).select_from(ArticleLink).where(stand_in.not_a_stand_in_article_id(ArticleLink.article_id))),
    }
    for form, plan in plans.items():
        about_articles = [line for line in plan if "articles" in line and "article_links" not in line]
        assert about_articles == ["SEARCH articles USING COVERING INDEX idx_article_hash (hash>? AND hash<?)"], (form, plan)
        assert not any("SCAN articles" in line or "PRIMARY KEY" in line for line in plan), (form, plan)
    for decoy in ("hash LIKE '(lost articles %'", "substr(hash, 1, 15) = '(lost articles '"):  # why the helper is a range: neither of these seeks the index
        decoy_plan = [str(r[-1]) for r in db.execute(text(f"EXPLAIN QUERY PLAN SELECT id FROM articles WHERE {decoy}"))]
        assert not any("SEARCH articles USING COVERING INDEX idx_article_hash" in line for line in decoy_plan), (decoy, decoy_plan)


def test_the_python_reading_of_the_stand_in_source_mark_agrees_with_the_sql_condition_on_every_source(db):
    from src.database.models import Source

    by_sql = {s.id for s in db.query(Source).filter(~stand_in.not_a_stand_in_source())}
    by_row = {s.id for s in db.query(Source).all() if stand_in.is_a_stand_in_source(s)}
    assert by_sql == by_row == {13}


def test_the_articles_that_cite_a_link_never_list_the_stand_in_whose_links_were_kept(client):
    """``article_links`` rows are kept for a lost article, so the lookup by link found the stand-in and listed it as an article that cites it,
    counted it, and named its source."""
    lost = client.get("/api/links/articles-by-link", params={"url": f"https://l.example/{STAND_IN_ARTICLE}"})
    assert lost.status_code == 200 and lost.json()["count"] == 0 and lost.json()["articles"] == [], lost.text
    real = client.get("/api/links/articles-by-link", params={"url": "https://l.example/1"}).json()  # the positive control
    assert real["count"] == 1 and [a["id"] for a in real["articles"]] == [1], real
    by_domain = client.get("/api/links/articles-by-link", params={"domain": "l.example", "limit": 3}).json()
    assert by_domain["count"] == 1499 and STAND_IN_ARTICLE not in [a["id"] for a in by_domain["articles"]], by_domain["count"]


def test_a_newsletter_is_never_filed_under_the_stand_in_a_kept_mapping_points_at(db, monkeypatch):
    """The import files a newsletter under the source its publisher resolves to. A resolution that names the stand-in (the id a kept mapping
    carries) would hide the newsletter from every reader that leaves the stand-in out, so it stays in the bucket as a refused attach."""
    from src.database.models import Article
    from src.ingest import newsletter_source as ns
    from src.ingest.email import ingest_emails

    def _eml(subject: str, mid: str) -> bytes:
        return (
            "From: Publisher <news@fresh.example>\n"
            f"Subject: {subject}\nMessage-ID: <{mid}>\nDate: Mon, 05 Jan 2026 18:00:00 +0000\n"
            "Content-Type: text/plain; charset=utf-8\n\n"
            f"A newsletter body about {subject} with enough ordinary sentences in it that the importer treats it as real prose rather than an empty shell.\n"
        ).encode()

    def _points_at(source_id: int):
        return lambda session, from_addr, list_id=None, *, list_id_parsed=None: ns.Resolution(
            "attach-exact", "fresh.example", "etld1", "a kept mapping", source_id=source_id, source_name="n", source_domain="d"
        )

    bucket = db.get(__import__("src.database.models", fromlist=["Source"]).Source, 1)
    monkeypatch.setattr(ns, "resolve_newsletter_publisher", _points_at(13))
    tally = ingest_emails(db, bucket, [_eml("Lost target", "l1@x")])
    assert tally["stored"] == 1 and tally["attach_refused"] == 1 and tally["attached_existing"] == 0, tally
    stored = db.query(Article).filter(Article.title == "Lost target").one()
    assert stored.source_id == 1 and stored.newsletter_attached_via is None, (stored.source_id, stored.newsletter_attached_via)
    assert db.query(Article).filter(Article.source_id == 13).count() == 1  # only the stand-in article itself is under the stand-in source
    monkeypatch.setattr(ns, "resolve_newsletter_publisher", _points_at(2))  # the positive control: a real target is used
    tally = ingest_emails(db, bucket, [_eml("Real target", "r1@x")])
    assert tally["attached_existing"] == 1 and tally["attach_refused"] == 0, tally
    placed = db.query(Article).filter(Article.title == "Real target").one()
    assert placed.source_id == 2 and placed.newsletter_attached_via == "attach-exact:etld1", (placed.source_id, placed.newsletter_attached_via)


def test_the_qualification_integrity_report_and_repair_never_judge_or_rewrite_the_stand_in(db):
    """A judging attempt kept for the stand-in disagrees with its status, as one kept for a real source can: the repair would write the
    stand-in's status, and the report would name it as an inversion. Both read one candidate join, so both leave it out."""
    from datetime import datetime

    from src.catalog.qualification_integrity import (
        qualification_integrity_report,
        repair_inversions,
    )
    from src.database.models import Source, SourceQualificationAttempt

    when = datetime(2026, 10, 7, 12, 0, 0)
    for sid in (1, 13):
        db.add(SourceQualificationAttempt(source_id=sid, attempted_at=when, verdict="qualified", criteria_version="v"))
    db.commit()
    report = qualification_integrity_report(db)
    assert report["inversions_total"] == 1 and [d["domain"] for d in report["demoted"]] == ["s0.example.org"], report["demoted"]  # the real source only
    planned = repair_inversions(db, dry_run=True)
    assert planned["reconciled_total"] == 1 and [r["domain"] for r in planned["restored_to_qualified"]] == ["s0.example.org"], planned
    applied = repair_inversions(db, dry_run=False)
    assert applied["reconciled_total"] == 1, applied
    db.expire_all()
    lost = db.query(Source).filter(Source.id == 13).one()
    assert lost.status == "unqualified" and lost.qualified_at is None, (lost.status, lost.qualified_at)
    assert db.query(Source).filter(Source.id == 1).one().status == "qualified"  # the positive control: the same repair restored the real source


def test_the_integrity_report_and_the_repair_read_one_candidate_join():
    """The two were verbatim copies of one join: a gate added to one would leave the other naming (or fixing) what the first leaves out."""
    import inspect

    from src.catalog import qualification_integrity as qi

    for fn in (qi.qualification_integrity_report, qi.repair_inversions):
        body = inspect.getsource(fn)
        assert "_inversion_candidates(session)" in body, fn.__name__
        assert "newest_at" not in body, f"{fn.__name__} holds a copy of the candidate join"
    assert "not_a_stand_in_source()" in inspect.getsource(qi._inversion_candidates)


def test_the_archive_backfill_queue_skips_the_stand_in_whether_it_is_queued_or_already_active(db, tmp_path):
    from src.ingest import clear_kill_switch
    from src.ingest.archive_backfill import advance_backfill, enqueue_source, load_state

    seen: list[str] = []

    def discover(fetcher, source, *, full_history):
        seen.append(source.domain)
        return ["https://x.example/a"]

    def ingest(session, source, url, *, fetcher):
        seen.append(f"ingest {source.domain}")
        raise AssertionError("a stand-in was fetched for")

    clear_kill_switch()
    try:
        queued = tmp_path / "queued.json"
        enqueue_source(13, state_path=queued)
        out = advance_backfill(db, fetcher=object(), per_pass=5, state_path=queued, ingest_fn=ingest, discover_fn=discover)
        assert out["skipped"] == "source no longer exists" and out["source_id"] == 13, out
        assert load_state(queued)["queue"] == [] and seen == []  # nothing was enumerated for it
        active = tmp_path / "active.json"
        active.write_text('{"active": {"source_id": 13, "urls": ["https://x.example/a"], "cursor": 0, "full_history": false, "tally": {}}}', encoding="utf-8")
        out = advance_backfill(db, fetcher=object(), per_pass=5, state_path=active, ingest_fn=ingest, discover_fn=discover)
        assert out["skipped"] == "source no longer exists" and out["done"] is True and seen == [], (out, seen)
        assert load_state(active)["active"] is None
        # the positive control: a real source in the same queue is enumerated
        real = tmp_path / "real.json"
        enqueue_source(1, state_path=real)
        out = advance_backfill(db, fetcher=object(), per_pass=5, state_path=real, ingest_fn=ingest, discover_fn=discover)
        assert out["enumerated"] is True and seen == ["s0.example.org"], (out, seen)
    finally:
        clear_kill_switch()


def test_the_source_routes_the_id_route_used_to_shadow_answer_over_http_and_leave_the_stand_in_out(client):
    """``/api/sources/export``, ``/stats`` and ``/search`` answered 422 to every call (``/api/sources/{source_id}`` was declared above them
    and matched their last segment as an id), so their gates could only be tested below the route; they are reached now."""
    gid = _give_the_stand_in_what_its_kept_children_leave_behind(_api_session(client))
    exported = client.get("/api/sources/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["count"] == 12 and "(lost" not in exported.text and "s0.example.org" in exported.text
    by_group = client.get("/api/sources/export", params={"group_id": gid})
    assert by_group.status_code == 200 and [s["domain"] for s in by_group.json()["sources"]] == ["s0.example.org"], by_group.text
    stats = client.get("/api/sources/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["sources"]["total"] == 12 and body["sources"]["disabled"] == 0 and body["sources"]["enabled"] == 12, body
    assert "losttag" not in body["sources"]["tag_counts"] and body["sources"]["tag_counts"] == {"realtag": 1}, body
    assert body["metadata"] == {"with_metadata": 1, "with_country": 1, "with_language": 1}, body
    found = client.get("/api/sources/search", params={"query": "lost"})
    assert found.status_code == 200 and found.json()["results"] == [] and found.json()["count"] == 0, found.text
    assert found.json()["total"] == 0
    tagged = client.get("/api/sources/search", params={"query": "losttag"})
    assert tagged.status_code == 200 and tagged.json()["count"] == 0, tagged.text
    real = client.get("/api/sources/search", params={"query": "realtag"})  # the positive control: the same search finds a real source
    assert real.status_code == 200 and [r["id"] for r in real.json()["results"]] == [1], real.text
    assert client.get("/api/sources/1").status_code == 200  # the id route still answers for an id
    assert [client.request(m, "/api/sources/abc").status_code for m in ("GET", "PUT", "DELETE")] == [404, 404, 404]  # a segment that is no id and no literal is no route, for every method
    assert [client.request(m, "/api/sources/export").status_code for m in ("PUT", "DELETE")] == [405, 405]  # a literal name answers 405 to a method the literal does not declare


def test_the_source_search_counts_every_match_and_bounds_its_page(client):
    from src.database.models import Source

    session = _api_session(client)
    for sid in (1, 2, 3, 4, 5):
        session.get(Source, sid).tags = "paged"
    session.commit()
    page = client.get("/api/sources/search", params={"query": "paged", "limit": 2, "offset": 1})
    body = page.json()
    assert page.status_code == 200 and body["count"] == 2 and body["total"] == 5, body  # five matched; the page carries two
    assert len({r["id"] for r in body["results"]} & {1, 2, 3, 4, 5}) == 2
    last = client.get("/api/sources/search", params={"query": "paged", "limit": 2, "offset": 4}).json()
    assert last["count"] == 1 and last["total"] == 5, last
    past = client.get("/api/sources/search", params={"query": "paged", "limit": 2, "offset": 9}).json()
    assert past["count"] == 0 and past["total"] == 5, past  # a page past the end still says how many matched
    for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
        assert client.get("/api/sources/search", params={"query": "paged", **params}).status_code == 422, params


def test_no_literal_route_of_the_source_router_is_shadowed_by_another_route_declared_above_it():
    """The cause of the three routes above, as a rule for the whole router: for every route with a literal path, the first route (in
    declaration order) that matches that path for that method is the route itself. Anchored to the router's own routes, never the app's
    shared ones."""
    from starlette.routing import Match

    from src.api.source_management import router

    def first(path, method):
        scope = {"type": "http", "path": path, "method": method, "root_path": ""}
        return next((r for r in router.routes if r.matches(scope)[0] == Match.FULL), None)

    literal = [r for r in router.routes if "{" not in r.path]
    assert len(literal) > 20, "the router lost its literal routes"
    shadowed = [(m, r.path, getattr(first(r.path, m), "path", None)) for r in literal for m in sorted(r.methods or ()) if m != "HEAD" and first(r.path, m) is not r]
    assert shadowed == [], shadowed


def test_the_claim_trail_bundle_never_carries_a_stand_in_article_it_is_handed(db, tmp_path, monkeypatch):
    """The claims trail-bundle is built from explicit article ids. The workspace the route builds comes from the search, which leaves
    quarantined articles out, so a stand-in reaches the bundle only by an id it is handed; the by-id load leaves it out of the article
    files, the README's count and the privacy member, and its text out of the signed ZIP."""
    import copy
    import io
    import zipfile

    from src.analytics import claim_bundle as cb
    from src.analytics import claim_workspace as cw
    from src.custody.signing import HybridSigner

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    _give_articles_what_a_stand_in_could_carry(db)
    ws = cw.build_workspace(db, "ministry realword")
    assert [a["id"] for a in ws["related"]["articles"]] == [1], ws["related"]["articles"]  # the search itself leaves the stand-in out
    handed = copy.deepcopy(ws)
    handed["related"]["articles"].append({"id": STAND_IN_ARTICLE})
    signer = HybridSigner(tmp_path / "k" / "ed.pem", tmp_path / "k" / "ml.key", use_pqc=False)
    data, report = cb.build_trail_bundle(db, handed, signer=signer)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        text = "".join(zf.read(n).decode("utf-8", "replace") for n in names)
    assert "articles/1.json" in names and "realword" in text  # the positive control: a real article is carried
    assert f"articles/{STAND_IN_ARTICLE}.json" not in names, names
    assert STAND_IN_MARKER not in text, "the stand-in's text is in the signed ZIP"


def test_the_omnibar_finds_no_stand_in_source_by_its_name(client):
    def sources(q):
        groups = client.get("/api/search/omni", params={"q": q}).json()["groups"]
        return next(g for g in groups if g["kind"] == "sources")

    assert sources("lost")["total"] == 0 and sources("lost")["items"] == [], sources("lost")
    assert sources("s0.example")["total"] >= 1  # the positive control: the same box finds a real source


def test_the_source_counts_do_not_count_the_stand_in_source(client):
    counts = client.get("/api/sources/qualification/config").json()["counts"]
    # 12 real sources, all 'unqualified' on a fresh store: the stand-in would make it 13
    assert counts["unqualified"] == 12, counts
    assert sum(counts[k] for k in ("qualified", "disqualified", "unqualified")) == 12, counts


def test_the_qualification_passes_and_their_counts_leave_the_stand_in_source_out(db):
    from src.catalog.qualification import select_unqualified
    from src.catalog.qualify_job import initial_backlog_estimate

    picked = select_unqualified(db, limit=100)
    assert len(picked) == 12, [s.domain for s in picked]
    assert all(s.domain != LOST_SOURCES_DOMAIN for s in picked)
    assert initial_backlog_estimate(db)["unqualified"] == 12


def test_the_qualification_queue_view_counts_real_sources_only(db):
    from src.catalog.qualification import qualification_queue

    new = qualification_queue(db)["new"]
    # 12 real sources, none judged or tried: the stand-in would make it 13 (and the next list would name it)
    assert new["total"] == 12 and new["untried"] == 12, new
    assert LOST_SOURCES_DOMAIN not in new["next"], new["next"]


def test_the_stand_in_source_is_never_collected_even_if_it_were_marked_qualified(db):
    from src.database.models import Source
    from src.scheduler.runner import select_sources
    from src.scheduler.settings import SchedulerSettings

    db.query(Source).update({"status": "qualified", "enabled": True}, synchronize_session=False)
    db.query(Source).filter(Source.domain == LOST_SOURCES_DOMAIN).update({"status": "qualified", "enabled": False}, synchronize_session=False)
    db.commit()
    chosen = select_sources(db, SchedulerSettings()).all()
    assert len(chosen) == 12 and all(s.domain != LOST_SOURCES_DOMAIN for s in chosen), [s.domain for s in chosen]


# --------------------------------------------------------------------------- #
#  what the rows kept for a lost parent show
# --------------------------------------------------------------------------- #
def test_the_real_articles_kept_for_a_lost_source_stay_in_the_list_and_name_the_lost_source(tmp_path):
    """The stand-in is not shown as a source of its own, but a REAL article kept for the lost source is still the user's: it stays in the list."""
    from src.api.main import app
    from src.database.session import get_db

    root = tmp_path
    pristine = root / "pristine.db"
    H.build_app_store(pristine, articles=300, sources=12)
    con = sqlite3.connect(pristine)
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("DELETE FROM sources WHERE id = 12")  # its articles are kept, their source is lost
    con.commit()
    kept = con.execute("SELECT count(*) FROM articles WHERE source_id = 12").fetchone()[0]
    con.close()
    assert kept > 0
    out = root / "out.db"
    report = Salvage(pristine, out).run()
    assert report["stand_ins"] == {"sources": 12}, report.get("stand_ins")
    engine = create_engine(f"sqlite:///{out}", future=True, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, future=True)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            rows = c.get("/api/articles", params={"limit": 500}).json()["results"]
            assert len([r for r in rows if "(lost sources 12)" in str(r.get("source", ""))]) == kept, "the kept articles are not in the list"
            assert all(s["domain"] != "(lost sources 12)" for s in c.get("/api/sources").json())
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# --------------------------------------------------------------------------- #
#  E3 fold 9: the source writers and lists the fold 7 sweep had not reached
# --------------------------------------------------------------------------- #
def test_the_manager_puts_many_sources_in_one_group_without_the_stand_in_and_takes_it_out_of_none(db):
    """The id-list twins of ``add_source_to_groups``: one group, many sources. The stand-in is neither added to the group nor removed from it."""
    from sqlalchemy import select

    from src.database.models import source_group_association
    from src.database.source_manager import SourceManager

    gid = _give_the_stand_in_what_its_kept_children_leave_behind(db)  # a group of source 1 and the stand-in

    def members(group_id):
        db.expire_all()
        return sorted(db.execute(select(source_group_association.c.source_id).where(source_group_association.c.group_id == group_id)).scalars())

    with SourceManager(session=db) as m:
        other = m.create_group("g2")
        assert m.add_sources_to_group(other.id, [1, 13]) == 1 and members(other.id) == [1], "the stand-in was put in a group"
        assert m.remove_sources_from_group(gid, [13]) == 0 and members(gid) == [1, 13], "the stand-in was taken out of a group"
        assert m.remove_sources_from_group(gid, [1]) == 1 and members(gid) == [13]  # the twin: the same call acts on a real source


def test_the_feed_discovery_never_probes_for_the_stand_in_in_either_branch(db, monkeypatch):
    """Its "domain" is the text ``(lost sources N)``: a request would be made for https://(lost sources N). Asked by id and asked for every
    source without a feed, no probe is built for it."""
    from src.database.source_manager import SourceManager

    asked: list[list[int]] = []

    def fake_find(sources, timeout=10):
        asked.append(sorted(s["id"] for s in sources))
        return []

    monkeypatch.setattr("src.database.source_manager.DuckDuckGoSearch.find_missing_rss_feeds", staticmethod(fake_find))
    with SourceManager(session=db) as m:
        m.discover_rss_feeds([1, 13])
        m.discover_rss_feeds()
    assert asked == [[1], list(range(1, 13))], asked  # by id: the real source only; for all: the twelve real sources, never 13


def test_a_market_rule_is_not_created_for_the_stand_in_source(client):
    body = {"symbol": "AAA", "url": "https://s0.example.org/p", "selector": ".p"}
    lost = client.post("/api/markets/rules", json={**body, "source_id": 13})
    assert lost.status_code == 404, (lost.status_code, lost.text)
    real = client.post("/api/markets/rules", json={**body, "source_id": 1})  # the positive control
    assert real.status_code == 200, (real.status_code, real.text)
    assert [r["source_id"] for r in client.get("/api/markets/rules").json()["rules"]] == [1]


def test_the_qualification_assist_run_answers_the_stand_in_as_not_found_and_runs_nothing_for_it(client, monkeypatch):
    """The id comes from the body, not the path, so it is a by-id route all the same: no run is made, no proposals artifact is written."""
    ran: list[int] = []

    def fake_run(session, source_id, client=None, *, model=None, max_articles=20):
        ran.append(source_id)
        return {"source_id": source_id, "proposals": []}

    monkeypatch.setattr("src.ai_layer.qualification_assist.run_and_persist_qualification_assist", fake_run)
    lost = client.post("/api/diagnostics/qualification-assist/run", json={"source_id": 13})
    assert lost.status_code == 404 and ran == [], (lost.status_code, lost.text, ran)
    real = client.post("/api/diagnostics/qualification-assist/run", json={"source_id": 1})  # the positive control
    assert real.status_code == 200 and ran == [1], (real.status_code, real.text, ran)


def test_the_wikidata_type_pass_looks_up_no_name_for_the_stand_in_and_writes_no_type_on_it(db, monkeypatch):
    """The stand-in has no source type, which is what the pass looks for, and its name is the placeholder: a lookup (a network request) by that
    name is pointless, and a type written onto it would make it look like a reconciled source."""
    from src.catalog import wikidata_apply

    monkeypatch.setattr(wikidata_apply, "kill_switch_active", lambda: False)
    asked: list[str] = []

    class _Empty:
        def json(self):
            return {}

    def getter(url):
        asked.append(url)
        return _Empty()

    wikidata_apply.apply_source_types(db, limit=50, get=getter)
    assert asked, "the positive control: the real sources were looked up"
    assert not any("lost" in u for u in asked), [u for u in asked if "lost" in u]


def test_the_topic_tags_are_proposed_for_and_written_onto_real_sources_only(db, monkeypatch):
    """``source_topic_candidates`` (decide), the shared-session fallback and ``apply_source_topics`` (apply) each leave the stand-in out."""
    from src.analytics import source_topics
    from src.database.models import Source

    monkeypatch.setattr(source_topics, "derive_source_topics", lambda session, **kw: [
        {"domain": "s0.example.org", "topics": ["politics"]},
        {"domain": "(lost sources 13)", "topics": ["politics"]},
    ])
    decided = source_topics.source_topic_candidates(db)
    assert decided == {"candidates": [{"id": 1, "topics": ["politics"]}]}, decided
    shared = source_topics._apply_source_topics_on_a_shared_session(db, min_articles=1, top_n=4)
    assert shared["sources_updated"] == 1, shared
    db.rollback()
    db.expire_all()
    assert (db.get(Source, 13).tags or "") == "" and "politics" in (db.get(Source, 1).tags or "")
    db.get(Source, 1).tags = None
    db.commit()
    # the apply phase re-reads each candidate row: a stand-in handed over by the decide phase is skipped there too
    monkeypatch.setattr(source_topics, "source_topic_candidates", lambda session, **kw: {"candidates": [{"id": 13, "topics": ["politics"]}, {"id": 1, "topics": ["politics"]}]})
    applied = source_topics.apply_source_topics(db, min_articles=1, top_n=4)
    assert applied["sources_updated"] == 1, applied
    db.expire_all()
    assert (db.get(Source, 13).tags or "") == "" and "politics" in (db.get(Source, 1).tags or "")


def test_the_two_source_diagnostics_leave_the_stand_in_out_of_their_lists(client):
    observed = client.get("/api/sources/official-instruments").json()
    assert 1 in [r["source_id"] for r in observed["sources"]] and 13 not in [r["source_id"] for r in observed["sources"]], observed
    audit = client.get("/api/sources/country-domain-audit").json()
    assert audit["examined"] == 12, audit  # the twelve real sources; the stand-in is not examined


def test_the_tag_proposals_never_offer_the_stand_in_source_whatever_mentions_were_kept_for_it(db):
    """Mentions carry the source id of their article, so the stand-in source (which owns real articles kept for a lost source) has mentions and
    an article count; it would be proposed for tagging, and the tags applied onto it."""
    from datetime import UTC, datetime

    from src.ai_layer.source_tags import select_source_tag_candidates
    from src.database.models import Keyword, KeywordMention

    kw = Keyword(term="housing", normalized_term="housing", language="en")
    db.add(kw)
    db.flush()
    for aid, sid in ((1, 1), (2, 13), (3, 13), (4, 13)):
        db.add(KeywordMention(keyword_id=kw.id, article_id=aid, count=3, observed_on=datetime.now(UTC).date(), source_id=sid, language="en"))
    db.commit()
    items, skipped = select_source_tag_candidates(db, min_articles=1, min_mentions=1)[:2]
    domains = [i.domain for i in items] + [s.domain for s in skipped]
    assert "s0.example.org" in domains, domains  # the positive control: the real source is visited
    assert not any("lost" in d for d in domains), domains


# --------------------------------------------------------------------------- #
#  E3 fold 9: a row kept for a lost article never makes a stand-in an article, a source or an independent outlet
#
#  A salvage copy keeps the child rows of an article it could not read (its links, its date tags, its places, its entities, its keyword
#  mentions) and writes ONE stand-in article at the lost id so those rows still name a row. A reader that goes from such a kept row to "an
#  article", to "the article's source" or to a count of articles must leave the stand-in out, or a placeholder (whose source is a placeholder
#  too) is listed, ranked, promoted, or counted as an independent outlet. Each reader is asked twice, on the real salvage copy above (article
#  1500 is the stand-in, under the stand-in source 13): once with ONE real article and the stand-in (the placeholder would make the pair, and
#  the reader must see one article), and once with two real articles (the positive control), so a reader that stopped answering cannot pass for
#  one that leaves the stand-in out. The condition is asked on the CHILD row (``stand_in.not_a_stand_in_article_id``), never through a join.
# --------------------------------------------------------------------------- #
LOST_SOURCE = 13
DAY = date(2026, 3, 5)


def _links(session, article_ids, normalized, *, link_type="external") -> None:
    from src.database.models import ArticleLink

    for aid in article_ids:
        session.add(ArticleLink(article_id=aid, url=f"https://{normalized}", normalized_url=normalized, link_type=link_type))
    session.commit()


def _places_and_dates(session, article_ids, *, place="Paris", country="fr", kind="city", on=DAY) -> None:
    """A place tag and a date tag for each article (a date tag an article already has is left as it is: they are unique per day)."""
    from src.database.models import ArticleMentionedDate, ArticleMentionedPlace

    for aid in article_ids:
        session.add(ArticleMentionedPlace(article_id=aid, name=place, country=country, kind=kind, mentions=1))
        if not session.query(ArticleMentionedDate).filter_by(article_id=aid, mentioned_on=on, precision="day").first():
            session.add(ArticleMentionedDate(article_id=aid, mentioned_on=on, precision="day", snippet="5 March 2026", confidence=0.9))
    session.commit()


# --------------------------------------------------------------------------- #
#  the readers of the links kept for a lost article
# --------------------------------------------------------------------------- #
def test_a_domain_cited_by_one_real_article_and_the_stand_in_is_cited_by_one_outlet_not_two(db):
    """``cited_domain_stats`` counts the DISTINCT sources that cite a domain, and promotion needs two: the stand-in's placeholder source would be the
    second, and ``promote_cited_sources`` would register a new source from one real outlet and a placeholder."""
    from src.database.models import Source
    from src.discovery.cited_sources import cited_domain_stats, promote_cited_sources

    _links(db, [1, STAND_IN_ARTICLE], "cited.example/story")
    stats = cited_domain_stats(db)["cited.example"]
    assert stats["sources"] == {1} and stats["articles"] == {1}, stats
    plan = promote_cited_sources(db, min_source_citers=2, dry_run=True)
    assert "cited.example" not in [c["domain"] for c in plan["candidates"]], plan
    before = db.query(Source).count()
    promote_cited_sources(db, min_source_citers=2)
    db.commit()
    assert db.query(Source).filter(Source.domain == "cited.example").count() == 0 and db.query(Source).count() == before


def test_a_domain_cited_by_two_real_articles_of_two_sources_is_promoted(db):
    from src.database.models import Source
    from src.discovery.cited_sources import cited_domain_stats, promote_cited_sources

    _links(db, [1, 2], "cited.example/story")
    assert cited_domain_stats(db)["cited.example"]["sources"] == {1, 2}
    plan = promote_cited_sources(db, min_source_citers=2, dry_run=True)
    assert [c["domain"] for c in plan["candidates"] if c["domain"] == "cited.example"] == ["cited.example"], plan
    promote_cited_sources(db, min_source_citers=2)
    db.commit()
    assert db.query(Source).filter(Source.domain == "cited.example").count() == 1


def test_the_citation_channel_never_counts_the_stand_in_toward_a_domains_citations(db):
    from src.discovery.channels import citation_candidates

    _links(db, [1, STAND_IN_ARTICLE], "candidate.example/a")
    _links(db, [1, 2], "candidate.example/b")
    out = citation_candidates(db, cap=50, min_citations=2, budget_s=0)
    by_domain = {d["domain"]: d for d in out["decisions"]} if "decisions" in out else {}
    assert by_domain, out  # the positive control: the real pair is a candidate
    assert by_domain["candidate.example"]["evidence"]["distinct_citing_articles"] == 2, by_domain["candidate.example"]
    _links(db, [1, STAND_IN_ARTICLE], "lonely.example/a")
    again = citation_candidates(db, cap=50, min_citations=2, budget_s=0)
    assert "lonely.example" not in [d["domain"] for d in again["decisions"]], again


def test_the_first_article_that_cited_a_domain_is_never_the_stand_in_whose_date_sorts_first(db):
    """The stand-in has no creation date, which sorts first: it would be named as the real source's "first article that cited" the domain, and
    counted in ``distinct_citing_articles``."""
    from src.discovery.source_trail import _first_citing_article

    _links(db, [1, STAND_IN_ARTICLE], "trail.example/x")
    first = _first_citing_article(db, "trail.example")
    assert first is not None and first["article_id"] == 1 and first["distinct_citing_articles"] == 1, first
    assert first["citing_source_name"] == "s0"
    _links(db, [2], "trail.example/y")
    both = _first_citing_article(db, "trail.example")
    assert both is not None and both["distinct_citing_articles"] == 2 and both["article_id"] in (1, 2), both
    _links(db, [STAND_IN_ARTICLE], "only-lost.example/z")
    assert _first_citing_article(db, "only-lost.example") is None  # nothing but the stand-in cites it: nothing real does


def test_an_origin_cited_by_one_real_article_and_the_stand_in_is_no_laundering_cluster(db):
    """``find_source_laundering`` is the apparent corroboration that is not: an origin cited by many DISTINCT sources. One real source plus the
    stand-in's placeholder source passed the gate, and the card named "(lost sources 13)"."""
    from src.analytics.laundering import find_source_laundering

    _links(db, [1, STAND_IN_ARTICLE], "origin.example/report")
    assert find_source_laundering(db, min_sources=2, min_articles=2)["clusters"] == []
    _links(db, [1, 2], "origin2.example/report")
    found = find_source_laundering(db, min_sources=2, min_articles=2)["clusters"]
    assert [c["origin"] for c in found] == ["origin2.example/report"], found
    assert found[0]["article_ids"] == [1, 2] and found[0]["source_names"] == ["s0", "s1"], found
    # A cluster that passes on its real articles alone, which the stand-in also cites: the counts and the member list are two reads of the child
    # rows, and each hides the other (the counts still pass whether or not the list is cleaned, and the list is whatever the counts selected).
    _links(db, [1, 2, STAND_IN_ARTICLE], "origin3.example/report")
    third = [c for c in find_source_laundering(db, min_sources=2, min_articles=2)["clusters"] if c["origin"] == "origin3.example/report"]
    assert len(third) == 1 and (third[0]["n_articles"], third[0]["distinct_sources"]) == (2, 2), third
    assert third[0]["article_ids"] == [1, 2] and third[0]["source_names"] == ["s0", "s1"], third


def _graph(client, **params) -> dict:
    response = client.get("/api/links/export.json", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_the_citation_graph_export_never_holds_the_stand_in_and_min_citations_counts_real_articles_only(client):
    """The pairs of the export come from ``article_links`` alone, so the links kept for the stand-in were nodes and edges of the graph, and the
    stand-in counted toward a domain's ``min_citations``."""
    session = _api_session(client)
    _links(session, [1, 2, STAND_IN_ARTICLE], "graph.example/page")
    graph = _graph(client, min_citations=1)
    ids = {n["id"] for n in graph["nodes"]}
    assert {"a:1", "a:2", "d:graph.example"} <= ids, ids  # the positive control: the real articles and their domain are in the graph
    assert f"a:{STAND_IN_ARTICLE}" not in ids, "the stand-in is a node of the citation graph"
    assert all(e["source"] != f"a:{STAND_IN_ARTICLE}" for e in graph["edges"])
    ml = client.get("/api/links/export.graphml", params={"min_citations": 1})
    assert ml.status_code == 200 and 'id="a:1"' in ml.text and f'id="a:{STAND_IN_ARTICLE}"' not in ml.text
    # a domain only the stand-in cites is no node at all, and one real article beside the stand-in is ONE citation
    _links(session, [STAND_IN_ARTICLE], "ghost.example/page")
    _links(session, [1], "ghost.example/page2")
    nodes = {n["id"] for n in _graph(client, min_citations=2)["nodes"]}
    assert "d:graph.example" in nodes, nodes
    assert "d:ghost.example" not in nodes, "min_citations counted the stand-in as a second citing article"
    assert "d:ghost.example" in {n["id"] for n in _graph(client, min_citations=1)["nodes"]}  # one real citer is still a node


def test_the_link_preview_never_lists_or_counts_the_stand_in_as_an_article_that_cites_the_link(client):
    session = _api_session(client)
    _links(session, [1, STAND_IN_ARTICLE], "preview.example/page")
    lost = client.get("/api/links/preview", params={"url": "https://preview.example/page"})
    assert lost.status_code == 200, lost.text
    body = lost.json()
    assert body["cited_by_articles"] == 1 and [c["article_id"] for c in body["citing_examples"]] == [1], body
    _links(session, [2], "preview.example/page")
    both = client.get("/api/links/preview", params={"url": "https://preview.example/page"}).json()
    assert both["cited_by_articles"] == 2 and [c["article_id"] for c in both["citing_examples"]] == [1, 2], both
    only_lost = client.get("/api/links/preview", params={"url": f"https://l.example/{STAND_IN_ARTICLE}"}).json()
    assert only_lost["cited_by_articles"] == 0 and only_lost["citing_examples"] == [], only_lost


# --------------------------------------------------------------------------- #
#  the readers of the places, dates and entities kept for a lost article
# --------------------------------------------------------------------------- #
def test_one_real_article_and_the_stand_in_are_no_convergence_in_space_and_time(db):
    """``find_convergences`` gates a span on distinct SOURCES: the stand-in's placeholder source made one real source pass, and the card said
    "(lost sources 13)"."""
    from src.analytics.convergence import find_convergences

    _places_and_dates(db, [1, STAND_IN_ARTICLE])
    none = find_convergences(db, min_articles=2, min_sources=2, today=date(2026, 3, 6))
    assert none["clusters"] == [], none
    _places_and_dates(db, [2, 1], place="Lyon")  # the positive control: two real articles of two sources are a convergence
    found = find_convergences(db, min_articles=2, min_sources=2, today=date(2026, 3, 6))
    assert [(c["place"], c["article_ids"], c["distinct_sources"], c["source_names"]) for c in found["clusters"]] == [("Lyon", [1, 2], 2, ["s0", "s1"])], found
    assert "(lost sources" not in str(found["clusters"]), found


def test_the_place_card_counts_and_lists_real_articles_only(db):
    from types import SimpleNamespace

    from src.entities.places import mention_article_ids, mention_count

    _places_and_dates(db, [1, 2, STAND_IN_ARTICLE], place="Paris", country="fr", kind="city")
    place = SimpleNamespace(name="Paris", country="fr")
    assert mention_count(db, place) == 2
    assert mention_article_ids(db, place) == ([1, 2], 2)
    alone = SimpleNamespace(name="Atlantis", country="xx")
    _places_and_dates(db, [STAND_IN_ARTICLE], place="Atlantis", country="xx", kind="city")
    assert mention_count(db, alone) == 0 and mention_article_ids(db, alone) == ([], 0)


def test_the_promised_dates_that_have_arrived_never_name_the_stand_in(db):
    """A stand-in carries no publication date today; the card is for the day a copy or an edit gives it one."""
    from datetime import UTC, datetime, timedelta

    from src.briefing.recipes import promises_due
    from src.database.models import Article, ArticleMentionedDate

    today = datetime.now(UTC).date()
    for aid in (1, STAND_IN_ARTICLE):
        db.get(Article, aid).published_at = datetime(2020, 1, 1)
        db.add(ArticleMentionedDate(article_id=aid, mentioned_on=today - timedelta(days=1), precision="day", snippet="x", confidence=0.9))
    db.commit()
    cards = promises_due(db)
    assert [c.article_ids for c in cards] == [[1]], [c.article_ids for c in cards]  # the real article's promise (the positive control), not the stand-in's


# --------------------------------------------------------------------------- #
#  the readers of the keyword mentions kept for a lost article
# --------------------------------------------------------------------------- #
def _mentions(session, term, article_ids, *, day=None, language="en", count=2, source_id=None) -> None:
    """One keyword and a mention of it by each article (the rows a lost article's mentions leave in the table). The mention carries the
    denormalised date and source of its article, as the indexer writes them; ``source_id`` names another source (a lost article's mentions keep
    the source its REAL row had, which may be a source that is still there)."""
    from datetime import UTC, datetime

    from src.database.models import Article, Keyword, KeywordMention

    kw = session.query(Keyword).filter_by(normalized_term=term, language=language).first()
    if kw is None:
        kw = Keyword(term=term, normalized_term=term, language=language)
        session.add(kw)
        session.flush()
    for aid in article_ids:
        session.add(KeywordMention(keyword_id=kw.id, article_id=aid, count=count, observed_on=day or datetime.now(UTC).date(), source_id=source_id or session.get(Article, aid).source_id))
    session.commit()


def _of_source(source: int, n: int, *, skip: int = 0) -> list[int]:
    """The ids of ``n`` real articles of real source ``source`` (1 to 12): the fixture deals its articles to the twelve sources in turn."""
    return [source + 12 * (skip + i) for i in range(n)]


def _days_ago(n: int) -> date:
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC).date() - timedelta(days=n)


def test_a_keyword_born_wide_in_one_real_article_and_the_stand_in_is_not_manufactured_emergence(db):
    """``find_manufactured_emergence`` needs a keyword new in the period, in several articles across several distinct sources: the stand-in's
    placeholder source made one real article pass both gates."""
    from src.analytics.emergence import find_manufactured_emergence

    gates = {"min_recent_articles": 2, "min_sources": 2}
    _mentions(db, "novelterm", [1, STAND_IN_ARTICLE])
    assert find_manufactured_emergence(db, **gates)["items"] == []
    _mentions(db, "newterm", [1, 2])  # the positive control: two real articles of two sources are an item
    items = find_manufactured_emergence(db, **gates)["items"]
    assert [(i["term"], i["recent_articles"], i["recent_sources"], sorted(i["article_ids"])) for i in items] == [("newterm", 2, 2, [1, 2])], items


def test_the_stand_in_neither_fills_the_recent_floor_of_an_emergence_nor_adds_the_second_source_of_one(db):
    """The two gates of ``find_manufactured_emergence`` each read the child rows once (the recent count that makes a candidate, and the
    articles and sources of a candidate), and each hides the other: with only one of them removed the stand-in is stopped by the other. So each
    is asked on its own. The FLOOR: two real articles and the stand-in are three mentions, but the floor of three asks real articles. The
    SOURCES: two real articles of ONE source and the stand-in pass the floor of two on the real ones alone, and it is the stand-in's placeholder
    source that would make them two sources."""
    from src.analytics.emergence import find_manufactured_emergence

    _mentions(db, "floorterm", [1, 2, STAND_IN_ARTICLE])
    assert find_manufactured_emergence(db, min_recent_articles=3, min_sources=2)["items"] == []
    _mentions(db, "floorterm", [3])  # the positive control: three real articles reach the floor
    items = find_manufactured_emergence(db, min_recent_articles=3, min_sources=2)["items"]
    assert [(i["term"], i["recent_articles"], i["recent_sources"]) for i in items] == [("floorterm", 3, 3)], items

    _mentions(db, "onesource", _of_source(1, 2) + [STAND_IN_ARTICLE])
    lone = [i["term"] for i in find_manufactured_emergence(db, min_recent_articles=2, min_sources=2)["items"]]
    assert "onesource" not in lone, lone
    _mentions(db, "onesource", [2])  # the positive control: a real article of a second source is the second source
    twin = {i["term"]: (i["recent_articles"], i["recent_sources"]) for i in find_manufactured_emergence(db, min_recent_articles=2, min_sources=2)["items"]}
    assert twin["onesource"] == (3, 2), twin


def test_a_story_of_one_real_article_and_the_stand_in_is_no_story_and_never_a_story_of_two_sources(db):
    """The keyword sets of the period cluster articles into stories, and ``single_source`` reads the sources of the cluster: the stand-in made a
    one-source cluster a pair of two sources."""
    from datetime import UTC, datetime, timedelta

    from src.bulletin.period import Period
    from src.bulletin.stories import build_stories

    today = datetime.now(UTC).date()
    period = Period(cadence="daily", start=today - timedelta(days=1), end=today + timedelta(days=1), baseline_start=today - timedelta(days=8))
    for term in ("alpha", "beta", "gamma"):
        _mentions(db, term, [1, STAND_IN_ARTICLE])
    lone = build_stories(db, period)
    assert lone["stories"] == [] and lone["articles_in_period"] == 1, lone
    for term in ("alpha", "beta", "gamma"):
        _mentions(db, term, [2])  # the positive control: two real articles of two sources are one story
    pair = build_stories(db, period)
    assert [(s["article_ids"], s["distinct_sources"], s["single_source"]) for s in pair["stories"]] == [([1, 2], 2, False)], pair
    assert "(lost sources" not in str(pair)


def test_the_shared_links_of_a_keywords_articles_never_count_the_stand_in_as_a_citer(client):
    session = _api_session(client)
    _mentions(session, "sharedterm", [1, STAND_IN_ARTICLE])
    _links(session, [1, STAND_IN_ARTICLE], "shared.example/page")
    lone = client.get("/api/links/shared", params={"term": "sharedterm"}).json()
    assert lone["members"] == 1 and lone["shared"] == [], lone
    _mentions(session, "sharedterm", [2])
    _links(session, [2], "shared.example/page")
    pair = client.get("/api/links/shared", params={"term": "sharedterm"}).json()  # the positive control
    assert pair["members"] == 2 and [(s["url"], s["cited_by_articles"], s["citing_sources"]) for s in pair["shared"]] == [("shared.example/page", 2, 2)], pair
    assert sorted(c["article_id"] for c in pair["shared"][0]["citers"]) == [1, 2], pair


# --------------------------------------------------------------------------- #
#  the brush over a keyword trend: the quarantined ids are asked for and subtracted
# --------------------------------------------------------------------------- #
def test_a_brushed_span_subtracts_the_quarantined_ids_it_asks_for_the_stand_in_among_them(db):
    """``IS NOT 1`` per chunk probes an article row per id until the table was analysed (12.8 MiB per 900 ids); ``IS 1`` seeks the covering index
    whether or not it was. The ids that ARE quarantined (the stand-in is) are asked for and subtracted, and the count that was excluded is exact."""
    from sqlalchemy import event

    from src.analytics.queries import trend_range_article_ids
    from src.database.models import Article

    _mentions(db, "brushterm", [1, 2, 3, STAND_IN_ARTICLE], day=DAY)
    two = db.get(Article, 2)
    two.quarantined, two.quarantine_reason = True, "link list"
    db.commit()
    seen: list[tuple[str, object]] = []
    engine = db.get_bind()

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM articles" in statement and "quarantined" in statement:
            seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        out = trend_range_article_ids(db, "brushterm", start=DAY, end=DAY)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert out["article_ids"] == [1, 3] and out["articles"] == 2 and out["quarantined_excluded"] == 2, out
    assert seen and all("quarantined IS 1" in sql and "IS NOT 1" not in sql for sql, _ in seen), seen
    for sql, params in seen:  # whatever the planner does, it does not probe an article row per id
        plan = [str(r[-1]) for r in engine.connect().exec_driver_sql("EXPLAIN QUERY PLAN " + sql, params)]
        assert not any("INTEGER PRIMARY KEY" in line for line in plan), plan


# --------------------------------------------------------------------------- #
#  the analyses that read the keyword mentions kept for a lost article by their own columns (E3 fold 9, item 5)
#
#  A mention keeps the source and the date its REAL article had, so the stand-in's mentions can name a source that is still there (the case the
#  tests call ``source_id=1``) or the stand-in source (13). Each analysis is asked once with the stand-in's mention in the window (it must not
#  change the answer) and once with a real twin of that mention (the positive control: the same answer a real article gives).
# --------------------------------------------------------------------------- #
def test_the_concept_views_never_count_list_or_head_with_the_stand_in_whose_mentions_were_kept(db, monkeypatch):
    """``ring_country_split`` (a country's counts), ``ring_country_article_ids`` (its drill), ``context`` (the recent mentions) and the supergroup
    overlap set each read the mentions of a concept: the stand-in's placeholder source made a country bucket, its id was drilled and listed."""
    from datetime import timedelta

    from src.analytics import equivalence
    from src.analytics import queries as q

    ring = equivalence.Ring(id="standinring", members=(("en", "ringterm"),))
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "standinring" else None)
    monkeypatch.setattr(equivalence, "ring_of", lambda lang, norm: "standinring" if (lang, norm) in ring.members else None)
    _mentions(db, "ringterm", [1], day=_days_ago(3))
    _mentions(db, "ringterm", [STAND_IN_ARTICLE], day=_days_ago(1) + timedelta(days=0))  # the newest: it would head the recent mentions

    def views():
        split = {c["country"]: c for c in q.ring_country_split(db, ring_id="standinring")["countries"]}
        drill = q.ring_country_article_ids(db, ring_id="standinring", country=None)["article_ids"]
        recent = [m["article_id"] for m in q.context(db, "ringterm")["mentions"]]
        return split[None]["articles"], split[None]["mentions"], drill, recent, q._article_set(db, ["ringterm"])

    assert views() == (1, 2, [1], [1], {1}), views()
    _mentions(db, "ringterm", [2], day=_days_ago(2))  # the positive control: a second real article is counted, drilled, listed and in the set
    assert views() == (2, 4, [1, 2], [2, 1], {1, 2}), views()


@pytest.mark.parametrize(
    "case",
    ["listed", "floor of the week", "floor of the baseline", "floor of the term", "share of the baseline", "ubiquity"],
)
def test_a_source_is_flooded_by_its_real_articles_only_never_by_the_stand_in_whose_mentions_were_kept(db, case):
    """Each read of ``find_flooded_topics`` is asked a question only the stand-in's mention could change: the articles it lists, the source's
    articles this week, last month, the term's articles this week, the term's share last month, and the sources that carry the term. A case
    that expects an item is the one a read ungated would have made impossible; a case that expects none is the one it would have made."""
    from src.analytics.concentration import find_flooded_topics
    from src.database.models import Source

    recent, prior = _days_ago(1), _days_ago(30)
    flood, filler, old, z_min = 3, 0, 3, 1.5  # real articles of source 1 that carry the term this week / something else this week / something else last month
    ghost: list[tuple[str, object, int]] = []
    expect_item = False
    if case == "listed":
        ghost, expect_item = [("floodterm", recent, 1)], True
    elif case == "floor of the week":
        flood, ghost = 2, [("sparetopic", recent, 1)]
    elif case == "floor of the baseline":
        flood, filler, old, ghost = 2, 1, 2, [("sparetopic", prior, 1)]
    elif case == "floor of the term":
        flood, filler, ghost = 1, 2, [("floodterm", recent, 1)]
    elif case == "share of the baseline":
        z_min, ghost, expect_item = 2.0, [("floodterm", prior, 1)], True
    else:  # the term is carried by two of the three active sources only if the stand-in's mention names a second one
        ghost, expect_item = [("floodterm", recent, 2)], True
        db.query(Source).filter(Source.id.in_([1, 2, 3])).update({Source.language: "en"}, synchronize_session=False)
        db.commit()
        _mentions(db, "sparetopic", [2, 3], day=recent)  # sources 2 and 3 are active this week, so three en sources are the cohort
    mine = _of_source(1, 40)
    flood_ids = mine[10 : 10 + flood]
    _mentions(db, "oldtopic", mine[:old], day=prior)
    _mentions(db, "floodterm", flood_ids, day=recent)
    for n, aid in enumerate(mine[20 : 20 + filler]):  # each filler article carries a topic of its own, so none is a flood
        _mentions(db, f"filler{n}", [aid], day=recent)
    for term, day, source in ghost:
        _mentions(db, term, [STAND_IN_ARTICLE], day=day, source_id=source)
    items = find_flooded_topics(db, min_recent_articles=3, min_recent_count=2, min_prior_articles=3, z_min=z_min)["items"]
    if not expect_item:
        assert items == [], (case, items)
        return
    assert [(i["term"], i["recent_articles"], i["recent_total"], i["baseline_share"]) for i in items] == [("floodterm", 3, 3, 0.0)], (case, items)
    assert items[0]["article_ids"] == sorted(flood_ids), (case, items)


def test_a_source_buried_below_its_peers_is_judged_on_real_articles_and_lists_real_articles_only(db):
    """``find_buried_topics`` reads the corpus size, a source's total, a topic's breadth and the pairs from one window, and lists the topic's articles
    from a second query: the stand-in's two mentions (kept under the buried source) were counted in all of them and listed."""
    from src.analytics.concentration import find_buried_topics

    day = _days_ago(3)
    for source in range(2, 7):  # five sources whose thirty articles each cover the topic
        _mentions(db, "burytopic", _of_source(source, 30), day=day)
    _mentions(db, "sparetopic", _of_source(1, 30), day=day)  # the thirty articles of source 1 cover something else
    _mentions(db, "burytopic", [STAND_IN_ARTICLE], day=day, source_id=1)
    _mentions(db, "sparetopic", [STAND_IN_ARTICLE], day=day, source_id=1)
    items = find_buried_topics(db, window_days=30)["items"]
    assert [(i["term"], i["source"], i["source_total"], i["source_articles_on_topic"], i["corpus_articles_on_topic"]) for i in items] == [("burytopic", "s0", 30, 0, 150)], items
    assert len(items[0]["article_ids"]) == 150 and STAND_IN_ARTICLE not in items[0]["article_ids"], items[0]["article_ids"][-3:]


def test_a_story_spread_over_real_sources_never_counts_the_stand_in_as_a_source_nor_lists_it(db):
    """``find_story_propagation`` needs three sources and a span: the stand-in's source (or the source its mention kept) was the first sighting or
    the third source, and its id was listed."""
    from datetime import UTC, datetime

    from src.analytics.story_propagation import find_story_propagation

    today = datetime.now(UTC).date()
    _mentions(db, "spreadterm", [1], day=_days_ago(6))
    _mentions(db, "spreadterm", [2], day=_days_ago(2))
    _mentions(db, "spreadterm", [STAND_IN_ARTICLE], day=_days_ago(9))  # the stand-in source, earlier than both
    assert find_story_propagation(db, today=today)["items"] == []
    _mentions(db, "spreadterm", [3], day=_days_ago(1))  # the positive control: a third real source
    items = find_story_propagation(db, today=today)["items"]
    assert [(i["distinct_sources"], i["first_source"], i["article_ids"]) for i in items] == [(3, "s0", [1, 2, 3])], items


def test_the_keyword_algebra_never_holds_or_counts_the_stand_in(db):
    from src.analytics.conjunction import corpus_algebra

    for term in ("algone", "algtwo"):
        _mentions(db, term, [1, STAND_IN_ARTICLE])
    out = corpus_algebra(db, ["algone", "algtwo"], op="intersection")
    assert out["article_ids"] == [1] and out["n_combined"] == 1 and [t["n"] for t in out["terms"]] == [1, 1], out
    for term in ("algone", "algtwo"):
        _mentions(db, term, [2])  # the positive control
    out = corpus_algebra(db, ["algone", "algtwo"], op="intersection")
    assert out["article_ids"] == [1, 2] and [t["n"] for t in out["terms"]] == [2, 2], out


def test_the_first_channel_to_carry_a_concept_is_never_credited_to_the_stand_in_whose_mention_was_kept(db):
    from datetime import UTC, datetime, timedelta

    from src.bulletin.period import Period
    from src.bulletin.sections import across_channels

    today = datetime.now(UTC).date()
    period = Period(cadence="daily", start=today - timedelta(days=5), end=today + timedelta(days=1), baseline_start=today - timedelta(days=12))
    terms = [{"normalized": "chanterm", "term": "chanterm"}]
    _mentions(db, "chanterm", [STAND_IN_ARTICLE], day=_days_ago(4))  # the stand-in source would be the first channel
    _mentions(db, "chanterm", [1], day=_days_ago(1))
    first = [(t["term"], t["first_seen"]) for t in across_channels(db, period, terms=terms)["terms"]]
    assert first == [("chanterm", _days_ago(1).isoformat())], first
    _mentions(db, "chanterm", [2], day=_days_ago(3))  # the positive control: a real article that is earlier counts
    first = [(t["term"], t["first_seen"]) for t in across_channels(db, period, terms=terms)["terms"]]
    assert first == [("chanterm", _days_ago(3).isoformat())], first


def test_a_weather_opportunity_never_counts_or_lists_the_stand_in_whose_place_and_mention_were_kept(db):
    from src.analytics.corroboration import find_weather_opportunities
    from src.database.models import ArticleMentionedPlace

    def nairobi(ids):
        for aid in ids:
            db.add(ArticleMentionedPlace(article_id=aid, name="Nairobi", country="ke", kind="city", mentions=1, lat=-1.2864, lon=36.8172, extractor="lexical-v1"))
        db.commit()

    _mentions(db, "drought", [1, 2, STAND_IN_ARTICLE], day=_days_ago(5))
    nairobi([1, 2, STAND_IN_ARTICLE])
    lone = find_weather_opportunities(db, min_articles=3)
    assert lone["clusters_total"] == 0 and lone["opportunities"] == [], lone
    _mentions(db, "drought", [3], day=_days_ago(5))  # the positive control: three real articles
    nairobi([3])
    found = find_weather_opportunities(db, min_articles=3)
    assert [(o["place"], o["article_ids"]) for o in found["opportunities"]] == [("Nairobi", [1, 2, 3])], found


def test_the_supply_chain_ripple_counts_outlets_and_lists_articles_of_real_articles_only(db):
    from src.analytics.supply_chain_ripple import _pair_article_ids, _source_counts
    from src.database.models import Keyword

    today = _days_ago(0)
    for term in ("ripplea", "rippleb"):
        _mentions(db, term, [1, STAND_IN_ARTICLE], day=_days_ago(2))
    ids = {k.normalized_term: k.id for k in db.query(Keyword).filter(Keyword.normalized_term.in_(["ripplea", "rippleb"]))}
    cutoff, hi = _days_ago(10), today.replace(year=today.year + 1)
    assert _source_counts(db, [ids["ripplea"]], cutoff, hi) == {ids["ripplea"]: 1}  # the stand-in source is no second outlet
    assert _pair_article_ids(db, ids["ripplea"], ids["rippleb"], cutoff, hi, 100) == [1]
    _mentions(db, "ripplea", [2], day=_days_ago(2))
    _mentions(db, "rippleb", [2], day=_days_ago(2))  # the positive control: a second real article of a second real source
    assert _source_counts(db, [ids["ripplea"]], cutoff, hi) == {ids["ripplea"]: 2}
    assert _pair_article_ids(db, ids["ripplea"], ids["rippleb"], cutoff, hi, 100) == [1, 2]


def test_the_breadth_and_the_article_sets_of_a_supergroup_never_count_or_list_the_stand_in(client):
    """``_distinct_source_count`` (the breadth every galaxy is ranked by), the rising pass's windowed source count and article set, and the route
    that opens a group's articles."""
    from datetime import timedelta

    from src.analytics.supergroup_rising import _article_ids_windowed, _distinct_sources_windowed
    from src.analytics.supergroup_stats import _distinct_source_count
    from src.database.models import Keyword, KeywordSuperGroup, KeywordSuperGroupMember

    session = _api_session(client)
    _mentions(session, "groupterm", [1], day=_days_ago(2))
    _mentions(session, "groupterm", [STAND_IN_ARTICLE], day=_days_ago(2))  # the stand-in source
    kid = session.query(Keyword.id).filter(Keyword.normalized_term == "groupterm").scalar()
    group = KeywordSuperGroup(name="a group")
    session.add(group)
    session.flush()
    session.add(KeywordSuperGroupMember(supergroup_id=group.id, normalized_term="groupterm", ring_id=None))
    session.commit()
    lo, hi = _days_ago(10), _days_ago(0) + timedelta(days=1)

    def measured():
        route = client.get("/api/insights/supergroup-articles", params={"group_id": group.id}).json()
        return _distinct_source_count(session, {kid}), _distinct_sources_windowed(session, {kid}, lo, hi), _article_ids_windowed(session, {kid}, lo, hi), route["article_ids"], route["total_articles"]

    assert measured() == (1, 1, [1], [1], 1), measured()
    _mentions(session, "groupterm", [2], day=_days_ago(2))  # the positive control: a second real source and article
    assert measured() == (2, 2, [1, 2], [1, 2], 2), measured()


def test_a_rising_group_is_not_diluted_by_a_source_only_the_stand_in_names(db):
    """``find_rising_supergroups`` takes the sources active this week as the denominator of its ubiquity gate: a mention kept for a lost article
    made a source that wrote nothing this week one of them, and a term carried by two of five sources (the gate's limit) by two of six."""
    from datetime import date, timedelta

    from src.analytics.supergroup_rising import find_rising_supergroups
    from src.database.models import KeywordSuperGroup, KeywordSuperGroupMember, Source

    today = date(2026, 7, 18)
    w_start = today - timedelta(days=7)
    b_start = w_start - timedelta(days=30)
    db.query(Source).filter(Source.id.in_(range(1, 8))).update({Source.language: "en"}, synchronize_session=False)
    for i in range(1, 6):  # five sources write every week, so they are the active ones
        _mentions(db, "noise", [_of_source(i, 1)[0]], day=b_start + timedelta(days=1), count=50)
        _mentions(db, "noise", [_of_source(i, 1, skip=1)[0]], day=w_start + timedelta(days=1), count=50)
    _mentions(db, "risingterm", _of_source(1, 2, skip=5), day=b_start + timedelta(days=1), count=1)
    _mentions(db, "risingterm", [_of_source(1, 1, skip=7)[0]], day=w_start + timedelta(days=1), count=15)
    _mentions(db, "risingterm", [_of_source(2, 1, skip=7)[0]], day=w_start + timedelta(days=1), count=15)
    group = KeywordSuperGroup(name="Test Group")
    db.add(group)
    db.flush()
    db.add(KeywordSuperGroupMember(supergroup_id=group.id, normalized_term="risingterm", ring_id=None))
    db.commit()
    _mentions(db, "noise", [STAND_IN_ARTICLE], day=w_start + timedelta(days=1), count=2, source_id=7)  # source 7 wrote nothing this week
    found = find_rising_supergroups(db, window_days=7, baseline_days=30, today=today)
    assert found["count"] == 0 and found["tested"] >= 1, found  # two of the five active sources carry it: the gate's limit (0.40)
    _mentions(db, "noise", [_of_source(7, 1, skip=1)[0]], day=w_start + timedelta(days=1), count=2)  # the positive control: source 7 really wrote
    found = find_rising_supergroups(db, window_days=7, baseline_days=30, today=today)
    assert found["count"] == 1 and found["items"][0]["name"] == "Test Group", found


def test_a_source_gets_topics_and_tag_proposals_from_its_real_articles_only(db):
    """``derive_source_topics`` and ``select_source_tag_candidates`` count a source's articles from mentions that keep the source of their real
    article: the stand-in's mention (kept under source 1) was an article of source 1 that makes the evidence floor and tops the term list."""
    from src.ai_layer.source_tags import select_source_tag_candidates
    from src.analytics.source_topics import derive_source_topics
    from src.database.models import Keyword, KeywordTag

    _mentions(db, "housing", [1], count=3)
    kid = db.query(Keyword.id).filter(Keyword.normalized_term == "housing").scalar()
    db.add(KeywordTag(keyword_id=kid, axis="topic", tag="economy", source="baseline"))
    db.commit()
    _mentions(db, "housing", [STAND_IN_ARTICLE], count=3, source_id=1)
    _mentions(db, "ghostterm", [STAND_IN_ARTICLE], count=99, source_id=1)
    assert derive_source_topics(db, min_articles=2) == []  # one real article of source 1 is under the floor of two
    items, skipped = select_source_tag_candidates(db, min_articles=2, min_mentions=1)[:2]
    assert [s.article_count for s in skipped if s.domain == "s0.example.org"] == [1] and not [i for i in items if i.domain == "s0.example.org"]
    _mentions(db, "housing", [13], count=3)  # the positive control: a second real article of source 1
    topics = derive_source_topics(db, min_articles=2)
    assert [(t["domain"], t["topics"]) for t in topics] == [("s0.example.org", ["economy"])], topics
    items = select_source_tag_candidates(db, min_articles=2, min_mentions=1)[0]
    mine = next(i for i in items if i.domain == "s0.example.org")
    assert mine.article_count == 2 and "housing" in mine.top_terms and "ghostterm" not in mine.top_terms, mine


def test_the_backfill_the_reindex_and_the_language_pass_never_touch_the_stand_in_and_its_kept_mentions_stay(db):
    """A stand-in has no text, so indexing it finds no terms: the re-index would REPLACE the mentions the copy kept for the lost article with
    none, and the backfill would stamp an attempt on a row that is not an article; the language pass would deduce one from its kept mentions."""
    from src.analytics.extract import get_extractor
    from src.analytics.store import _unindexed_query, reconcile_article_language, reindex_articles
    from src.database.models import Article, KeywordMention

    # The backfill's worklist, asked BEFORE any mention is kept for the stand-in: once it has one the worklist leaves it out for that reason
    # alone (it is no longer "unindexed"), and the gate would be hidden behind it.
    waiting = {int(a.id) for a in _unindexed_query(db).with_entities(Article.id)}
    assert 1 in waiting and STAND_IN_ARTICLE not in waiting, len(waiting)
    for term in ("langa", "langb", "langc"):
        _mentions(db, term, [STAND_IN_ARTICLE], source_id=1)
    done = reindex_articles(db, extractor=get_extractor("baseline"), article_ids=[1, STAND_IN_ARTICLE])
    assert done["reindexed"] == 1, done
    assert db.query(KeywordMention).filter_by(article_id=STAND_IN_ARTICLE).count() == 3  # the kept mentions are still there
    out = reconcile_article_language(db, limit=5, after_id=STAND_IN_ARTICLE - 1)
    assert out["scanned"] == 0 and out["done"] is True, out
    db.expire_all()
    assert db.get(Article, STAND_IN_ARTICLE).detected_language is None
    # The same pass with a real article still waiting: the candidate scan and the count of what REMAINS are two reads, and each hides the other
    # (the stand-in as a candidate is scanned; the stand-in as a remainder keeps `done` false for ever).
    db.query(Article).filter(Article.id != STAND_IN_ARTICLE).update({"language": "en", "detected_language": None}, synchronize_session=False)
    db.query(Article).filter(Article.id == 1).update({"language": None}, synchronize_session=False)
    db.commit()
    out = reconcile_article_language(db, limit=5, after_id=0)
    assert out["scanned"] == 1 and out["last_id"] == 1 and out["done"] is True, out
    newest = [r[0] for r in db.query(Article.id).filter(Article.id >= 1495, stand_in.not_a_stand_in_article_id(Article.id)).order_by(Article.id)]
    assert newest == [1495, 1496], newest  # the condition reads an article's own id too (the stand-in at 1500 is left out)
