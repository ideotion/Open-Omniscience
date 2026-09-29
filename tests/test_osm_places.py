"""Places from the OSM lane: the name index, the facet, the object card, the geocoder (S05-04 S5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q817 = a: notable places become Places, every other place a row behind the "Places" facet.
Q820 = a: a local geocoder for the countries read, its scope disclosed, never an external
service. Q823 ⛔: nothing here becomes a corpus Article or leaves the machine.

The fixture's literals (``scripts/make_osm_fixture.py``): Fixture Land (relation 100) holds the
cafe (node 5, ``name:fr`` "Cafe du Test"), the bakery (6), the pharmacy (7), Fixtureville
(node 8, ``place=village``, ``name:ar``), a road (way 12), a building carrying the one address
"1 Fixture Road 00000 Fixtureville" (way 13) and a site relation (101); the Outside Cafe (node 9)
lies beyond the border. The border ways (10, 11) carry ``boundary=administrative`` too.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.osm import ingest
from src.osm import places as P
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE, generator
from tests.js_source_helper import function_source

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


@pytest.fixture
def db():
    from src.database.models import Base

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def _objects(result):
    return [it["object"] for it in result["items"]]


# --------------------------------------------------------------------------- #
#  The name index and the facet                                                #
# --------------------------------------------------------------------------- #


def test_the_ingest_builds_the_index_and_says_what_it_took(osm_lane_dir):
    rep = ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    # Named: the cafe, bakery, pharmacy, village, the site relation, the country relation.
    assert rep.search_index == {"alpha3": "ZZZ", "names": 6, "addresses": 1, "addresses_no_point": 0}
    assert P.index_state()[0]["indexed"] is True


def test_a_place_is_found_by_any_name_osm_gives_it(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert _objects(P.search_names("cafe du")) == ["node/5"], "the name:fr spelling"
    assert _objects(P.search_names("قرية")) == ["node/8"], "the name:ar spelling"
    assert _objects(P.search_names("Fixturev")) == ["node/8"], "the last word is a prefix"


def test_the_facet_holds_places_only_and_nothing_outside_the_border(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    found = _objects(P.search_names("fixture", limit=50))
    assert "way/12" not in found and "way/13" not in found, "a road or a building listed as a place"
    assert "way/10" not in found and "way/11" not in found, "a border way listed as a place"
    assert not P.search_names("outside")["items"], "the cafe beyond the border was indexed"


def test_a_query_is_never_read_as_fts_syntax(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    for q in ('fixture" OR "x', "NEAR(cafe", "cafe*", "-cafe", "AND"):
        P.search_names(q)                   # no OperationalError: every token is quoted
        P.geocode(q)


def test_an_index_from_an_earlier_ingest_reads_as_not_matching_and_is_rebuilt(osm_lane_dir):
    from src.osm.lane_models import OsmSearchIndex
    from src.versioned import store

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        s.query(OsmSearchIndex).one().basis_ingest = "2000-01-01T00:00:00+00:00"
    assert P.index_state()[0]["indexed"] is False
    assert list(P.refresh_indexes()) == ["ZZZ"]
    assert P.index_state()[0]["indexed"] is True
    assert P.search_names("bakery")["total"] == 1, "a rebuild doubled or dropped the rows"


def test_no_lane_no_index_no_error(osm_lane_dir):
    from src.versioned import store

    assert P.search_names("cafe") == {"items": [], "total": 0}
    assert P.index_state() == []
    assert not store.lane_exists("osm"), "asking created the lane"


# --------------------------------------------------------------------------- #
#  The object card                                                             #
# --------------------------------------------------------------------------- #


def test_the_object_card_carries_every_tag_the_extract_had(osm_lane_dir):
    g = generator()
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    card = P.object_card("node/5")
    want = next(t for i, _la, _lo, t in g.LANE_NODES if i == 5)
    assert {x["key"]: x["value"] for x in card["tags"]} == want
    assert card["tag"] == "amenity=cafe" and card["place_id"] is None, "a cafe with no wikidata is not a Place"
    assert card["caveat"] == P.OBJECT_CAVEAT


def test_a_relation_has_no_point_and_a_notable_object_names_its_place(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert P.object_card("relation/101")["point"] is None, "a relation read as a point at (0, 0)"
    assert P.object_card("node/8")["place_id"] == "node/8"
    assert P.object_card("way/10")["place_id"] is None, "a border way offered as a Place"
    assert P.object_card("node/999") is None


def test_the_object_route(osm_lane_dir):
    from src.api.main import app

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    c = TestClient(app)
    assert c.get("/api/osm/objects/node/5").json()["name"] == "Fixture Cafe"
    assert c.get("/api/osm/objects/node/999").status_code == 404
    assert c.get("/api/osm/objects/thing/5").status_code == 400
    assert _objects(c.get("/api/osm/search", params={"q": "bakery"}).json()) == ["node/6"]


# --------------------------------------------------------------------------- #
#  The geocoder (Q820)                                                         #
# --------------------------------------------------------------------------- #


def test_an_address_in_a_country_read_is_located_at_its_objects_point(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    got = P.geocode("1 Fixture Road, Fixtureville")
    assert got["status"] == "located"
    (r,) = got["results"]
    assert r["object"] == "way/13" and r["address"] == "1 Fixture Road 00000 Fixtureville"
    assert r["lat"] == pytest.approx(0.165) and r["lon"] == pytest.approx(0.165)
    assert got["scope"] == P.GEOCODER_SCOPE == "Addresses outside your OpenStreetMap countries are not located."


def test_NEGATIVE_SPACE_an_address_outside_the_countries_read_is_the_disclosed_gap(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    got = P.geocode("10 Downing Street, London")
    assert got["status"] == "not-located" and got["results"] == [], "a guess"
    assert got["scope"] == P.GEOCODER_SCOPE
    assert [c["alpha3"] for c in got["countries"]] == ["ZZZ"], "the scope names what was searched"


def test_a_near_miss_is_not_located_never_the_nearest_house(osm_lane_dir):
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert P.geocode("2 Fixture Road")["status"] == "not-located", "house 2 answered with house 1"
    assert P.geocode("1 Fixture Lane")["status"] == "not-located"


def test_no_country_read_says_so(osm_lane_dir):
    got = P.geocode("1 Fixture Road")
    assert got["status"] == "no-country" and got["countries"] == []


def test_search_and_geocoder_resolve_ZERO_names(osm_lane_dir, monkeypatch):
    from src.ingest import clear_kill_switch
    from src.ingest.airplane import install_airplane_socket_guard

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    clear_kill_switch()
    install_airplane_socket_guard()
    seen: list = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (seen.append(a), real(*a, **k))[1])
    P.search_names("cafe")
    P.geocode("1 Fixture Road")
    P.object_card("node/5")
    assert seen == [], f"a lookup resolved {len(seen)} name(s)"


def test_the_geocode_route(osm_lane_dir):
    from src.api.main import app

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    body = TestClient(app).get("/api/osm/geocode", params={"q": "00000 Fixtureville"}).json()
    assert body["status"] == "located" and body["results"][0]["object"] == "way/13"


# --------------------------------------------------------------------------- #
#  Notable places become Places (Q817), and nothing becomes an Article (Q823)  #
# --------------------------------------------------------------------------- #


def test_notable_objects_become_places_their_border_ways_do_not(osm_lane_dir, db):
    from src.database.models import Article, Place
    from src.entities.places import materialise_notable

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    got = materialise_notable(db)
    assert got["places"] == 2 and got["created"] == 2 and got["border_ways"] == 2
    village = db.get(Place, "node/8")
    assert village.kind == "village" and village.country_alpha3 == "ZZZ" and village.country == "zz"
    assert json.loads(village.names_json) == {"ar": "قرية الاختبار"}
    assert village.geometry_ref == "osm.db:node/8"
    country = db.get(Place, "relation/100")
    assert country.kind == "boundary=administrative" and country.lat is None, "a relation given a point"
    assert db.query(Article).count() == 0 and village.article_id is None, "Q823: a Place became an Article"


def test_a_place_the_gazetteer_resolved_keeps_its_gazetteer_facts(osm_lane_dir, db):
    from src.database.models import Place
    from src.entities.places import materialise_notable

    db.add(Place(id="node/8", name="Fixtureville (gazetteer)", kind="village", country="zz",
                 gazetteer_vintage="2026-01", lat=0.1, lon=0.1, population=12))
    db.commit()
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    materialise_notable(db)
    p = db.get(Place, "node/8")
    assert (p.name, p.lat, p.population) == ("Fixtureville (gazetteer)", 0.1, 12)
    assert p.geometry_ref == "osm.db:node/8", "the lane still records where its geometry lives"


def test_the_place_card_of_a_notable_object_says_where_it_came_from(osm_lane_dir, db):
    from src.entities.places import OSM_NOTABLE_CAVEAT, materialise_notable, place_card

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    materialise_notable(db)
    card = place_card(db, "node/8", "ar")
    assert card["title"] == {"name": "قرية الاختبار", "source": "osm", "lang": "ar"}
    assert card["origin"] == "osm-lane" and card["caveat"] == OSM_NOTABLE_CAVEAT
    assert card["osm"] == {"held": True, "tag": "place=village", "vintage": None, "country_name": "Fixture Land"}


def test_the_omnibar_places_group_lists_lane_rows_once(osm_lane_dir, db):
    from src.api.search_omni import _places_group
    from src.entities.places import materialise_notable

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    materialise_notable(db)
    g = _places_group(db, "fixture")
    places = [it["id"] for it in g["items"]]
    rows = _objects(g["osm"])
    assert "node/8" in places and "node/8" not in rows, "a Place listed twice"
    assert rows and set(rows) <= {"node/5", "node/6", "node/7", "relation/101", "relation/100"}
    assert g["osm"]["total"] == 6, "the index's own total, stated"


# --------------------------------------------------------------------------- #
#  The UI                                                                      #
# --------------------------------------------------------------------------- #


def test_the_geocoder_panel_states_its_scope_always_and_asks_no_consent():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    tab = html.partition('id="tab-timemap"')[2].partition('<div class="tab-page"')[0]
    assert '<section class="panel" id="osm-geocoder" hidden>' in tab
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    scope = function_source(js, "_osmGeoScope")
    assert "Addresses outside your OpenStreetMap countries are not located." in scope
    locate = function_source(js, "osmLocate")
    assert "/api/osm/geocode" in locate and "ensureOnline" not in locate, "a local lookup asked for the network"
    render = function_source(js, "_osmGeoRender")
    assert "Nothing nearby is offered in its place." in render
    # The answer is re-drawn on a language switch (found in the 2026-09-29 Chromium walk).
    assert "_osmGeoRender();" in js.partition('document.addEventListener("oo:langchange"')[2].partition("});")[0]


def test_the_object_card_shows_its_caveat_and_every_tag():
    js = (STATIC / "app-analysis.js").read_text(encoding="utf-8")
    render = function_source(js, "renderOsmObjectCard")
    assert 'class="card-caveat"' in render and "d.tags" in render
    shell = (STATIC / "app-shell.js").read_text(encoding="utf-8")
    assert "openOsmObjectCard(it.object)" in shell
    on = (STATIC / "oo-on.js").read_text(encoding="utf-8")
    for name in ("openOsmObjectCard", "openPlaceCard"):
        assert f'"{name}"' in on, name


# --------------------------------------------------------------------------- #
#  Stale index rows (found by the Opus review of PR 1223)                      #
# --------------------------------------------------------------------------- #


def test_a_stale_index_row_never_joins_an_unrelated_object(osm_lane_dir):
    """SQLite reuses row ids after a re-ingest deletes a country's objects. An address row left
    over from an interrupted ingest must not be shown at the point of whatever holds its id."""
    from sqlalchemy import text

    from src.versioned import store

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        oid = s.execute(text("SELECT object_id FROM osm_addresses LIMIT 1")).scalar()
        s.execute(text("INSERT INTO osm_addresses (address, alpha3, object_id) VALUES ('9 Ghost Lane', 'QQQ', :i)"), {"i": oid})
    body = P.geocode("9 Ghost Lane")
    assert body["status"] == "not-located" and body["total"] == 0, "a row of a country never indexed answered"


def test_a_reingest_clears_the_countrys_indexes_before_its_objects_go(osm_lane_dir, monkeypatch):
    from sqlalchemy import text

    from src.osm import reader as R
    from src.versioned import store

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")

    class Stop(Exception):
        pass

    def scan_then_stop(self, bbox, locations):
        raise Stop()

    with monkeypatch.context() as m:
        m.setattr(R.PythonExtract, "scan", scan_then_stop)
        with pytest.raises(Stop):
            ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        for table in ("osm_names", "osm_addresses", "osm_view_cells", "osm_rtree"):
            assert s.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
