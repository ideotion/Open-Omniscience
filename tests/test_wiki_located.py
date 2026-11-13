"""S06-03 S2 + S3 (R17 step 4; Q819, Q820; R678): infobox addresses, located only in the local OSM index.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The spine is NEGATIVE SPACE: what must never become a point. An infobox about a person (anywhere on the page), an infobox of a type
nobody listed, a string that only looks like an address, an address the index answers ambiguously, an address in a country not ingested.
Each must yield no point AND the right counter, never a silent drop and never a zero standing in for "nothing looked".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.versioned.models import VersionedEntity, VersionedRevision
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import located as L
from src.wiki.coverage import edition_coverage
from src.wiki.lane_models import WikiWarmPage
from tests import _osm_lane_helpers

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

T0 = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)

HALL = """{{Infobox building
| name = Fixture Hall
| address = 2 Fixture Road<ref>{{cite web|url=https://example.org}}</ref>, [[Fixtureville|Fixtureville]], {{nowrap|Fixtureland}}
| coordinates = {{coord|48|51|29|N|2|17|40|E}}
}}
'''Fixture Hall''' is a hall."""

PERSON = """{{Infobox person
| name = A. Person
| address = 9 Private Lane, Fixtureville
}}"""

PERSON_THEN_BUILDING = """{{Infobox person|name=A. Person}}
{{Infobox building|address=9 Private Lane}}"""


# --------------------------------------------------------------------------- #
# The pure extractor.
# --------------------------------------------------------------------------- #
def test_a_place_infobox_offers_its_address_cleaned_and_its_coordinate():
    offer = L.page_addresses("en", HALL)
    assert offer["type"] == "infobox building"
    assert offer["candidates"] == [("address", "2 Fixture Road, Fixtureville, Fixtureland")]
    lat, lon = offer["coord"]
    assert round(lat, 3) == 48.858 and round(lon, 3) == 2.294


@pytest.mark.parametrize("text", [PERSON, PERSON_THEN_BUILDING, "{{Infobox building|address=9 Private Lane}}\n{{Infobox person|name=A}}", "{{Infobox officeholder|address=1 Main St}}", "{{Персона|адрес=ул. Ленина, 5}}"])
def test_a_page_with_a_person_infobox_is_never_read(text):
    edition = "ru" if "Персона" in text else "en"
    assert L.page_addresses(edition, text) == {"skip": "about_a_person"}


def test_an_unlisted_infobox_type_fails_closed():
    assert L.page_addresses("en", "{{Infobox settlement|address=1 Main St}}") == {"skip": "type_not_on_the_list"}
    # A type listed for ANOTHER edition is not listed for this one.
    assert L.page_addresses("fr", "{{Infobox building|address=1 Main St}}") == {"skip": "type_not_on_the_list"}


def test_no_listed_type_is_a_person_type():
    assert not [t for t in L._ALL_PLACE_TYPES if L._is_person_type(t)]
    assert set(L.PLACE_TYPES) == set(L.ADDRESS_KEYS) and len(L.PLACE_TYPES) == 12


@pytest.mark.parametrize(
    "edition,text,want",
    [
        ("fr", "{{Infobox Bâtiment|adresse=3 rue Fixture}}", [("adresse", "3 rue Fixture")]),
        ("de", "{{Infobox Unternehmen|Anschrift=Fixturestraße 4<br />Berlin}}", [("anschrift", "Fixturestraße 4, Berlin")]),
        ("es", "{{Ficha de edificio|dirección=Calle Mayor 3}}", [("dirección", "Calle Mayor 3")]),
        ("pt", "{{Info/Empresa|endereço=Rua Fixture, 10}}", [("endereço", "Rua Fixture, 10")]),
        ("ru", "{{Здание|адрес=ул. Ленина, 5}}", [("адрес", "ул. Ленина, 5")]),
        ("id", "{{Infobox perusahaan|alamat=Jalan Fixture 7}}", [("alamat", "Jalan Fixture 7")]),
    ],
)
def test_the_editions_own_type_and_key_names(edition, text, want):
    assert L.page_addresses(edition, text)["candidates"] == want


def test_an_infobox_with_no_address_field_offers_nothing():
    assert L.page_addresses("en", "{{Infobox building|name=Hall|location=Fixtureville}}") == {"none": True}
    assert L.page_addresses("en", "No infobox at all, though 2 Fixture Road is mentioned.") == {"none": True}


def test_trailing_parts_drop_one_at_a_time_and_the_street_part_never_does():
    assert L.variants("2 Fixture Road, Fixtureville, Fixtureland") == [
        "2 Fixture Road, Fixtureville, Fixtureland", "2 Fixture Road, Fixtureville", "2 Fixture Road",
    ]
    assert L.variants("Fixture Road, Fixtureville") == [], "a value with no number is never looked up"
    assert L.variants("ул. Ленина, 5") == ["ул. Ленина, 5"], "dropping the number would look up a bare street"


def test_coord_reads_decimal_and_dms_and_refuses_nonsense():
    assert L.page_coordinate("{{coord|40.4|-3.7|display=title}}") == (40.4, -3.7)
    lat, lon = L.page_coordinate("{{Coord|33|52|S|151|12|E}}")
    assert round(lat, 3) == -33.867 and round(lon, 2) == 151.2
    assert L.page_coordinate("{{coord|95|10}}") is None
    assert L.page_coordinate("{{coord|north|east}}") is None


# --------------------------------------------------------------------------- #
# The locator, against a geocoder written by hand.
# --------------------------------------------------------------------------- #
def _geo(table):
    calls = []

    def geocode(q, limit=5):
        calls.append(q)
        if table == "no-country":
            return {"status": "no-country", "results": [], "total": 0, "countries": []}
        res = table.get(q, [])
        return {"status": "located" if res else "not-located", "results": res, "total": len(res),
                "countries": [{"alpha3": "FXL", "vintage": "2026-10-01T00:00:00+00:00"}]}

    geocode.calls = calls
    return geocode


def _hit(lat, lon, obj="way/1"):
    return {"address": "2 Fixture Road 75000 Fixtureville", "lat": lat, "lon": lon, "object": obj, "name": None, "country": "FXL"}


def test_located_after_dropping_the_country_with_its_provenance():
    geo = _geo({"2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)]})
    out = L.resolve("2 Fixture Road, Fixtureville, Fixtureland", geo)
    assert out["status"] == "located" and out["query"] == "2 Fixture Road, Fixtureville"
    assert out["osm_object"] == "way/1" and out["osm_vintage"].startswith("2026-10-01")
    assert geo.calls == ["2 Fixture Road, Fixtureville, Fixtureland", "2 Fixture Road, Fixtureville"]


def test_a_building_and_its_entrance_are_one_place_but_two_far_apart_are_ambiguous():
    near = _geo({"2 Fixture Road": [_hit(48.85, 2.35, "way/1"), _hit(48.8505, 2.3502, "node/2")]})
    assert L.resolve("2 Fixture Road", near)["status"] == "located"
    far = _geo({"2 Fixture Road": [_hit(48.85, 2.35), _hit(43.3, 5.4)]})
    assert L.resolve("2 Fixture Road", far) == {"status": "ambiguous", "answers": 2}
    many = _geo({"2 Fixture Road": [_hit(48.85, 2.35)] * 6})
    assert L.resolve("2 Fixture Road", many)["status"] == "ambiguous"


def test_not_found_and_no_country_are_different_answers():
    assert L.resolve("2 Fixture Road", _geo({})) == {"status": "not_located"}
    assert L.resolve("2 Fixture Road", _geo("no-country")) == {"status": "no_osm_country"}
    assert L.resolve("Fixture Road", _geo({})) == {"status": "no_house_number"}


def test_outside_is_claimed_only_from_a_known_coordinate_outside_every_box():
    boxes = [(41.0, -5.0, 51.0, 10.0)]
    assert L.outside_every_country((-33.9, 151.2), boxes) is True
    assert L.outside_every_country((48.8, 2.3), boxes) is False
    assert L.outside_every_country(None, boxes) is False
    assert L.outside_every_country((-33.9, 151.2), []) is False


# --------------------------------------------------------------------------- #
# The scan over a real temp lane, the counters, and the coverage block.
# --------------------------------------------------------------------------- #
@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    L.reset()
    create_lane("wiki")
    try:
        with lane_session("wiki") as s:
            yield s
    finally:
        L.reset()
        dispose_all()


def _page(s, edition, title, text, n):
    e = VersionedEntity(external_id=f"{edition}:#{n}", language=edition, title=title)
    s.add(e)
    s.flush()
    s.add(VersionedRevision(entity_id=e.id, revision_ref=str(100 + n), content_hash=f"h{n}", content=text, byte_size=len(text)))


@pytest.fixture
def scope(monkeypatch):
    def set_scope(signature, boxes, geocoder):
        monkeypatch.setattr(L, "_osm_scope", lambda: (signature, boxes))
        monkeypatch.setattr("src.osm.places.geocode", geocoder)

    return set_scope


def test_the_report_places_only_what_it_located_and_counts_everything_else(lane, scope):
    _page(lane, "en", "Fixture Hall", HALL, 1)
    _page(lane, "en", "A. Person", PERSON, 2)
    _page(lane, "en", "Far Hall", "{{Infobox building|address=7 Far Street}} {{coord|-33.9|151.2}}", 3)
    _page(lane, "en", "Twin Hall", "{{Infobox building|address=5 Twin Road}}", 4)
    _page(lane, "en", "Vague Hall", "{{Infobox building|address=Somewhere, Fixtureville}}", 5)
    lane.add(WikiWarmPage(edition="fr", page_id=9, title="Salle", latest_revid=9, latest_text="{{Infobox Bâtiment|adresse=3 rue Fixture}}"))
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [(41.0, -5.0, 51.0, 10.0)], _geo({
        "2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)],
        "5 Twin Road": [_hit(48.85, 2.35), _hit(45.0, 1.0)],
        "3 rue Fixture": [_hit(48.86, 2.36, "node/3")],
    }))
    rep = L.located_report(lane, budget=5.0)
    assert rep["measured"] is True and rep["complete"] is True
    assert rep["texts_read"] == {"hot": 5, "warm": 1} == rep["texts_held"]
    assert rep["per_edition"]["en"] == {
        "ambiguous": 1, "found": 4, "located": 1, "no_house_number": 1, "outside_your_osm_countries": 1, "skipped_about_a_person": 1,
    }
    assert rep["per_edition"]["fr"] == {"found": 1, "located": 1}
    titles = {p["title"] for p in rep["points"]}
    assert titles == {"Fixture Hall", "Salle"}, "only located addresses become points; the person's never does"
    hall = next(p for p in rep["points"] if p["title"] == "Fixture Hall")
    assert hall["field"] == "address" and hall["infobox"] == "infobox building" and hall["osm_object"] == "way/1"
    assert hall["tier"] == "hot" and hall["revision"] and hall["edition"] == "en"
    assert all("Private" not in str(p) for p in rep["points"])
    assert rep["scope"] == "Addresses outside your OpenStreetMap countries are not located."


def test_without_an_osm_country_nothing_is_looked_up_and_it_is_counted_so(lane, scope):
    _page(lane, "en", "Fixture Hall", HALL, 1)
    lane.commit()
    calls = []
    scope("[]", [], lambda q, limit=5: calls.append(q) or {})
    rep = L.located_report(lane, budget=5.0)
    assert rep["per_edition"]["en"] == {"found": 1, "no_osm_country": 1} and rep["points"] == []
    assert calls == [], "no country ingested: nothing to ask the index"


def test_the_scan_is_incremental_and_says_how_far_it_got(lane, scope):
    for n in range(5):
        _page(lane, "en", f"Hall {n}", HALL, n)
    lane.commit()
    scope("[]", [], lambda q, limit=5: {})
    rep = L.located_report(lane, budget=0.0)
    assert rep["complete"] is False and rep["texts_read"]["hot"] < 5 and rep["texts_held"]["hot"] == 5
    rep = L.located_report(lane, budget=5.0)
    assert rep["complete"] is True and rep["texts_read"]["hot"] == 5


def test_a_busy_scan_answers_with_the_last_report_instead_of_waiting(lane, scope):
    scope("[]", [], lambda q, limit=5: {})
    first = L.located_report(lane, budget=1.0)
    with L._lock:
        again = L.located_report(lane, budget=1.0)
    assert again["from_previous_read"] is True and again["per_edition"] == first["per_edition"]


def test_coverage_carries_the_counters_and_the_bundle_member_carries_counts_only(lane, scope):
    _page(lane, "en", "Fixture Hall", HALL, 1)
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [], _geo({"2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)]}))
    full = edition_coverage(lane, now=T0)["located"]
    assert full["measured"] is True and full["per_edition"]["en"]["located"] == 1 and full["located_points"] == 1
    assert full["per_press_lane"] is None and full["per_press_lane_reason"] == "press-body-addresses-not-read"
    member = edition_coverage(lane, now=T0, newest_gaps=False)["located"]
    assert member["per_edition"]["en"] == {"found": 1, "located": 1}
    assert "located_points" not in member and "points" not in member and "gaps" not in member


def test_the_lane_route_serves_the_points(lane, scope, monkeypatch):
    _page(lane, "en", "Fixture Hall", HALL, 1)
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [], _geo({"2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)]}))
    from src.api.wiki_lane import lane_located_addresses

    out = lane_located_addresses(limit=2000)
    assert out["measured"] is True and out["n"] == 1 and out["truncated"] is False
    assert out["points"][0]["title"] == "Fixture Hall"
    capped = lane_located_addresses(limit=1)
    assert capped["n"] == 1 and capped["total_located"] == 1


# --------------------------------------------------------------------------- #
# End to end, with NO stand-in: the synthetic OSM extract ingested into a real OSM lane, its address index built by the ingest, the
# real geocoder, and a wiki page whose infobox carries the fixture's one address. Gate row D's "a located address from a wiki infobox".
# --------------------------------------------------------------------------- #
def test_a_fixture_infobox_address_is_located_through_the_real_local_index(osm_lane_dir):
    from src.osm import ingest
    from tests._osm_lane_helpers import FIXTURE

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    L.reset()
    create_lane("wiki")
    try:
        with lane_session("wiki") as s:
            _page(s, "en", "Fixture Building", "{{Infobox building|address=1 Fixture Road, Fixtureville, Fixture Land}}", 1)
            _page(s, "en", "Elsewhere Hall", "{{Infobox building|address=4 Nowhere Road}} {{coord|-33.9|151.2}}", 2)
            _page(s, "en", "Somebody", "{{Infobox person|address=1 Fixture Road, Fixtureville}}", 3)
            s.commit()
            rep = L.located_report(s, budget=5.0)
    finally:
        L.reset()
    assert rep["per_edition"]["en"] == {"found": 2, "located": 1, "outside_your_osm_countries": 1, "skipped_about_a_person": 1}
    [pt] = rep["points"]
    assert pt["title"] == "Fixture Building" and pt["osm_object"] == "way/13" and pt["osm_country"] == "ZZZ"
    assert pt["query"] == "1 Fixture Road, Fixtureville", "the country part was dropped, the street part kept"
    assert pt["osm_address"] == "1 Fixture Road 00000 Fixtureville"
