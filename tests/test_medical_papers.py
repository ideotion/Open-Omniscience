"""Medical papers beside the news (S07-01 S1, row 173 PR 4; R745, R750): what the analysis shows, and what it never does.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Papers subtab reads the analysed articles' own links and matches them against ``medical.db``. Mostly negative space:
the route sends no request and writes no file (a lane never fetched answers with every cited id counted, and no
``medical.db`` appears), a paper not kept is COUNTED and never listed (R750), a retracted record carries its class
and its notice, and the surface states the no-medical-advice line visibly in all twelve locales.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.medical import fetch as F
from src.medical import store as M
from src.versioned import store
from tests._app_engine import app_sqlite_engine

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "medical" / "pubmed_update_sample.xml"
NO_ADVICE = "This app never gives medical advice. A paper listed here is one your articles link to, not a recommendation."


@pytest.fixture
def medical(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")

    def _no_network(*_a, **_k):
        raise AssertionError("reading papers must never build a network session")

    monkeypatch.setattr(F, "_session", _no_network)
    try:
        yield tmp_path
    finally:
        store.dispose_all()


def _wanted(**kinds: set[str]) -> M.Wanted:
    w = M.Wanted()
    for k, vals in kinds.items():
        for v in vals:
            w.add(k, v)
    return w


def _apply_fixture(wanted: M.Wanted) -> None:
    store.create_lane(M.LANE)
    body = gzip.compress(FIXTURE.read_bytes())
    F.apply_body("pubmed25n1300.xml.gz", body, hashlib.md5(body, usedforsecurity=False).hexdigest(), wanted)


# --- the store ---------------------------------------------------------------------------------


def test_cited_papers_carry_their_class_and_notices_and_the_rest_is_counted(medical):
    _apply_fixture(_wanted(pmid={"90000001", "90000002", "90000003"}))
    cited = {
        1: _wanted(pmid={"90000001", "90000002"}, doi={"10.9999/never.kept"}),
        2: _wanted(doi={"10.9999/jir.2024.001"}),  # the same paper as PMID 90000001, named by its DOI
        3: _wanted(doi={"10.9999/preprint.3"}),
    }
    with store.lane_session(M.LANE) as s:
        out = M.papers_cited_by(s, cited)
    by = {p["pmid"]: p for p in out["papers"]}
    assert set(by) == {90000001, 90000002, 90000003}
    assert by[90000001]["provenance_class"] == "journal" and "erratum" in by[90000001]["notices"]
    assert by[90000001]["article_ids"] == [1, 2] and by[90000001]["cited_by"] == 2
    assert by[90000002]["provenance_class"] == "retracted" and "retraction" in by[90000002]["notices"]
    assert by[90000003]["provenance_class"] == "preprint"
    # Ordered by how many of the articles cite it, then by PMID: a count, never a score.
    assert [p["pmid"] for p in out["papers"]] == [90000001, 90000002, 90000003]
    # The DOI no file carried is COUNTED, never listed (R750).
    assert out["not_found"] == 1 and out["cited"] == out["found"] + 1
    assert all("score" not in k and "rank" not in k for p in out["papers"] for k in p)


def test_nothing_cited_lists_nothing(medical):
    store.create_lane(M.LANE)
    with store.lane_session(M.LANE) as s:
        assert M.papers_cited_by(s, {}) == {"papers": [], "cited": 0, "found": 0, "not_found": 0}


# --- the route ---------------------------------------------------------------------------------


@pytest.fixture
def client(medical):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.api.medical import router
    from src.database.models import Article, ArticleLink, Base, Source
    from src.database.session import get_db

    eng = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    make = sessionmaker(bind=eng, future=True)
    with make() as s:
        s.add(Source(id=1, name="Web", domain="w.test", source_type="news"))
        for aid in (1, 2, 3):
            s.add(Article(id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}", source_id=1, title="t",
                          hash=f"h{aid}", language="en", content="c", created_at=datetime.now(UTC)))
        links = {1: ["https://pubmed.ncbi.nlm.nih.gov/90000002/", "https://news.test/story"],
                 2: ["https://doi.org/10.9999/never.kept"], 3: ["https://news.test/other"]}
        for aid, urls in links.items():
            s.add_all([ArticleLink(article_id=aid, url=u, normalized_url=u, link_type="external") for u in urls])
        s.commit()

    def _db():
        with make() as s:
            yield s

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_a_lane_never_fetched_counts_every_cited_id_and_creates_no_file(client, medical):
    assert not store.lane_path(M.LANE).exists()
    d = client.get("/api/medical/corpus-papers", params={"article_ids": "1,2,3"}).json()
    assert (d["n_articles"], d["articles_citing"], d["cited"], d["found"], d["not_found"]) == (3, 2, 2, 0, 2)
    assert d["papers"] == [] and d["last_file"] is None and d["gap"] == F.GAP
    assert not store.lane_path(M.LANE).exists(), "a read never creates medical.db"


def test_the_route_lists_a_kept_retracted_paper_beside_the_count_of_the_rest(client, medical):
    _apply_fixture(_wanted(pmid={"90000002"}))
    d = client.get("/api/medical/corpus-papers", params={"article_ids": "1,2,3"}).json()
    assert [(p["pmid"], p["provenance_class"], p["article_ids"]) for p in d["papers"]] == [(90000002, "retracted", [1])]
    assert (d["found"], d["not_found"]) == (1, 1)
    assert d["last_file"]["name"] == "pubmed25n1300.xml.gz"
    assert "Nothing is requested from the network" in d["method"]


# --- the surface -------------------------------------------------------------------------------


def test_the_subtab_states_no_medical_advice_and_the_gap_visibly_and_links_nowhere():
    html = (ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "static" / "app-medical.js").read_text(encoding="utf-8")
    assert 'data-tab="papers"' in html and 'id="an-papers"' in html
    # Both lines render in a VISIBLE caveat line, never behind a toggle or a hover.
    assert f'card-caveat" style="margin-top:0">${{esc(_t("{NO_ADVICE}"))}}' in js
    assert 'class="card-caveat">${esc(_t("Only papers NLM revised recently' in js
    # Every class has its own badge with its own words; colour is never the only signal.
    for label in ("Journal record", "Preprint", "Retracted", "Retraction notice", "Expression of concern"):
        assert f'"{label}"' in js
    assert "href=" not in js.split("renderAnPapers")[0].split("Papers subtab")[1], "no outbound link from a paper"
    analysis = (ROOT / "src" / "static" / "app-analysis.js").read_text(encoding="utf-8")
    assert 'key === "papers"' in analysis


@pytest.mark.parametrize("lang", ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"])
def test_the_no_medical_advice_line_ships_in_every_locale(lang):
    d = json.loads((ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
    assert d.get(NO_ADVICE), lang
    if lang != "en":
        assert d[NO_ADVICE] != NO_ADVICE, f"{lang} carries the English line untranslated"


# --- the freshness block (K13, R751(a)) ----------------------------------------------------------


def test_a_fetch_records_its_k13_block_with_counts_and_no_paper_id(medical, monkeypatch):
    from src.api.medical import _record_for_k13
    from src.monitoring import kpi as K

    monkeypatch.setattr(K, "_coverage_path", lambda: medical / "keyword-coverage.json")
    _apply_fixture(_wanted(pmid={"90000002"}))
    _record_for_k13({"listed": 3, "remaining": 2, "applied": [{"name": "pubmed25n1300.xml.gz"}], "failed": None,
                     "stopped": False, "coverage": {"cited": 2, "cited_found": 1, "cited_not_found": 1}})
    text = (medical / "vertical-medical.json").read_text(encoding="utf-8")
    assert "90000002" not in text and "10.9999" not in text
    rec = json.loads(text)
    assert (rec["applied"], rec["papers"], rec["by_class"]["retracted"], rec["last_file"]) == (1, 1, 1, "pubmed25n1300.xml.gz")
    assert rec["coverage"]["cited_not_found"] == 1
