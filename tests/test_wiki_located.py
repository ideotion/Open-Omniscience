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

HALL = """{{Infobox museum
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
{{Infobox museum|address=9 Private Lane}}"""


# --------------------------------------------------------------------------- #
# The pure extractor.
# --------------------------------------------------------------------------- #
def test_a_place_infobox_offers_its_address_cleaned_and_its_coordinate():
    offer = L.page_addresses("en", HALL)
    assert offer["type"] == "infobox museum"
    assert offer["candidates"] == [("address", "2 Fixture Road, Fixtureville, Fixtureland")]
    lat, lon = offer["coord"]
    assert round(lat, 3) == 48.858 and round(lon, 3) == 2.294


@pytest.mark.parametrize("text", [PERSON, PERSON_THEN_BUILDING, "{{Infobox museum|address=9 Private Lane}}\n{{Infobox person|name=A}}", "{{Infobox officeholder|address=1 Main St}}", "{{Персона|адрес=ул. Ленина, 5}}"])
def test_a_page_with_a_person_infobox_is_never_read(text):
    edition = "ru" if "Персона" in text else "en"
    assert L.page_addresses(edition, text) == {"skip": "about_a_person"}


def test_an_unlisted_infobox_type_fails_closed():
    assert L.page_addresses("en", "{{Infobox settlement|address=1 Main St}}") == {"skip": "type_not_on_the_list"}
    # A type listed for ANOTHER edition is not listed for this one.
    assert L.page_addresses("fr", "{{Infobox museum|address=1 Main St}}") == {"skip": "type_not_on_the_list"}


def test_no_listed_type_is_a_person_type():
    assert not [t for t in L._ALL_PLACE_TYPES if L._is_person_type(t)]
    assert set(L.PLACE_TYPES) == set(L.ADDRESS_KEYS) and len(L.PLACE_TYPES) == 12


@pytest.mark.parametrize(
    "edition,text,want",
    [
        ("fr", "{{Infobox Musée|adresse=3 rue Fixture}}", [("adresse", "3 rue Fixture")]),
        ("de", "{{Infobox Unternehmen|Anschrift=Fixturestraße 4<br />Berlin}} {{coord|52.5|13.4}}", [("anschrift", "Fixturestraße 4, Berlin")]),
        ("es", "{{Ficha de museo|dirección=Calle Mayor 3}}", [("dirección", "Calle Mayor 3")]),
        ("pt", "{{Info/Empresa|endereço=Rua Fixture, 10}} {{coord|-23.5|-46.6}}", [("endereço", "Rua Fixture, 10")]),
        ("ru", "{{Музей|адрес=ул. Ленина, 5}}", [("адрес", "ул. Ленина, 5")]),
        ("id", "{{Infobox perusahaan|alamat=Jalan Fixture 7}} {{coord|-6.2|106.8}}", [("alamat", "Jalan Fixture 7")]),
    ],
)
def test_the_editions_own_type_and_key_names(edition, text, want):
    assert L.page_addresses(edition, text)["candidates"] == want


def test_an_infobox_with_no_address_field_offers_nothing():
    assert L.page_addresses("en", "{{Infobox museum|name=Hall|location=Fixtureville}}") == {"none": True}
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
    assert L.resolve("2 Fixture Road", near, guarded=True)["status"] == "located"
    far = _geo({"2 Fixture Road": [_hit(48.85, 2.35), _hit(43.3, 5.4)]})
    assert L.resolve("2 Fixture Road", far, guarded=True) == {"status": "ambiguous", "answers": 2}
    many = _geo({"2 Fixture Road": [_hit(48.85, 2.35)] * 6})
    assert L.resolve("2 Fixture Road", many, guarded=True)["status"] == "ambiguous"


