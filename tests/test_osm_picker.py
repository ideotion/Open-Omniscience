"""The OSM lane's country picker (S05-04 S3; Q807 = a, Q806 = b, Q824 = a, Q828 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What is pinned: the lane is OFF until a country is chosen; the suggestions come from the
interface language and from nothing that could carry the IP address; every country shows its
continent extract and an estimated daily change cost before it is chosen, each labelled an
estimate with its method; choosing writes one local setting and opens no socket; the download
stays behind the one online consent, and a kill-switch refusal is shown by name. The refusal
itself (the manager presenting airplane mode as ``paused_by = "airplane"``) is pinned in
``tests/test_download_paused_by.py``; this file pins that the picker says so.
"""

from __future__ import annotations

import re
import socket
from pathlib import Path

import pytest

from src.osm import picker as P

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Settings isolated to a JSON file (the module's own per-file test seam)."""
    from src.config import app_settings as AS

    path = tmp_path / "app_settings.json"
    monkeypatch.setattr(AS, "_settings_path", lambda: path)
    return path


@pytest.fixture
def no_network(monkeypatch):
    """Any resolution or connection fails the test: the picker reads local files only."""

    def refuse(*_a, **_k):
        raise AssertionError("the picker touched the network")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


# --------------------------------------------------------------------------- #
#  Off until chosen (Q807)                                                     #
# --------------------------------------------------------------------------- #


def test_the_lane_is_off_until_a_country_is_chosen(settings_file, no_network):
    state = P.picker_state("fr")
    assert state["enabled"] is False
    assert state["selected"] == []
    assert state["off"] == P.OFF and "Nothing is downloaded" in state["off"]


def test_choosing_writes_one_local_setting_and_nothing_else(settings_file, no_network):
    assert P.save_selection(["FR", "fr", "be"]) == ["fr", "be"]
    state = P.picker_state("fr")
    assert state["enabled"] is True and state["off"] is None
    assert [r["cc"] for r in state["selected"]] == ["fr", "be"]
    assert settings_file.exists()
    assert P.save_selection([]) == []
    assert P.picker_state("fr")["enabled"] is False


@pytest.mark.parametrize("bad", [["fra"], ["zz"], ["../x"], [""], "fr", [None]])
def test_a_selection_names_only_iso_countries(settings_file, bad):
    with pytest.raises(P.PickerError):
        P.save_selection(bad)
    assert P.selected() == []


def test_the_setting_itself_refuses_anything_but_alpha2(settings_file):
    from src.config import app_settings as AS

    with pytest.raises(AS.AppSettingsError):
        AS.save_settings({"osm_countries": ["FRA"]})
    assert AS.AppSettings().osm_countries == []


# --------------------------------------------------------------------------- #
#  Suggestions: the interface language, never the IP (Q807)                   #
# --------------------------------------------------------------------------- #


def test_french_suggests_the_francophone_countries_from_the_language_file(settings_file):
    rows = P.suggestions("fr")
    by_cc = {r["cc"]: r for r in rows}
    assert by_cc["fr"]["alpha3"] == "FRA"
    assert {"fr", "be", "ch", "lu"} <= set(by_cc)
    assert all(r["basis"] in ("official", "de-facto", "regional") for r in rows)


def test_an_unknown_language_suggests_nothing_rather_than_guessing(settings_file):
    assert P.suggestions("xx") == []
    assert P.picker_state("")["suggested"] == []


def test_nothing_on_the_picker_path_can_read_the_callers_address():
    """Q807's negation: no route or helper here sees a request, so none can see an IP."""
    for path in (ROOT / "src/osm/picker.py", ROOT / "src/api/osm_lane.py"):
        text = path.read_text("utf-8")
        for needle in ("Request", "request.client", "remote_addr", "X-Forwarded-For", "geoip"):
            assert needle not in text, f"{path.name} mentions {needle}"


# --------------------------------------------------------------------------- #
#  The cost, shown before the choice (Q806, Q824)                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "cc,region",
    [("fr", "europe"), ("jp", "asia"), ("br", "south-america"), ("us", "north-america"),
     ("au", "australia-oceania"), ("ng", "africa"), ("cu", "central-america"), ("tr", "europe")],
)
def test_each_country_maps_to_its_continent_extract(cc, region):
    assert P.extract_for(cc) == (region, None)


def test_a_country_no_catalogued_extract_holds_says_so_instead_of_a_size():
    code, reason = P.extract_for("ru")
    assert code is None and "its own extract" in reason
    row = P._row("ru")
    assert row["extract"] is None and row["diff_daily_estimate_bytes"] is None


