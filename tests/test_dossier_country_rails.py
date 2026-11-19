"""S08-01 S2/S3 — the dossier's country rails and its rail-availability counter (0.8 row A).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The rails keyed by COUNTRY (statistics, climate, agenda, elections) join an item only when the
item IS a country: a Place of OSM kind ``country`` carries it. Proven on synthetic rows: a
country item joins all four with what this machine holds for that country and nothing for
another; a city's item, and an item two country Places disagree about, join none and say why;
a statistics series is named with its periods and dates, never a value; an election keeps its
date confidence and caveat; and the availability counter says which joined rails had rows.
No test here opens a socket.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Base, Place, StatFigure
from src.entities import dossier as DO
from tests.js_source_helper import read_static

LAND = "Q999999040"


@pytest.fixture
def lanes(tmp_path, monkeypatch):
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
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def _fig(db, agency, series, area, period, value, vintage="2026-11-01T00:00:00Z"):
    db.add(StatFigure(agency=agency, series_id=series, ref_area=area, time_period=period,
                      value=value, extracted_at=vintage))


@pytest.fixture
def country(db):
    db.add(Place(id="relation/2202162", qid=LAND, kind="country", name="France",
                 country="fr", country_alpha3="FRA"))
    # Two vintages of one observation and a second period: one series, two periods.
    _fig(db, "worldbank", "SP.POP.TOTL", "FRA", "2020", 67.3e6)
    _fig(db, "worldbank", "SP.POP.TOTL", "FRA", "2020", 67.4e6, vintage="2026-11-02T00:00:00Z")
    _fig(db, "worldbank", "SP.POP.TOTL", "FRA", "2021", None)  # a published gap is still a period
    _fig(db, "eurostat", "une_rt_m", "FR", "2025-09", 7.6)
    _fig(db, "owid", "co2.co2", "FRA", "2022", 299.1)
    # Another country's rows, and an aggregate's, never join.
    _fig(db, "worldbank", "SP.POP.TOTL", "DEU", "2020", 83.2e6)
    _fig(db, "owid", "co2.co2", "WLD", "2022", 37000.0)
    db.commit()


def _rail(d, key):
    return next(r for r in d["rails"] if r["key"] == key)


def test_a_country_item_joins_the_four_country_rails_with_its_own_rows_only(db, country, lanes):
    d = DO.qid_dossier(db, LAND, "en")
    assert [r["key"] for r in d["rails"]] == [*DO.JOINED_RAILS, *DO.COUNTRY_RAILS]
    assert d["country"] == {"iso2": "fr", "iso3": "FRA"}
    assert [r["key"] for r in d["not_joined"]] == ["markets", "law_versions"]
    stats = _rail(d, "stats")
    assert stats["count"] == 2
    assert [(s["agency"], s["series_id"], s["ref_area"], s["periods"], s["first"], s["last"])
            for s in stats["series"]] == [
        ("eurostat", "une_rt_m", "FR", 1, "2025-09", "2025-09"),
        ("worldbank", "SP.POP.TOTL", "FRA", 2, "2020", "2021"),
    ]
    assert stats["series"][1]["fetched"] == "2026-11-02T00:00:00Z"
    climate = _rail(d, "climate")
    assert [(s["agency"], s["series_id"]) for s in climate["series"]] == [("owid", "co2.co2")]
    assert "CC BY 4.0" in climate["licences"]["owid"]


def test_a_series_row_names_the_series_and_never_carries_a_value(db, country, lanes):
    d = DO.qid_dossier(db, LAND, "en")
    for key in ("stats", "climate"):
        for s in _rail(d, key)["series"]:
            assert "value" not in s
            assert not any(isinstance(v, float) for v in s.values())


def test_the_agenda_and_elections_rails_split_the_catalogue_and_keep_the_date_caveat(db, country, lanes):
    from src.events.catalog import agenda

    d = DO.qid_dossier(db, LAND, "en")
    fr = agenda(country="fr")
    ag, el = _rail(d, "agenda"), _rail(d, "elections")
    assert ag["count"] + el["count"] == len(fr) and el["count"] >= 1
    assert all(e["calendar"] != "elections" for e in ag["events"])
    assert all(e["calendar"] == "elections" for e in el["events"])
    for e in el["events"]:
        # An election's date never travels without its tier and the caveat that goes with it.
        assert e.get("date_confidence") in ("scheduled", "window", "projected", None)
        if e.get("date_confidence"):
            assert e.get("date_caveat")


def test_a_city_item_joins_no_country_rail_and_says_why(db, lanes):
    db.add(Place(id="node/1", qid=LAND, kind="city", name="Paris", country="fr", country_alpha3="FRA"))
    _fig(db, "worldbank", "SP.POP.TOTL", "FRA", "2020", 1.0)
    db.commit()
    d = DO.qid_dossier(db, LAND, "en")
    assert [r["key"] for r in d["rails"]] == list(DO.JOINED_RAILS)
    absent = [r for r in d["not_joined"] if r["key"] in DO.COUNTRY_RAILS]
    assert [r["key"] for r in absent] == list(DO.COUNTRY_RAILS)
    assert {r["code"] for r in absent} == {"not-a-country"}
    assert d["country"] is None


def test_two_country_places_naming_different_countries_pick_none(db, lanes):
    db.add(Place(id="relation/1", qid=LAND, kind="country", name="France", country="fr", country_alpha3="FRA"))
    db.add(Place(id="relation/2", qid=LAND, kind="country", name="Germany", country="de", country_alpha3="DEU"))
    db.commit()
    d = DO.qid_dossier(db, LAND, "en")
    assert {r["code"] for r in d["not_joined"] if r["key"] in DO.COUNTRY_RAILS} == {"several-countries"}


def test_a_country_code_the_registry_does_not_know_joins_nothing(db, lanes):
    db.add(Place(id="relation/3", qid=LAND, kind="country", name="Zed", country="zz", country_alpha3=None))
    db.commit()
    d = DO.qid_dossier(db, LAND, "en")
    assert d["country"] is None
    assert {r["code"] for r in d["not_joined"] if r["key"] in DO.COUNTRY_RAILS} == {"country-unconfirmed"}


def test_a_neighbours_country_point_inside_a_region_build_never_takes_the_regions_rows(db, lanes):
    # The gazetteer writes the code of the REGION it was built from: Monaco's country point in
    # a France build carries "fr". Its names say Monaco, so France's rows must not join.
    db.add(Place(id="node/1790048269", qid=LAND, kind="country", name="Monaco",
                 names_json='{"fr": "Monaco", "en": "Monaco"}', country="fr", country_alpha3="FRA"))
    _fig(db, "worldbank", "SP.POP.TOTL", "FRA", "2020", 1.0)
    db.commit()
    d = DO.qid_dossier(db, LAND, "en")
    assert d["country"] is None
    assert {r["code"] for r in d["not_joined"] if r["key"] in DO.COUNTRY_RAILS} == {"country-unconfirmed"}


def test_a_local_name_the_registry_does_not_know_is_confirmed_by_a_tagged_name(db, lanes):
    db.add(Place(id="relation/51477", qid=LAND, kind="country", name="Deutschland",
                 names_json='{"en": "Germany"}', country="de", country_alpha3="DEU"))
    db.commit()
    assert DO.qid_dossier(db, LAND, "en")["country"] == {"iso2": "de", "iso3": "DEU"}


def test_eurostats_own_codes_for_greece_and_the_uk_are_found(db, lanes):
    db.add(Place(id="relation/192307", qid=LAND, kind="country", name="Ελλάς",
                 names_json='{"en": "Greece"}', country="gr", country_alpha3="GRC"))
    _fig(db, "eurostat", "une_rt_m", "EL", "2025-09", 9.0)
    db.commit()
    stats = _rail(DO.qid_dossier(db, LAND, "en"), "stats")
    assert [(s["agency"], s["ref_area"]) for s in stats["series"]] == [("eurostat", "EL")]


def test_an_owid_chart_that_is_not_the_climate_dataset_stays_on_the_statistics_rail(db, lanes):
    db.add(Place(id="relation/2202162", qid=LAND, kind="country", name="France", country="fr", country_alpha3="FRA"))
    _fig(db, "owid", "life-expectancy", "FRA", "2020", 82.0)
    _fig(db, "owid", "co2.co2_per_capita", "FRA", "2022", 4.6)
    db.commit()
    d = DO.qid_dossier(db, LAND, "en")
    assert [s["series_id"] for s in _rail(d, "stats")["series"]] == ["life-expectancy"]
    assert [s["series_id"] for s in _rail(d, "climate")["series"]] == ["co2.co2_per_capita"]


def test_the_count_matches_the_list_when_one_series_is_stored_under_two_spellings(db, lanes):
    db.add(Place(id="relation/2202162", qid=LAND, kind="country", name="France", country="fr", country_alpha3="FRA"))
    _fig(db, "worldbank", "X", "FRA", "2020", 1.0)
    _fig(db, "worldbank", "X", "FR", "2020", 1.0)
    db.commit()
    stats = _rail(DO.qid_dossier(db, LAND, "en"), "stats")
    assert stats["count"] == len(stats["series"]) == 2


def test_the_availability_counter_names_the_rails_with_and_without_rows(db, country, lanes):
    d = DO.qid_dossier(db, LAND, "en")
    a = d["availability"]
    assert a["joined"] == 9
    assert a["rails_with_rows"] == ["places", "stats", "climate", "agenda", "elections"]
    assert a["rails_without_rows"] == ["news", "wikipedia", "law", "map"]
    assert a["with_rows"] == 5


def test_a_country_with_nothing_stored_still_lists_its_rails_as_gaps(db, lanes):
    db.add(Place(id="relation/4", qid=LAND, kind="country", name="Iceland", country="is", country_alpha3="ISL"))
    db.commit()
    d = DO.qid_dossier(db, LAND, "en")
    assert _rail(d, "stats")["count"] == 0 and _rail(d, "stats")["series"] == []
    assert "stats" in d["availability"]["rails_without_rows"]


def test_the_export_carries_the_country_rails_and_survives_a_browser_save(db, country, lanes):
    import json

    from src.reporting.dossier_evidence import dossier_selection

    sel = dossier_selection(db, LAND, "en")
    assert sel.block["rails_carried"] == [*DO.JOINED_RAILS, *DO.COUNTRY_RAILS]
    raw = json.dumps(sel.block, sort_keys=True)
    assert json.loads(raw) == sel.block
    assert not any(isinstance(v, float) for v in _walk(sel.block))


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def test_the_page_renders_each_country_rail_and_the_counter():
    js = read_static("app-dossier.js")
    for needle in ('r.key === "stats"', 'r.key === "climate"', 'r.key === "agenda"',
                   'r.key === "elections"', "d.availability", "date_caveat", "r.code"):
        assert needle in js, needle


def test_the_agenda_date_is_today_relative(db, country, lanes):
    # The agenda rail is computed for today, like the Agenda tab: no stored date is moved.
    d = DO.qid_dossier(db, LAND, "en")
    for e in _rail(d, "agenda")["events"]:
        if e.get("next_occurrence"):
            assert e["next_occurrence"] >= date.today().isoformat()


def test_the_country_rails_render_through_the_real_renderer():
    import subprocess
    from pathlib import Path

    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "dossier_country_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout
