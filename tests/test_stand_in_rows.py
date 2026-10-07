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
        for claim in ("quarantined", "stand-in for a lost row", "source lists", "never collected or qualified", "deleted"):
            assert claim in salvage.STAND_IN_NOTE, f"the report's note does not say {claim!r}"
        # the real rows carry none of these marks
        assert con.execute("SELECT count(*) FROM articles WHERE quarantine_reason = ?", (stand_in.ARTICLE_REASON,)).fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM sources WHERE enabled = 0").fetchone()[0] == 1
    finally:
        con.close()


def test_the_text_a_stand_in_source_carries_starts_with_the_prefix_the_readers_leave_out():
    """The copy writes ``(lost sources 13)`` through ``stand_in.lost_text`` and the readers leave out by ``SOURCE_DOMAIN_PREFIX``: two names for one fact."""
    assert stand_in.lost_text("sources", 13).startswith(stand_in.SOURCE_DOMAIN_PREFIX)
    assert stand_in.is_stand_in_source_domain(stand_in.lost_text("sources", 7)) and not stand_in.is_stand_in_source_domain("example.org")
    assert not stand_in.is_stand_in_source_domain(None) and not stand_in.is_stand_in_source_domain("")


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