def test_not_found_and_no_country_are_different_answers():
    assert L.resolve("2 Fixture Road", _geo({}), guarded=True) == {"status": "not_located"}
    assert L.resolve("2 Fixture Road", _geo("no-country"), guarded=True) == {"status": "no_osm_country"}
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
    _page(lane, "en", "Far Hall", "{{Infobox museum|address=7 Far Street}} {{coord|-33.9|151.2}}", 3)
    _page(lane, "en", "Twin Hall", "{{Infobox museum|address=5 Twin Road, Fixtureville}}", 4)
    _page(lane, "en", "Vague Hall", "{{Infobox museum|address=Somewhere, Fixtureville}}", 5)
    lane.add(WikiWarmPage(edition="fr", page_id=9, title="Salle", latest_revid=9, latest_text="{{Infobox Musée|adresse=3 rue Fixture, Fixtureville}}"))
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [(41.0, -5.0, 51.0, 10.0)], _geo({
        "2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)],
        "5 Twin Road, Fixtureville": [_hit(48.85, 2.35), _hit(45.0, 1.0)],
        "3 rue Fixture, Fixtureville": [_hit(48.86, 2.36, "node/3")],
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
    assert hall["field"] == "address" and hall["infobox"] == "infobox museum" and hall["osm_object"] == "way/1"
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
            _page(s, "en", "Fixture Building", "{{Infobox museum|address=1 Fixture Road, Fixtureville, Fixture Land}}", 1)
            _page(s, "en", "Elsewhere Hall", "{{Infobox museum|address=4 Nowhere Road}} {{coord|-33.9|151.2}}", 2)
            _page(s, "en", "Somebody", "{{Infobox person|address=1 Fixture Road, Fixtureville}}", 3)
            s.commit()
            rep = L.located_report(s, budget=5.0)
    finally:
        L.reset()
    assert rep["per_edition"]["en"] == {"found": 2, "located": 1, "outside_your_osm_countries": 1, "skipped_about_a_person": 1}
    [pt] = rep["points"]
    assert pt["title"] == "Fixture Building" and pt["osm_object"] == "way/13" and pt["osm_country"] == "ZZZ"
    assert pt["query"] == "1 Fixture Road, Fixtureville", "the country part was dropped, the street part kept"
    assert "osm_address" not in pt, "the matched object's own address is never served (security read, R691)"


# --------------------------------------------------------------------------- #
# The review's probes (PR #1948): the person rule fails closed at PAGE level, and the scan follows the lane as it changes.
# --------------------------------------------------------------------------- #
_BUILDING = "{{Infobox museum|address=10 Fixture Street}}\n"


@pytest.mark.parametrize(
    "edition,extra",
    [
        ("en", "{{Infobox cricketer|name=A}}"),
        ("en", "{{Infobox ice hockey player|name=A}}"),
        ("en", "{{Infobox musician|name=A}}"),
        ("en", "{{Template:Infobox person|name=A}}"),
        ("en", "[[Category:Living people]]"),
        ("en", "[[Category:1950 births]]"),
        ("de", "{{Personendaten|NAME=A}}"),
        ("ru", "{{Музыкант|имя=A}}"),
        ("ja", "{{ActorActress|名前=A}}"),
        ("ja", "[[カテゴリ:存命人物]]"),
        ("fr", "[[Catégorie:Naissance en 1950]]"),
    ],
)
def test_any_person_signal_anywhere_on_the_page_keeps_it_unread(edition, extra):
    building = {"en": _BUILDING, "de": "{{Infobox Museum|Adresse=Fixturestraße 4}}\n", "ru": "{{Музей|адрес=ул. Ленина, 5}}\n",
                "ja": "{{Infobox 博物館|所在地=東京都 1-2-3}}\n", "fr": "{{Infobox Musée|adresse=3 rue Fixture}}\n"}[edition]
    assert L.page_addresses(edition, building + extra) == {"skip": "about_a_person"}


@pytest.mark.parametrize("extra", ["{{#invoke:Infobox|infobox|label1=Born}}", "{{Infobox settlement|name=X}}"])
def test_a_second_infobox_not_on_the_list_keeps_the_page_unread(extra):
    assert L.page_addresses("en", _BUILDING + extra) == {"skip": "type_not_on_the_list"}


def test_a_harmless_mapframe_beside_the_place_infobox_is_fine():
    assert L.page_addresses("en", _BUILDING + "{{Infobox mapframe|zoom=10}}")["candidates"] == [("address", "10 Fixture Street")]


@pytest.mark.parametrize("field", ["building_type = Private house", "nrhp_type = Residence", "type = [[Villa]]"])
def test_a_home_is_never_read(field):
    assert L.page_addresses("en", "{{Infobox museum|" + field + "|address=123 Elm Street}}") == {"skip": "a_home"}


def test_a_ref_whose_name_carries_a_slash_does_not_swallow_the_address():
    assert L.clean_value('2 Fixture Road<ref name="a/b"/>, Fixtureville<ref>x</ref>') == "2 Fixture Road, Fixtureville"


def test_a_number_alone_is_never_looked_up():
    assert L.variants("5, Rue Fixture") == ["5, Rue Fixture"]


def test_a_located_answer_far_from_the_pages_own_coord_is_not_placed(lane, scope):
    _page(lane, "en", "Namesake Hall", "{{Infobox museum|address=2 Fixture Road, Elsewhere}} {{coord|-33.9|151.2}}", 1)
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [], _geo({"2 Fixture Road, Elsewhere": [_hit(48.85, 2.35)]}))
    rep = L.located_report(lane, budget=5.0)
    assert rep["per_edition"]["en"] == {"ambiguous": 1, "found": 1} and rep["points"] == []


def test_a_failed_lookup_and_an_unreadable_osm_lane_are_named_never_raised(lane, scope, monkeypatch):
    _page(lane, "en", "Fixture Hall", HALL, 1)
    lane.commit()

    def boom(q, limit=5):
        raise RuntimeError("osm lane locked")

    scope('[["FXL", "2026-10-01"]]', [], boom)
    rep = edition_coverage(lane, now=T0)["located"]
    assert rep["measured"] is True and rep["per_edition"]["en"] == {"found": 1, "lookup_failed": 1}
    L.reset()
    scope(None, [], boom)
    rep = L.located_report(lane, budget=5.0)
    assert rep["per_edition"]["en"] == {"found": 1, "osm_unreadable": 1}


def test_a_page_that_changes_is_read_again_and_a_page_that_goes_is_forgotten(lane, scope):
    _page(lane, "en", "Fixture Hall", HALL, 1)
    lane.add(WikiWarmPage(edition="fr", page_id=9, title="Salle", latest_revid=9, latest_text="{{Infobox Musée|adresse=3 rue Fixture, Fixtureville}}"))
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [], _geo({"2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)], "3 rue Fixture, Fixtureville": [_hit(48.86, 2.36)]}))
    assert len(L.located_report(lane, budget=5.0)["points"]) == 2
    # The HOT page gains a person infobox in a new revision; the WARM text is replaced in place by one without an infobox.
    entity = lane.query(VersionedEntity).filter_by(external_id="en:#1").one()
    lane.add(VersionedRevision(entity_id=entity.id, revision_ref="999", content_hash="h999", content=HALL + "{{Infobox person|name=A}}", byte_size=1))
    warm = lane.query(WikiWarmPage).one()
    warm.latest_revid, warm.latest_text = 10, "Now a stub."
    lane.commit()
    rep = L.located_report(lane, budget=5.0)
    assert rep["points"] == [] and rep["per_edition"] == {"en": {"skipped_about_a_person": 1}}
    lane.delete(warm)  # evicted from the WARM tier; a deleted_at page keeps its text (Q713) and stays read
    lane.commit()
    rep = L.located_report(lane, budget=5.0)
    assert rep["texts_held"] == {"hot": 1, "warm": 0} == rep["texts_read"] and rep["complete"] is True


def test_an_edition_outside_the_twelve_does_not_hold_complete_false(lane, scope):
    _page(lane, "nl", "Gebouw", "{{Infobox gebouw|adres=Straat 1}}", 1)
    lane.commit()
    scope("[]", [], lambda q, limit=5: {})
    rep = L.located_report(lane, budget=5.0)
    assert rep["complete"] is True and rep["texts_held"] == {"hot": 0, "warm": 0}


def test_addresses_left_unresolved_at_the_deadline_are_pending_not_zero(lane, scope):
    _page(lane, "en", "Fixture Hall", HALL, 1)
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [], _geo({}))
    L.located_report(lane, budget=5.0)  # reads the page
    L._state.resolved.clear()
    rep = L.located_report(lane, budget=0.0)
    assert rep["per_edition"]["en"] == {"found": 1, "pending": 1} and rep["complete"] is False


def test_round_two_review_probes():
    # A category written with underscores is still a person.
    assert L.classify_page("en", "{{Infobox museum|address=1 Main Street}}[[Category:Living_people]]")[0] == "about_a_person"
    # A house named in the title is a home even when the infobox says nothing about use.
    assert L.page_addresses("en", "{{Infobox museum|address=1 Main Street, Springfield}}", "John Smith House") == {"skip": "a_home"}
    # Persondata alone marks a person.
    assert L.classify_page("en", "{{Infobox museum|address=1 Main Street}}{{Persondata|NAME=A}}")[0] == "about_a_person"


def test_a_partial_answer_is_ambiguous_never_a_pick():
    geo = lambda q, limit=5: {"status": "located", "total": 3, "results": [_hit(1.0, 1.0)]}  # noqa: E731
    assert L.resolve("1 Main Street, Springfield", geo)["status"] == "ambiguous"


def test_without_a_page_coordinate_a_shortened_address_keeps_its_locality():
    asked = []

    def geo(q, limit=5):
        asked.append(q)
        return {"status": "empty", "total": 0, "results": []}

    L.resolve("1 avenue de la Gare, 1700 Fribourg", geo)
    assert asked and all("," in q for q in asked)
    asked.clear()
    L.resolve("1 avenue de la Gare, 1700 Fribourg", geo, guarded=True)
    assert asked and "1 avenue de la Gare" not in asked, "even beside a coordinate, the street alone is somebody's house elsewhere"
    asked.clear()
    L.resolve("1 avenue de la Gare", geo)
    assert asked == [], "an address with no locality is tried only beside the page's own coordinate"
    L.resolve("1 avenue de la Gare", geo, guarded=True)
    assert asked == ["1 avenue de la Gare"]


def test_held_reads_no_warm_text_column():
    import inspect

    src = inspect.getsource(L._held)
    warm = src[src.index("select(WikiWarmPage.id"):]
    warm = warm[: warm.index(".where(")]
    assert "latest_text" not in warm and "deleted_at" not in warm


# --------------------------------------------------------------------------- #
# R691: the closed allowlist is the safeguard; generic building types are never on it, and the home words are an extra, script-aware check.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "edition,text",
    [
        ("en", "{{Infobox building|address=12 Elm Street, Springfield}}"),
        ("en", "{{Infobox historic building|address=12 Elm Street}}"),
        ("en", "{{Infobox NRHP|address=12 Elm Street}}"),
        ("en", "{{Infobox landmark|address=12 Elm Street}}"),
        ("en", "{{Infobox castle|address=12 Elm Street}}"),
        ("en", "{{Infobox house|address=12 Elm Street}}"),
        ("en", "{{Infobox farm|address=12 Elm Street}}"),
        ("fr", "{{Infobox Bâtiment|adresse=3 rue Fixture}}"),
        ("fr", "{{Infobox Monument|adresse=3 rue Fixture}}"),
        ("de", "{{Infobox Bauwerk|Adresse=Fixturestraße 4}}"),
        ("es", "{{Ficha de edificio|dirección=Calle Mayor 3}}"),
        ("ru", "{{Здание|адрес=ул. Ленина, 5}}"),
        ("ja", "{{Infobox 建築物|所在地=東京都港区1-2-3}}"),
        ("zh", "{{Infobox 建筑物|地址=北京市1号}}"),
        ("ar", "{{صندوق معلومات مبنى|العنوان=شارع 1}}"),
        ("hi", "{{ज्ञानसन्दूक भवन|पता=1 मार्ग, दिल्ली}}"),
        ("bn", "{{তথ্যছক ভবন|ঠিকানা=১ রোড, ঢাকা}}"),
        ("id", "{{Infobox gedung|alamat=Jalan Fixture 7}}"),
    ],
)
def test_a_generic_building_type_is_never_read_whatever_it_says(edition, text):
    # A building, monument, castle or heritage-register infobox describes private houses as often as public places: off the list.
    assert L.page_addresses(edition, text) == {"skip": "type_not_on_the_list"}


@pytest.mark.parametrize(
    "edition,text",
    [
        ("en", "{{Infobox family|address=12 Elm Street}}"),
        ("de", "{{Infobox Familie|Adresse=Fixturestraße 4}}"),
        ("ja", "{{Infobox 家族|所在地=東京都港区1-2-3}}"),
        ("en", "{{Infobox museum|address=12 Elm Street}}[[Category:Smith family]]"),
        ("en", "{{Infobox museum|address=12 Elm Street}}[[Category:American families]]"),
    ],
)
def test_a_family_is_people_too(edition, text):
    assert L.page_addresses(edition, text) == {"skip": "about_a_person"}


# A private residence in five scripts (and the rest), each on an ALLOWLISTED type so only the extra check stands between it and the map.
RESIDENCES = [
    ("en", "Smith Farm", "{{Infobox hotel|address=12 Elm Street, Springfield}}"),
    ("en", "Elm Lodge", "{{Infobox company|name=Elm House|address=12 Elm Street, Springfield}}"),
    ("en", "Elm Lodge", "{{Infobox company|address=12 Elm Street, Springfield}}[[Category:Houses in Springfield]]"),
    ("en", "Elm Lodge", "{{Infobox venue|type=Private residence|address=12 Elm Street, Springfield}}"),
    ("ja", "高級住宅", "{{Infobox 博物館|所在地=東京都港区1-2-3}}"),
    ("ja", "山田邸", "{{Infobox 博物館|所在地=東京都港区1-2-3}}"),
    ("ja", "山田宅", "{{Infobox 博物館|所在地=東京都港区1-2-3}}"),
    ("ja", "記念館", "{{Infobox 博物館|所在地=東京都港区1-2-3}}[[Category:日本の住宅]]"),
    ("zh", "王公馆", "{{Infobox 博物馆|地址=上海市1号}}"),
    ("zh", "某别墅", "{{Infobox 公司|地址=上海市1号}}"),
    ("zh", "纪念馆", "{{Infobox 博物馆|地址=上海市1号|类型=私人住宅}}"),
    ("ar", "منزل العائلة", "{{صندوق معلومات متحف|العنوان=شارع 1، القاهرة}}"),
    ("ar", "فيلا النخيل", "{{صندوق معلومات شركة|العنوان=شارع 1، القاهرة}}"),
    ("ar", "مبنى", "{{صندوق معلومات فندق|العنوان=شارع 1، القاهرة|النوع=مسكن خاص}}"),
    ("hi", "शर्मा हवेली", "{{ज्ञानसन्दूक संग्रहालय|पता=1 मार्ग, दिल्ली}}"),
    ("hi", "शर्मा निवास", "{{ज्ञानसन्दूक कंपनी|पता=1 मार्ग, दिल्ली}}"),
    ("hi", "कोठी", "{{ज्ञानसन्दूक संग्रहालय|पता=1 मार्ग, दिल्ली|प्रकार=निजी आवास}}"),
    ("bn", "রায় বাড়ি", "{{তথ্যছক জাদুঘর|ঠিকানা=১ রোড, ঢাকা}}"),
    ("fr", "Maison Dupont", "{{Infobox Musée|adresse=3 rue Fixture}}"),
    ("de", "Gutshof Müller", "{{Infobox Museum|Adresse=Fixturestraße 4}}"),
    ("ru", "Усадьба Иванова", "{{Музей|адрес=ул. Ленина, 5}}"),
    ("es", "Hacienda López", "{{Ficha de museo|dirección=Calle Mayor 3}}"),
    ("pt", "Fazenda Silva", "{{Info/Museu|endereço=Rua Fixture, 10}}"),
    ("id", "Rumah Budi", "{{Infobox perusahaan|alamat=Jalan Fixture 7}}"),
]


@pytest.mark.parametrize("edition,title,text", RESIDENCES)
def test_a_private_residence_is_never_read_in_any_script(edition, title, text):
    assert L.page_addresses(edition, text, title) == {"skip": "a_home"}


def test_the_home_words_are_whole_words_where_words_are_spaced_and_never_split_by_vowel_signs():
    assert not L.names_a_home("Housekeeping Museum")  # a letter after "house": not the word
    assert not L.names_a_home("Farmington Library")
    assert L.names_a_home("Old Farm")  # at the end of the text
    assert L.names_a_home("Elm_House")  # underscores as spaces
    # \b would split Devanagari at the vowel sign of हवेली and miss it; substring matching does not.
    assert L.names_a_home("हवेली") and L.names_a_home("पुरानी हवेली संग्रहालय")
    assert L.names_a_home("高級住宅街") and L.names_a_home("বাড়ি")


def test_residences_in_every_script_produce_no_point_even_when_the_index_answers(lane, scope):
    for n, (edition, title, text) in enumerate(RESIDENCES, start=1):
        _page(lane, edition, title, text, n)
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [], lambda q, limit=5: {"status": "located", "total": 1, "results": [_hit(48.85, 2.35)]})
    rep = L.located_report(lane, budget=5.0)
    assert rep["points"] == []
    skipped = sum(row.get("skipped_a_home", 0) for row in rep["per_edition"].values())
    assert skipped == len(RESIDENCES)
    assert all(set(row) == {"skipped_a_home"} for row in rep["per_edition"].values())