def test_every_country_has_an_extract_in_the_catalogue_or_a_stated_reason():
    from src.catalog.countries import ISO_3166_1_ALPHA2
    from src.geo.osm_regions import get_region

    for cc in ISO_3166_1_ALPHA2:
        code, reason = P.extract_for(cc)
        if code is None:
            assert reason, cc
        else:
            assert get_region(code) is not None, (cc, code)


def test_the_daily_change_estimate_is_the_planets_scaled_by_size_share():
    from src.geo.osm_regions import estimate_bytes

    europe = P.daily_diff_estimate("europe")
    assert europe == round(P.PLANET_DAILY_DIFF_BYTES * estimate_bytes("europe") / estimate_bytes("planet"))
    assert 0 < P.daily_diff_estimate("antarctica") < europe < P.PLANET_DAILY_DIFF_BYTES
    assert P.daily_diff_estimate("not-a-region") is None


def test_every_figure_travels_with_its_method_caveat_and_dates(settings_file):
    state = P.picker_state("fr")
    fr = state["suggested"][0]
    assert fr["extract"]["code"] == "europe" and fr["extract"]["size_estimate_bytes"] > 0
    assert fr["diff_daily_estimate_bytes"] > 0
    d = state["diff"]
    assert d["method"] == P.DIFF_METHOD and "from memory" in d["method"]
    assert d["caveat"] == P.DIFF_CAVEAT and "not a measurement" in d["caveat"]
    assert "re-baseline" in d["cadence"] and d["apply"] == "0.6"
    assert d["retention_days"] == 90 and re.fullmatch(r"\d{4}-\d{2}", d["as_of"])
    assert re.fullmatch(r"\d{4}-\d{2}", state["size_as_of"])


def test_the_diff_estimate_date_is_registered():
    from src.maintenance.registry import load_registry

    pins = [e.get("pin") or {} for e in load_registry()]
    assert {"file": "src/osm/picker.py", "const": "OSM_DIFF_ESTIMATE_AS_OF"} in pins


# --------------------------------------------------------------------------- #
#  The HTTP face                                                              #
# --------------------------------------------------------------------------- #


def test_the_picker_routes(settings_file, no_network):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from src.api.osm_lane import router
    from src.database.models import Base, LawDocument
    from src.database.session import get_db

    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng, tables=[LawDocument.__table__])

    def _db():
        with Session(eng) as s:
            yield s

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _db
    c = TestClient(app)
    body = c.get("/api/osm/picker", params={"lang": "fr"}).json()
    assert body["enabled"] is False and "fr" in {r["cc"] for r in body["suggested"]}
    assert body["law_suggested"] == [] and body["law_unavailable"] is False
    assert c.put("/api/osm/countries", json={"countries": ["fr"]}).json() == {
        "countries": ["fr"],
        "enabled": True,
    }
    assert c.put("/api/osm/countries", json={"countries": ["zz"]}).status_code == 400
    assert c.get("/api/osm/picker").json()["selected"][0]["cc"] == "fr"


# --------------------------------------------------------------------------- #
#  The UI: consent, the named refusal, the World map vintage (Q828)            #
# --------------------------------------------------------------------------- #


def _fn(src: str, name: str) -> str:
    from tests.js_source_helper import function_source

    return function_source(src, name)


def test_the_picker_lives_in_settings_openstreetmap_above_the_regions():
    html = (STATIC / "index.html").read_text("utf-8")
    _before, _sep, view = html.partition('id="set-offlinemap"')
    assert view.index('id="osm-lane-picker"') < view.index('id="osm-region-list"')
    for el in ("osm-pick-state", "osm-pick-suggest", "osm-pick-add", "osm-pick-cadence"):
        assert f'id="{el}"' in view
    assert "ODbL" in view.partition('id="osm-region-list"')[0]


def test_the_download_button_goes_through_the_one_online_consent():
    js = (STATIC / "app-map.js").read_text("utf-8")
    cell = _fn(js, "_osmPickDownloadCell")
    assert '"startOsmDownload"' in cell and "api(" not in cell
    assert "ensureOnline(" in _fn(js, "startOsmDownload")
    for fn in ("loadOsmPicker", "_osmPickSave", "loadOsmVintage"):
        for url in re.findall(r'api\("([^"?]+)', _fn(js, fn)):
            assert url.startswith("/api/osm/"), (fn, url)


