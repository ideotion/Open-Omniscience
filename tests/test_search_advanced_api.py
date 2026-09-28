"""The advanced search end to end (S05-01 S4-S7): filters, export parity, saved searches,
did-you-mean, local history.

The gate row's exit bar is the second test here, stated as the brief states it: *the export
compared row-for-row with the filtered view on the reference corpus -- ids and order
identical, the ordering in the file header*. The reference corpus is the scale generator's
(`src/testing/corpus_gen.py`), scaled down, so the filters meet the article shapes, the
language mix and the source tags the benchmarks use.
"""

from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.api.ratelimit import limiter
from src.database.models import Article, ArticleMentionedDate, Base, Keyword, KeywordMention, Source
from src.database.session import get_db


def _client_for(engine):
    TS = sessionmaker(bind=engine, future=True)

    def _db():
        db = TS()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    return TS


@pytest.fixture()
def small(tmp_path):
    """A hand-built corpus where every filter has a row on each side of it."""
    from src.database.fts import ensure_fts
    from src.database.fts_norm import install_pool_hook

    install_pool_hook()
    engine = create_engine(f"sqlite:///{tmp_path / 's.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    TS = _client_for(engine)
    now = datetime(2026, 9, 1, 12, 0)
    with TS() as s:
        fr = Source(name="Le Monde", domain="lemonde.fr", tags="europe", country="fr", region="europe")
        us = Source(name="Wire", domain="wire.us", tags="world", country="us", region="americas")
        s.add_all([fr, us])
        s.flush()
        specs = [
            # title, src, language, detected, words, sentiment, created, quarantined, mentions
            ("energy one", fr, "fr", None, 100, None, now - timedelta(days=30), False, "2020-05-01"),
            ("energy two", us, "en", None, 900, "positive", now - timedelta(days=10), False, None),
            ("energy three", us, None, "de", 2500, None, now - timedelta(days=2), False, "2024-01-15"),
            ("energy four", us, "en", None, 300, "negative", now - timedelta(days=1), True, None),
        ]
        for i, (title, src, lang, det, wc, sent, created, quar, mention) in enumerate(specs):
            a = Article(url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=src.id,
                        title=title, content=f"{title} policy text", hash=str(i).ljust(64, "0"),
                        language=lang, detected_language=det, word_count=wc,
                        sentiment_label=sent, sentiment_score={"positive": 0.6, "negative": -0.5}.get(sent),
                        created_at=created, published_at=created, quarantined=quar,
                        quarantine_reason="navigation page" if quar else None)
            s.add(a)
            s.flush()
            if mention:
                s.add(ArticleMentionedDate(article_id=a.id,
                                           mentioned_on=datetime.fromisoformat(mention).date(),
                                           status="candidate"))
        s.commit()
    limiter.reset()  # /api/articles is 100/hour for the test client; isolate this file's hits
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    limiter.reset()


def _t(client, **params) -> list[str]:
    r = client.get("/api/articles", params={"query": "energy", **params})
    assert r.status_code == 200, r.text
    return sorted(x["title"] for x in r.json()["results"])


def test_every_q601_filter_is_reachable(small) -> None:
    assert _t(small) == ["energy one", "energy three", "energy two"]  # quarantined out
    assert _t(small, include_quarantined="true") == [
        "energy four", "energy one", "energy three", "energy two"]
    assert _t(small, langs="en") == ["energy two"]
    assert _t(small, langs="de") == ["energy three"]  # detected only
    assert _t(small, langs="de", lang_basis="asserted") == []
    assert _t(small, langs="en,fr", lang_basis="asserted") == ["energy one", "energy two"]
    assert _t(small, countries="FRA") == ["energy one"]  # alpha-3 accepted
    assert _t(small, countries="us") == ["energy three", "energy two"]
    assert _t(small, regions="europe") == ["energy one"]
    assert _t(small, collected_from="2026-08-20") == ["energy three", "energy two"]
    assert _t(small, collected_to="2026-08-02") == ["energy one"]  # whole last day included
    assert _t(small, words_min="500") == ["energy three", "energy two"]
    assert _t(small, words_max="500") == ["energy one"]
    assert _t(small, sentiment="positive") == ["energy two"]
    assert _t(small, mentions_from="2024-01-01") == ["energy three"]
    assert _t(small, mentions_to="2021-01-01") == ["energy one"]
    fr_id = small.get("/api/search/facets").json()["sources"]
    fr_id = next(x["id"] for x in fr_id if x["name"] == "Le Monde")
    assert _t(small, sources=str(fr_id)) == ["energy one"]


def test_quarantined_row_says_why(small) -> None:
    rows = small.get("/api/articles", params={"query": "energy four", "include_quarantined": "true"}).json()
    [row] = rows["results"]
    assert row["quarantined"] is True and row["quarantine_reason"] == "navigation page"


def test_bad_filter_values_are_400_not_guesses(small) -> None:
    for params in ({"sentiment": "happy"}, {"lang_basis": "both"}, {"collected_from": "May"},
                   {"near": "5000"}, {"words_min": "-1"}):
        assert small.get("/api/articles", params={"query": "energy", **params}).status_code in (400, 422)


def test_table_sorts_words_and_sentiment(small) -> None:
    r = small.get("/api/articles", params={"query": "energy", "sort_by": "words", "sort_dir": "desc"}).json()
    assert [x["word_count"] for x in r["results"]] == [2500, 900, 100]
    assert r["ordering"]["by"] == "words"
    r = small.get("/api/articles", params={"query": "energy"}).json()
    assert r["ordering"]["by"] == "relevance" and "not a sample" in r["ordering"]["statement"]


def test_facets_carry_counts_and_caveats(small) -> None:
    f = small.get("/api/search/facets").json()
    assert {c["display"] for c in f["countries"]} == {"FRA", "USA"}
    langs = {x["code"]: x for x in f["languages"]}
    assert langs["de"] == {"code": "de", "asserted": 0, "detected": 1}
    assert "English" in f["caveats"]["sentiment"]
    assert f["near"]["default"] == 10


def test_analysis_window_reads_the_same_filters(small) -> None:
    a = small.get("/api/insights/corpus-sources", params={"query": "energy", "countries": "us"}).json()
    b = small.get("/api/insights/corpus-sources", params={"query": "energy"}).json()
    assert a["total_matched"] == 2 and b["total_matched"] == 3


# --------------------------------------------------------------------------- #
# The gate's exit row: export == view, on the reference corpus
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    from src.database.fts_norm import install_pool_hook
    from src.testing.corpus_gen import CorpusSpec, generate_corpus

    install_pool_hook()
    path = tmp_path_factory.mktemp("ref") / "ref.db"
    generate_corpus(path, CorpusSpec(articles=1500, sources=40, mentions_per_article=12,
                                     head_pool=800, content_words=60))
    engine = create_engine(f"sqlite:///{path}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)  # tables the generator does not create (watches ...)
    return engine


@pytest.mark.parametrize("params", [
    {"query": "baba OR bebe"},
    {"query": "baba", "langs": "en,fr", "sort_by": "date", "sort_dir": "asc"},
    {"query": "ba*", "countries": "USA,gb", "words_min": "10"},
    {"query": "NEAR(baba bebe)", "sort_by": "source"},
    {"query": "source:\"source 1\" NOT ba"},
])
def test_export_reproduces_the_filtered_view_row_for_row(reference, params) -> None:
    _client_for(reference)
    limiter.reset()
    try:
        with TestClient(app) as c:
            view = c.get("/api/articles", params={**params, "limit": 1000})
            assert view.status_code == 200, view.text
            view = view.json()
            assert view["total"] <= 1000, "the fixture must fit on one page to compare"
            ids = [r["id"] for r in view["results"]]
            j = c.get("/api/articles/export", params={**params, "format": "json"})
            assert j.status_code == 200, j.text
            body = j.json()
            assert [r["id"] for r in body["articles"]] == ids
            assert body["ordering"] == view["ordering"]
            k = c.get("/api/articles/export", params={**params, "format": "csv"})
            rows = list(csv.reader(io.StringIO(k.text)))[1:]
            assert [int(r[0]) for r in rows] == ids
            assert k.headers["X-OO-Ordering"].startswith(view["ordering"]["by"])
    finally:
        app.dependency_overrides.clear()
    limiter.reset()


def test_non_latin1_query_exports(reference) -> None:
    """The CSV provenance header used to fail the whole export on a CJK query."""
    _client_for(reference)
    limiter.reset()
    try:
        with TestClient(app) as c:
            r = c.get("/api/articles/export", params={"query": "北京", "format": "csv"})
            assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
    limiter.reset()


# --------------------------------------------------------------------------- #
# Saved searches (Q606 = a)
# --------------------------------------------------------------------------- #


def test_saved_search_reruns_identically_and_never_fires(small) -> None:
    filters = {"langs": ["en"], "lang_basis": "asserted", "include_quarantined": True}
    r = small.post("/api/watches", json={"name": "english energy", "query": "energy",
                                         "threshold": 0, "filters": filters})
    assert r.status_code == 200, r.text
    assert r.json()["saved_search"] is True
    # "after a restart": nothing but the stored row -- read it back fresh.
    [w] = [x for x in small.get("/api/watches").json()["watches"] if x["name"] == "english energy"]
    assert w["saved_search"] and w["filters"] == filters
    params = {"query": w["query"], "langs": ",".join(w["filters"]["langs"]),
              "lang_basis": w["filters"]["lang_basis"], "include_quarantined": "true"}
    first = small.get("/api/articles", params=params).json()
    again = small.get("/api/articles", params=params).json()
    assert [x["id"] for x in first["results"]] == [x["id"] for x in again["results"]]
    assert sorted(x["title"] for x in first["results"]) == ["energy four", "energy two"]
    fired = small.post("/api/watches/evaluate").json()
    assert all(f["name"] != "english energy" for f in fired["fired"])


def test_saved_search_rejects_a_filter_no_search_could_mean(small) -> None:
    r = small.post("/api/watches", json={"query": "energy", "threshold": 0,
                                         "filters": {"sentiments": ["ecstatic"]}})
    assert r.status_code == 422


def test_filter_only_saved_search_needs_no_query(small) -> None:
    r = small.post("/api/watches", json={"name": "fr", "query": "", "threshold": 0,
                                         "filters": {"countries": ["fr"]}})
    assert r.status_code == 200
    assert small.post("/api/watches", json={"query": "", "threshold": 3}).status_code == 422


def test_filtered_watch_fires_on_the_view_not_the_wider_query(small) -> None:
    from src.analytics.watches import evaluate_watches, list_watches

    small.post("/api/watches", json={"name": "fr only", "query": "energy", "threshold": 1,
                                     "window_days": 3650, "filters": {"countries": ["fr"]}})
    fired = small.post("/api/watches/evaluate").json()["fired"]
    [row] = [f for f in fired if f["name"] == "fr only"]
    assert row["n_articles"] == 1
    assert evaluate_watches and list_watches  # imported: the module's public surface


# --------------------------------------------------------------------------- #
# Did you mean (Q605 = b)
# --------------------------------------------------------------------------- #


def test_spell_primitives() -> None:
    from src.analytics.spell_index import deletes, distance

    assert "climte" in deletes("climate")
    assert distance("climte", "climate") == 1
    assert distance("cliamte", "climate") == 1  # adjacent swap
    assert distance("xyz", "climate") == 3  # over the limit
    assert len(deletes("abcdefghijkl")) == len(deletes("abcdefg"))  # prefix only


def test_did_you_mean_is_offered_never_substituted(small, tmp_path) -> None:
    from src.analytics import spell_index

    # Vocabulary: "energy" in 3 articles (suggestible), "enerjy" never a keyword.
    engine = app.dependency_overrides[get_db]
    gen = engine()
    db = next(gen)
    kw = Keyword(term="energy", normalized_term="energy")
    db.add(kw)
    db.flush()
    for aid in [a.id for a in db.query(Article).limit(3)]:
        db.add(KeywordMention(keyword_id=kw.id, article_id=aid, count=1))
    db.commit()

    @contextmanager
    def factory():
        s = sessionmaker(bind=db.get_bind(), future=True)()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    result = spell_index.build(session_factory=factory)
    assert result["state"] == "done" and result["keywords"] == 1 and result["rows"] > 0
    db.close()
    r = small.get("/api/articles", params={"query": "enerjy"}).json()
    assert r["total"] == 0  # the literal query ran, and matched nothing
    dym = r["did_you_mean"]
    assert dym["query"] == "energy"
    assert dym["terms"][0]["suggestions"][0] == {"term": "energy", "distance": 1, "articles": 3}
    assert "exactly as you typed" in dym["caveat"]
    # a known word gets no suggestion
    assert "did_you_mean" not in small.get("/api/articles", params={"query": "energy"}).json()


# --------------------------------------------------------------------------- #
# Local search history (Q614 = a)
# --------------------------------------------------------------------------- #


@pytest.fixture()
def history_on(small):
    small.delete("/api/search/history")
    yield small
    small.put("/api/settings", json={"search_history_enabled": False})
    small.delete("/api/search/history")


def test_history_is_off_by_default_and_refuses_to_record(history_on) -> None:
    from src.config.app_settings import AppSettings

    assert AppSettings().search_history_enabled is False
    h = history_on.get("/api/search/history").json()
    assert h["enabled"] is False and h["entries"] == []
    assert history_on.post("/api/search/history", json={"query": "x"}).status_code == 409


def test_history_records_when_on_and_clear_empties_it(history_on) -> None:
    assert history_on.put("/api/settings", json={"search_history_enabled": True}).status_code == 200
    assert history_on.put("/api/settings", json={"search_history_enabled": "yes"}).status_code == 422
    history_on.post("/api/search/history", json={"query": "energy", "params": {"langs": "en"}})
    history_on.post("/api/search/history", json={"query": "policy"})
    history_on.post("/api/search/history", json={"query": "energy", "params": {"langs": "en"}})
    entries = history_on.get("/api/search/history").json()["entries"]
    assert [e["query"] for e in entries] == ["energy", "policy"]  # deduped, newest first
    assert history_on.delete("/api/search/history").json()["count"] == 0
    assert history_on.get("/api/search/history").json()["entries"] == []


MARKER = "zqxhistorymarkerzqx"


def test_history_never_reaches_an_export_or_a_diagnostics_bundle(history_on) -> None:
    """Q614: never exported. Negative space, measured on the bytes that leave."""
    history_on.put("/api/settings", json={"search_history_enabled": True})
    history_on.post("/api/search/history", json={"query": MARKER})
    assert MARKER in json.dumps(history_on.get("/api/search/history").json())  # it IS stored
    for fmt in ("csv", "json"):
        r = history_on.get("/api/articles/export", params={"query": "energy", "format": fmt})
        assert MARKER not in r.text and MARKER not in json.dumps(dict(r.headers))
    b = history_on.get("/api/diagnostics/debug-bundle")
    assert b.status_code == 200
    assert MARKER.encode() not in b.content


def test_only_the_history_module_reads_the_history_key() -> None:
    """Structural half of "never exported": nothing else can reach the entries."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src"
    readers = [p.relative_to(root).as_posix() for p in root.rglob("*.py")
               if "search.history" in p.read_text(encoding="utf-8")]
    assert readers == ["api/search_advanced.py"]


def test_near_default_is_a_stored_preference(history_on) -> None:
    try:
        assert history_on.put("/api/settings", json={"search_near_default": 4}).status_code == 200
        assert history_on.get("/api/search/facets").json()["near"]["default"] == 4
        assert history_on.put("/api/settings", json={"search_near_default": 5000}).status_code == 400
    finally:
        history_on.put("/api/settings", json={"search_near_default": 10})


def test_near_bounds_mirror_the_grammar() -> None:
    from src.config import app_settings
    from src.database import fts

    assert (app_settings._NEAR_MIN, app_settings._NEAR_MAX) == (fts.NEAR_MIN, fts.NEAR_MAX)
    assert app_settings.AppSettings().search_near_default == fts.NEAR_DEFAULT