# --------------------------------------------------------------------------- #
# The two security reads of R691, each finding pinned.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "edition,title,text",
    [
        ("en", "St Mary's Rectory", "{{Infobox religious building|building_type=Rectory|address=12 Church Lane, Ambridge}}"),
        ("en", "Old Vicarage, Grantchester", "{{Infobox church|address=4 Mill Way, Grantchester}}"),
        ("de", "Pfarrhaus St. Peter", "{{Infobox Kirchengebäude|Adresse=Kirchweg 3, Dorf}}"),
        ("fr", "Presbytère de Fixture", "{{Infobox Édifice religieux|adresse=3 rue Fixture, Fixtureville}}"),
        ("ru", "Резиденция посла", "{{Гостиница|адрес=ул. Ленина, 5, Москва}} {{coord|55.7|37.6}}"),
        ("en", "Elm Garden", "{{Infobox park|type=Private garden|address=7 Elm Road, Ambridge}}"),
        ("en", "Elm Inn", "{{Infobox hotel|type=" + "Private residence " * 20 + "|address=7 Elm Road, Ambridge}} {{coord|52|-1}}"),
        ("en", "Elm Inn", "{{Infobox hotel|type=[[Detached house|Single-family]]|address=7 Elm Road, Ambridge}} {{coord|52|-1}}"),
    ],
)
def test_a_house_that_goes_with_an_office_or_a_private_place_is_never_read(edition, title, text):
    assert L.page_addresses(edition, text, title) == {"skip": "a_home"}