def test_a_kill_switch_refusal_reads_as_airplane_mode_by_name():
    js = (STATIC / "app-map.js").read_text("utf-8")
    cell = _fn(js, "_osmPickDownloadCell")
    assert 'd.paused_by === "airplane"' in cell and "Paused: airplane mode is on" in cell


def test_the_world_map_states_the_vintage_and_links_to_settings():
    html = (STATIC / "index.html").read_text("utf-8")
    assert 'id="oomap-osm-vintage"' in html
    js = (STATIC / "app-map.js").read_text("utf-8")
    vintage = _fn(js, "loadOsmVintage")
    assert "openSettingsOsm()" in vintage and "c.vintage" in vintage
    assert "date not stated in the extract" in vintage
    assert "loadOsmVintage();" in _fn(js, "loadOoMapCoverage")
    shell = (STATIC / "app-shell.js").read_text("utf-8")
    assert "loadOsmPicker()" in shell
    actions = (STATIC / "oo-on.js").read_text("utf-8")
    for name in ("openSettingsOsm", "osmPickAdd", "osmPickAddCode", "osmPickRemove"):
        assert f'"{name}"' in actions


def test_every_picker_string_ships_in_twelve_languages():
    import json

    strings = [P.OFF, P.SUGGESTION_BASIS, P.FIRST_BASIS, "Start with {country}", P.DIFF_METHOD, P.DIFF_CAVEAT, P.CADENCE,
               P._NO_EXTRACT["ru"], "No continent extract is known for this code.",
               "Paused: airplane mode is on", "Read · data as of {date}",
               "{country}, date not stated in the extract", "Countries for the map data"]
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc, (path.name, s)


# --------------------------------------------------------------------------- #
#  The origin country first (R76), and the laws row                          #
# --------------------------------------------------------------------------- #


def test_the_language_row_opens_with_its_origin_country_then_alphabetical(settings_file):
    """R76 (answer 3, 2026-09-29): French -> France first, then the rest alphabetically."""
    from src.civic.coverage_floor import load_floor

    rows = P.suggestions("fr")
    assert rows[0]["cc"] == "fr" and rows[0]["origin"] is True
    names = [r["name"].casefold() for r in rows[1:]]
    assert names == sorted(names)
    assert not any(r["origin"] for r in rows[1:])
    floor = {r["cc"] for r in load_floor()["languages"]["fr"]["countries"]}
    assert {r["cc"] for r in rows} == floor


def test_every_interface_language_has_an_origin_country_in_its_own_floor():
    """The origin must be one of the language's own countries, or the row would invent one."""
    import json

    from src.civic.coverage_floor import load_floor

    floor = load_floor()["languages"]
    langs = {p.stem for p in (STATIC / "locales").glob("*.json")}
    assert set(P.ORIGIN_COUNTRY) == langs
    for lang, cc in P.ORIGIN_COUNTRY.items():
        assert cc in {r["cc"] for r in floor[lang]["countries"]}, lang
    assert (P.origin_country("en"), P.origin_country("es"), P.origin_country("fr")) == ("gb", "es", "fr")
    assert json  # the locales are read by name only


def test_the_origin_country_is_the_default_first_import_until_one_is_chosen(settings_file):
    state = P.picker_state("en", [])
    assert state["enabled"] is False and state["first"]["cc"] == "gb"
    assert state["first_basis"] == P.FIRST_BASIS
    P.save_selection(["de"])
    state = P.picker_state("en", [])
    assert state["enabled"] is True and state["first"] is None


def test_the_laws_row_is_the_watched_jurisdictions_that_are_countries():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Base, LawDocument

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[LawDocument.__table__])
    with Session(eng) as s:
        for i, (jur, watched) in enumerate(
            [("fr", True), ("fr", True), ("uk", True), ("eu", True), ("int", True), ("de", False)]
        ):
            s.add(LawDocument(jurisdiction=jur, url=f"https://example.org/{i}", title=f"t{i}", watched=watched))
        s.commit()
        rows = P.law_countries(s)
    assert [(r["cc"], r["law_documents"]) for r in rows] == [("fr", 2), ("gb", 1)]
    assert rows[0]["extract"]["code"] == "europe"


def test_a_failed_law_read_is_said_not_shown_as_an_empty_row(settings_file):
    assert P.picker_state("fr", None)["law_unavailable"] is True
    state = P.picker_state("fr", [])
    assert state["law_unavailable"] is False and state["law_suggested"] == []
    assert state["law_basis"] == P.LAW_BASIS
