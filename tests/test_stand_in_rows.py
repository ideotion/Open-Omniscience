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
        for claim in ("quarantined", "stand-in for a lost row", "source lists", "never collected or qualified", "deleted", "signed evidence bundle", "AI routes", "date tags", "finds it by its number", "still include it"):
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
    ],
    ids=["summarize", "translate", "analyses", "ai-keywords", "date-tags", "extract-dates"],
)
def test_an_article_by_id_route_of_the_ai_layer_or_the_date_tags_answers_the_stand_in_as_not_found(client, fake_llm, method, path, body):
    _give_articles_what_a_stand_in_could_carry(_api_session(client))
    lost = client.request(method, path.format(STAND_IN_ARTICLE), json=body)
    assert lost.status_code == 404, (lost.status_code, lost.text)
    assert STAND_IN_MARKER not in lost.text
    assert all(STAND_IN_MARKER not in p for p in fake_llm.prompts), "the model was handed the stand-in's text"
    real = client.request(method, path.format(1), json=body)  # the positive control: the same route answers for a real article
    assert real.status_code == 200, (real.status_code, real.text)


def test_an_article_the_app_judged_not_an_article_is_still_reached_by_its_id_in_those_routes(client, fake_llm):
    """Only the stand-in is refused: an article that was quarantined for what it is (a link list) is a real row, and an explicit id reaches it
    (the reader and the explicit id sets of the signed outputs do the same), so a gate that read ``quarantined`` instead of the stand-in's own
    reason would turn it into a not-found."""
    from src.database.models import Article

    session = _api_session(client)
    _give_articles_what_a_stand_in_could_carry(session, ids=(1, 2))
    row = session.get(Article, 2)
    row.quarantined, row.quarantine_reason = True, "link list"
    session.commit()
    for method, path, body in [
        ("POST", "/api/llm/articles/{}/summarize", {"model": "m"}),
        ("GET", "/api/llm/articles/{}/analyses", None),
        ("GET", "/api/ai/articles/{}/keywords", None),
        ("GET", "/api/article-dates/article/{}", None),
        ("POST", "/api/article-dates/article/{}", None),
    ]:
        reached = client.request(method, path.format(2), json=body)
        assert reached.status_code == 200, (method, path, reached.status_code, reached.text)
    synth = client.post("/api/llm/synthesize", json={"article_ids": [2]})
    assert synth.status_code == 200 and [m["id"] for m in synth.json()["members"]] == [2], synth.text


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
    assert [client.request(m, "/api/sources/abc").status_code for m in ("GET", "PUT", "DELETE")] == [404, 404, 404]  # a segment that is no id is no route, for every method


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