@pytest.mark.parametrize(
    "title,text",
    [
        ("John Smith (chef)", "{{Infobox restaurant|address=7 Elm Road, Ambridge}} {{coord|52|-1}}"),
        ("Elm Kitchen", "{{Lifetime|1950|LIVING|Smith, John}}{{Infobox restaurant|address=7 Elm Road, Ambridge}} {{coord|52|-1}}"),
        ("Elm Kitchen", "{{Infobox restaurant|address=7 Elm Road, Ambridge}} {{coord|52|-1}}{{DEFAULTSORT:Smith, John}}"),
        ("Elm Kitchen", "{{Infobox museum|address=7 Elm Road, Ambridge}}[[Category:Living&#32;people]]"),
    ],
)
def test_a_biography_without_a_person_infobox_is_still_a_person(title, text):
    assert L.page_addresses("en", text, title) == {"skip": "about_a_person"}


def test_an_embassy_is_off_the_list_and_a_firm_needs_its_own_coordinate():
    assert L.page_addresses("en", "{{Infobox embassy|address=1 Embassy Row, Capital}}") == {"skip": "type_not_on_the_list"}
    firm = "{{Infobox company|name=Acme Ltd|address=7 Elm Road, Ambridge}}"
    assert L.page_addresses("en", firm, "Acme Ltd") == {"skip": "type_not_on_the_list"}
    assert L.page_addresses("en", firm + " {{coord|52|-1}}", "Acme Ltd")["candidates"] == [("address", "7 Elm Road, Ambridge")]


