"""S05-11 S4 — the dossier seed: one Wikidata item, the rails joined to it, the corpus passport.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief's acceptance line: «a QID page renders from fixture rows with its rail list and the
corpus passport (A-1).» Proven on synthetic rows: three routes (a named entity, a keyword, a
place mention) join three articles on three channels (press, Wikipedia, law); a name two items
share joins NEITHER; the rails the seed does not join are named; the passport counts what is
there AND what is missing. No test here opens a socket.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import equivalence
from src.database.models import (
    Article,
    ArticleEntity,
    ArticleKeyword,
    ArticleMentionedPlace,
    Base,
    Keyword,
    Place,
    Source,
    WikidataItem,
)
from src.entities import dossier as DO
from tests.js_source_helper import read_static

ZED = "Q999999001"
ZED_PLACE = "node/9000000001"


@pytest.fixture
def rings(monkeypatch):
    rs = (
        equivalence.Ring(id="zedport", qid=ZED,
                         members=(("en", "zedport"), ("fr", "zedport-sur-mer"), ("ar", "زدبورت"))),
        equivalence.Ring(id="mercury-planet", qid="Q999999020", members=(("en", "mercury"),)),
        equivalence.Ring(id="mercury-element", qid="Q999999021", members=(("en", "mercury"),)),
    )
    equivalence.invalidate_ring_caches()
    monkeypatch.setattr(equivalence, "load_rings", lambda: rs)
    equivalence._index.cache_clear()
    equivalence._multi_index.cache_clear()
    equivalence._member_languages.cache_clear()
    yield
    monkeypatch.undo()
    equivalence.invalidate_ring_caches()


@pytest.fixture
def lanes(tmp_path, monkeypatch):
    """A fresh data directory with no lane in it; lanes disposed on the way in and out."""
    from src.versioned import store

    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        yield tmp_path
    finally:
        store.dispose_all()


@pytest.fixture
def db():
    # One shared connection, usable from the test client's worker thread too.
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def _source(db, domain, *, country=None, source_type=None):
    s = Source(name=domain, domain=domain, country=country, source_type=source_type)
    db.add(s)
    db.flush()
    return s


def _article(db, src, text, *, lang="en", when=None):
    art = Article(url=f"https://{src.domain}/{hash(text)}", canonical_url=f"https://{src.domain}/{hash(text)}",
                  source_id=src.id, title=text[:20], content=text, language=lang, published_at=when,
                  hash=hashlib.sha256(text.encode()).hexdigest())
    db.add(art)
    db.flush()
    return art


@pytest.fixture
def seeded(db, rings):
    press = _source(db, "zz.example", country="fr")
    wiki = _source(db, "fr.wikipedia.org")
    law = _source(db, "law.zz.local", country="de", source_type="legal")
    # Route 1: a named entity whose name resolves to exactly this item.
    a1 = _article(db, press, "Zedport harbour reopened.", when=datetime(2026, 3, 1))
    db.add(ArticleEntity(article_id=a1.id, name="Zedport", entity_class="organization", mentions=2))
    # Route 2: a keyword that is this item's French name, in French.
    a2 = _article(db, wiki, "Zedport-sur-Mer est une ville.", lang="fr", when=datetime(2026, 5, 9))
    kw = Keyword(term="Zedport-sur-Mer", normalized_term="zedport-sur-mer", language="fr")
    db.add(kw)
    db.flush()
    db.add(ArticleKeyword(article_id=a2.id, keyword_id=kw.id))
    # Route 3: a place mention that resolves to a Place carrying this item.
    db.add(Place(id=ZED_PLACE, qid=ZED, kind="city", name="Zedport", country="zz"))
    a3 = _article(db, law, "Ordinance for the port of Zedport.", lang=None)
    db.add(ArticleMentionedPlace(article_id=a3.id, name="Zedport", country="zz", kind="city", mentions=1))
    # A name two items share joins NEITHER (the several-senses refusal).
    a4 = _article(db, press, "Mercury rose today.", when=datetime(2026, 4, 1))
    db.add(ArticleEntity(article_id=a4.id, name="Mercury", entity_class="organization", mentions=1))
    # The French keyword tagged ENGLISH is not this item's English name, so it does not join.
    a5 = _article(db, press, "An English page that says zedport-sur-mer.")
    kw_en = Keyword(term="zedport-sur-mer", normalized_term="zedport-sur-mer", language="en")
    db.add(kw_en)
    db.flush()
    db.add(ArticleKeyword(article_id=a5.id, keyword_id=kw_en.id))
    db.commit()
    return {"a1": a1.id, "a2": a2.id, "a3": a3.id, "a4": a4.id, "a5": a5.id}


def _rail(d, key):
    return next(r for r in d["rails"] if r["key"] == key)


def test_a_QID_page_renders_from_fixture_rows_with_its_rails_and_passport(db, seeded, lanes):
    d = DO.qid_dossier(db, ZED, "en")
    # The three routes each join exactly their article; the union is the three.
    assert {k: v["articles"] for k, v in d["routes"].items()} == {"entities": 1, "keywords": 1, "places": 1}
    assert d["routes"]["entities"]["matched_on"] == ["Zedport"]
    assert d["routes"]["keywords"]["matched_on"] == ["zedport-sur-mer"]
    assert sorted(d["article_ids"]) == sorted([seeded["a1"], seeded["a2"], seeded["a3"]])
    assert d["article_ids_bounded"] is False
    # The rail list: joined rails in order, each with its own count, then the named others.
    assert [r["key"] for r in d["rails"]] == list(DO.JOINED_RAILS)
    assert _rail(d, "news")["articles"] == 1 and _rail(d, "news")["by_channel"] == {"web": 1}
    assert _rail(d, "wikipedia")["articles"] == 1
    assert _rail(d, "law")["articles"] == 1
    assert _rail(d, "places")["places"] == [
        {"id": ZED_PLACE, "name": "Zedport", "kind": "city", "country": "zz", "articles": 1}]
    assert [r["key"] for r in d["not_joined"]] == ["markets", "agenda", "law_versions"]
    assert all(r["reason"] for r in d["not_joined"])
    # The passport (A-1): n articles · sources · countries · languages · date span, gaps counted.
    p = d["passport"]
    assert (p["articles"], p["sources"]) == (3, 3)
    assert (p["countries"], p["no_country"]) == (2, 1)
    assert [c["code"] for c in p["country_codes"]] == ["de", "fr"]
    assert (p["languages"], p["no_language"]) == (2, 1)
    assert (p["first"], p["last"], p["undated"]) == ("2026-03-01", "2026-05-09", 1)
    assert d["method"] and d["caveat"]


def test_a_name_two_items_share_joins_neither(db, seeded, lanes):
    for q in ("Q999999020", "Q999999021"):
        d = DO.qid_dossier(db, q, "en")
        assert seeded["a4"] not in d["article_ids"]
        assert d["routes"]["entities"]["articles"] == 0


def test_a_keyword_joins_only_in_the_language_the_ring_names_it_in(db, seeded, lanes):
    d = DO.qid_dossier(db, ZED, "en")
    assert seeded["a5"] not in d["article_ids"]


def test_an_item_the_corpus_never_mentions_still_lists_every_rail_with_zeros(db, rings, lanes):
    d = DO.qid_dossier(db, "Q42", "en")
    assert d["passport"]["articles"] == 0 and d["article_ids"] == []
    assert [r["key"] for r in d["rails"]] == list(DO.JOINED_RAILS)
    assert _rail(d, "wikipedia")["lane"]["reason"] == "lane-never-run"
    assert _rail(d, "map")["lane"]["reason"] == "lane-never-run"
    assert d["item"]["status"] == "not-cached"


def test_the_item_label_is_the_readers_language_first_then_english(db, rings, lanes):
    db.add(WikidataItem(qid=ZED, status="ok", labels_json='{"en": "Zedport", "ar": "زدبورت"}',
                        descriptions_json='{"en": "a synthetic port"}'))
    db.commit()
    ar = DO.qid_dossier(db, ZED, "ar")["item"]
    assert (ar["label"], ar["label_lang"]) == ("زدبورت", "ar")
    assert (ar["description"], ar["description_lang"]) == ("a synthetic port", "en")
    assert DO.qid_dossier(db, ZED, "de")["item"]["label_lang"] == "en"


def test_not_a_QID_is_refused():
    assert DO.qid_dossier(None, "Paris", "en") is None


def test_the_map_rail_lists_the_osm_lanes_objects_tagged_with_the_item(db, rings, lanes):
    from src.osm.lane_models import osm_objects_table as T
    from src.osm.tags import column_name
    from src.versioned.store import create_lane, lane_session

    create_lane("osm")
    with lane_session("osm") as lane:
        lane.execute(T.insert().values(osm_type="n", osm_id=9000000001, country_alpha3="ZZZ",
                                       kind="place", **{column_name("wikidata"): ZED,
                                                        column_name("name"): "Zedport"}))
        lane.execute(T.insert().values(osm_type="n", osm_id=9000000002, country_alpha3="ZZZ",
                                       kind="poi", **{column_name("wikidata"): "Q1"}))
    m = _rail(DO.qid_dossier(db, ZED, "en"), "map")["lane"]
    assert m["available"] is True
    assert [(o["osm"], o["name"]) for o in m["objects"]] == [("n9000000001", "Zedport")]


def test_the_passport_takes_a_select_never_an_id_list(db, seeded):
    from src.analytics.passport import corpus_passport

    p = corpus_passport(db, select(Article.id))
    assert p["articles"] == 5 and p["undated"] == 2


def test_the_route_answers_and_refuses_a_non_QID(db, seeded, lanes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import entities as E
    from src.database.session import get_db

    app = FastAPI()
    app.include_router(E.router)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    r = c.get("/api/entities/dossier", params={"qid": ZED.lower(), "lang": "fr"})
    assert r.status_code == 200 and r.json()["passport"]["articles"] == 3
    assert c.get("/api/entities/dossier", params={"qid": "Paris"}).status_code == 400


# --------------------------------------------------------------------------- #
#  the page
# --------------------------------------------------------------------------- #


def test_the_page_is_a_dialog_with_a_visible_caveat_and_no_inline_handlers():
    html = read_static("index.html")
    assert '<dialog id="dossier"' in html
    block = html.split('<dialog id="dossier"', 1)[1].split("</dialog>", 1)[0]
    assert "onclick=" not in block
    assert '<script src="/static/app-dossier.js"></script>' in html
    assert '"/static/app-dossier.js"' in read_static("sw.js")
    js = read_static("app-dossier.js")
    for needle in ("/api/entities/dossier", "card-caveat", "d.not_joined", "passportLine", "d.passport"):
        assert needle in js, needle


def test_the_dossier_opens_from_the_place_card_and_the_who_facet():
    an = read_static("app-analysis.js")
    assert "pc-dossier" in an and "openDossier(" in an
    assert "an-dossier" in an


def test_an_acronym_stored_upper_case_still_joins(db, rings, lanes, monkeypatch):
    """Acronym keywords and entities are stored UPPER-case while ring members are lower-case."""
    rs = (equivalence.Ring(id="usa", qid="Q999999030", members=(("en", "usa"), ("ru", "сша"))),)
    monkeypatch.setattr(equivalence, "load_rings", lambda: rs)
    equivalence._index.cache_clear()
    equivalence._multi_index.cache_clear()
    equivalence._member_languages.cache_clear()
    src = _source(db, "acr.example", country="us")
    a = _article(db, src, "The USA acted.")
    b = _article(db, src, "США сделали шаг.", lang="ru")
    kw = Keyword(term="USA", normalized_term="USA", language="en")
    kw_ru = Keyword(term="США", normalized_term="США", language="ru")
    db.add_all([kw, kw_ru])
    db.flush()
    db.add(ArticleKeyword(article_id=a.id, keyword_id=kw.id))
    db.add(ArticleKeyword(article_id=b.id, keyword_id=kw_ru.id))
    c = _article(db, src, "USA again.")
    db.add(ArticleEntity(article_id=c.id, name="USA", entity_class="organization", mentions=1))
    db.commit()
    d = DO.qid_dossier(db, "Q999999030", "en")
    assert d["routes"]["keywords"]["articles"] == 2
    assert d["routes"]["entities"]["articles"] == 1
    assert sorted(d["article_ids"]) == sorted([a.id, b.id, c.id])