def test_a_template_built_name_fails_closed():
    text = "{{Infobox museum|address=7 Elm Road, Ambridge}}{{Infobox {{#if:1|person}}|name=A}}"
    assert L.page_addresses("en", text) == {"skip": "type_not_on_the_list"}
    assert L.page_addresses("en", "{{Infobox museum|address=7 Elm Road, Ambridge|note=a{{!}}b}}")["candidates"]


def test_the_street_alone_is_never_asked_and_a_postcode_is_not_a_house_number():
    asked = []

    def geo(q, limit=5):
        asked.append(q)
        if q == "5 Mill Lane":
            return {"status": "located", "total": 1, "results": [_hit(51.27, 0.42)]}
        return {"status": "empty", "total": 0, "results": []}

    assert L.resolve("5 Mill Lane, Townville, Kent", geo, guarded=True)["status"] == "not_located"
    assert "5 Mill Lane" not in asked
    assert L.variants("Mill Lane, ME1 2AB") == []
    assert L.variants("ул. Ленина, 5, Москва") == ["ул. Ленина, 5, Москва", "ул. Ленина, 5"]
    assert L.variants("5, rue Fixture, Fixtureville") == ["5, rue Fixture, Fixtureville", "5, rue Fixture"]
    # The located answer agrees with the page within a few kilometres, not fifty.
    assert L.COORD_AGREEMENT_METRES <= 5_000


def test_a_busy_scan_serves_counts_never_old_points():
    L._last = {"measured": True, "complete": True, "points": [{"title": "Old Museum"}], "per_edition": {"en": {"located": 1}}}
    assert L._lock.acquire(blocking=False)
    try:
        rep = L.located_report(None)
    finally:
        L._lock.release()
        L.reset()
    assert rep["points"] == [] and rep["complete"] is False and rep["from_previous_read"] is True
    assert rep["per_edition"] == {"en": {"located": 1}}


def test_a_renamed_page_is_read_again(lane, scope):
    _page(lane, "en", "Elm Museum", "{{Infobox museum|address=2 Fixture Road, Fixtureville}}", 1)
    lane.commit()
    scope('[["FXL", "2026-10-01"]]', [], _geo({"2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)]}))
    assert len(L.located_report(lane, budget=5.0)["points"]) == 1
    entity = lane.query(VersionedEntity).filter_by(external_id="en:#1").one()
    entity.title = "Elm House"
    lane.commit()
    rep = L.located_report(lane, budget=5.0)
    assert rep["points"] == [] and rep["per_edition"]["en"] == {"skipped_a_home": 1}


def test_the_words_the_security_read_found_missing():
    for word in ("मकान", "ঘর", "屋敷", "住居", "寓所", "домик", "منـزل", "مَنْزِل"):
        assert L.names_a_home(word), word
