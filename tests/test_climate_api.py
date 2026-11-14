"""The Climate tab's API and store: the gate on the one egressing route, R662's storage, the reads.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No test here opens a socket: the fetchers are replaced by a stand-in that returns what the real
parsers make of hand-built bodies (the live shapes are operator checks, OPEN_QUEUE 33(j)).
"""

from __future__ import annotations

import contextlib
import pathlib
import re
import subprocess
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import climate as climate_api
from src.database.models import AppState, Base
from src.database.models import StatFigure as StatFigureRow
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.stats import climate
from src.stats.oni import parse_oni
from src.stats.sdmx import StatFigure

ONI_V1 = "SEAS YR   TOTAL ANOM\nDJF  1950 24.72 -1.53\nJFM  1950 25.17 -1.34\nFMA  1950 25.75 -99.9\n"
ONI_V2 = "SEAS YR   TOTAL ANOM\nDJF  1950 24.72 -1.53\nJFM  1950 25.17 -1.30\nFMA  1950 25.75 -99.9\n"


@pytest.fixture()
def maker():
    engine = create_engine(
        "sqlite:///:memory:", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


@pytest.fixture()
def db(maker):
    with maker() as s:
        yield s


@pytest.fixture()
def client(maker, monkeypatch):
    @contextlib.contextmanager
    def scope():
        s = maker()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr("src.database.session.session_scope", scope)
    app = FastAPI()
    app.include_router(climate_api.router)
    return TestClient(app)


def _oni_fetchers(text: str, stamp: str):
    calls: list[str] = []

    def fetch_oni():
        calls.append("oni")
        return parse_oni(text, extracted_at=stamp)

    return types.SimpleNamespace(fetch_oni=fetch_oni, ONI_URL="https://example.invalid/oni", calls=calls)


def _rows(db) -> int:
    return db.execute(select(func.count(StatFigureRow.id))).scalar_one()


# --- R662: new or revised observations only ------------------------------------------------- #
def test_an_identical_refetch_adds_zero_observation_rows(db):
    climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(ONI_V1, "2026-11-01T00:00:00+00:00"))
    first = _rows(db)
    assert first == 6  # three seasons x (anomaly, total), the sentinel kept as a gap
    record = climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(ONI_V1, "2026-11-02T00:00:00+00:00"))
    assert _rows(db) == first
    assert record["tally"]["new"] == 0 and record["tally"]["revised"] == 0 and record["tally"]["unchanged"] == 6
    # The re-fetch is still recorded, with its own timestamp.
    assert climate.load_record(db, "oni", None)["fetched_at"] == "2026-11-02T00:00:00+00:00"


def test_a_revised_value_is_a_new_row_and_the_earlier_vintage_stays_readable(db):
    climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(ONI_V1, "2026-11-01T00:00:00+00:00"))
    record = climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(ONI_V2, "2026-11-02T00:00:00+00:00"))
    assert record["tally"]["revised"] == 1 and record["tally"]["unchanged"] == 5
    trail = db.execute(
        select(StatFigureRow.value, StatFigureRow.extracted_at)
        .where(StatFigureRow.series_id == "oni.anom", StatFigureRow.time_period == "1950-JFM")
        .order_by(StatFigureRow.extracted_at)
    ).all()
    assert trail == [(-1.34, "2026-11-01T00:00:00+00:00"), (-1.30, "2026-11-02T00:00:00+00:00")]
    shown = climate.read_series(db, "oni", "oni.anom", "nino34")
    by_period = {p["p"]: p["v"] for p in shown["points"]}
    assert by_period["1950-JFM"] == -1.30  # the chart shows the latest vintage
    assert shown["periods_with_several_vintages"] == 1


def test_a_period_the_publisher_stopped_serving_is_counted_never_deleted(db):
    climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(ONI_V1, "2026-11-01T00:00:00+00:00"))
    shorter = "SEAS YR   TOTAL ANOM\nDJF  1950 24.72 -1.53\nJFM  1950 25.17 -1.34\n"
    record = climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(shorter, "2026-11-02T00:00:00+00:00"))
    assert record["tally"]["withdrawn"] == 2  # FMA's anomaly and total
    assert any("1950-FMA" in w for w in record["tally"]["withdrawn_sample"])
    assert _rows(db) == 6


def test_a_period_repeated_inside_one_file_is_counted_and_never_breaks_the_fetch(db):
    twice = ONI_V1 + "JFM  1950 25.17 -1.34\n"
    record = climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(twice, "2026-11-01T00:00:00+00:00"))
    assert _rows(db) == 6  # the first copy kept, the repeat not stored
    assert record["tally"]["repeated"] == 2  # its anomaly and its total


@pytest.mark.parametrize("cell", ["nan", "inf", "-inf", "1e999"])
def test_a_non_finite_oni_cell_is_refused_never_stored(cell):
    parsed = parse_oni("SEAS YR   TOTAL ANOM\nDJF  1950 24.72 " + cell + "\n", extracted_at="2026-11-01T00:00:00+00:00")
    assert not parsed.figures


def test_a_gap_stays_a_gap_on_the_chart(db):
    climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(ONI_V1, "2026-11-01T00:00:00+00:00"))
    shown = climate.read_series(db, "oni", "oni.anom", "nino34")
    assert shown["gaps"] == 1 and shown["n"] == 2
    assert {p["p"]: p["v"] for p in shown["points"]}["1950-FMA"] is None


def test_oni_seasons_are_placed_at_their_middle_month():
    assert climate._place("oni", "1950-DJF") == "1950-01-15"  # Dec 1949, Jan 1950, Feb 1950
    assert climate._place("oni", "1950-NDJ") == "1950-12-15"
    assert climate._place("gistemp", "1990") == "1990-07-01"
    assert climate._place("gistemp", "1990-03") == "1990-03-15"
    assert climate._place("nsidc", "2020-09-16") == "2020-09-16"
    assert climate._place("gistemp", "1990-DJF") is None  # only ONI has seasons


def test_the_fetch_record_lands_in_the_same_transaction(db):
    climate.fetch_and_store(db, "oni", None, fetchers=_oni_fetchers(ONI_V1, "2026-11-01T00:00:00+00:00"))
    db.rollback()
    assert _rows(db) == 0
    assert db.get(AppState, climate.record_key("oni", None)) is None


# --- params are checked before anything is sent ----------------------------------------------- #
@pytest.mark.parametrize("station", ["", "USW0009472", "USW000947288", "../etc/passw", "usw0009472!", "US W0094728"])
def test_a_malformed_station_is_refused_before_any_fetch(station):
    with pytest.raises(ValueError, match="GHCN station id"):
        climate.valid_param("ghcnd", station)


def test_a_station_id_is_normalised_to_upper_case():
    assert climate.valid_param("ghcnd", " usw00094728 ") == "USW00094728"


def test_every_dataset_dispatches_to_its_own_fetcher(db):
    seen: list[tuple] = []

    class _P:
        def __init__(self, figs):
            self.figures = figs

        def summary(self):
            return {"coverage_gaps": {"2020-01-01": 0.1}} if seen and seen[-1][0] == "nsidc" else {}

    def fig(agency, series, area, period="2020"):
        return StatFigure(agency=agency, series_id=series, ref_area=area, time_period=period, value=1.0,
                          unit="u", methodology_ref="m", adjustment=None, base_year=None,
                          extracted_at="2026-11-01T00:00:00+00:00")

    def rec(name, *args):
        seen.append((name, *args))

    f = types.SimpleNamespace(
        fetch_gistemp=lambda r: rec("gistemp", r) or _P([fig("us-nasa-giss", "gistemp.monthly", r, "2020-01")]),
        gistemp_url=lambda r: f"g/{r}",
        fetch_nsidc=lambda r: rec("nsidc", r) or _P([fig("us-nsidc", "nsidc.sea_ice_extent_daily", r, "2020-01-01")]),
        nsidc_url=lambda r: f"n/{r}",
        fetch_usgs_quakes=lambda a, b, m: rec("usgs", a, m) or _P([]),
        usgs_quakes_count_url=lambda a, b, m: "c", usgs_quakes_query_url=lambda a, b, m: "q",
        fetch_owid_dataset=lambda d: rec("owid", d) or _P([fig("owid", f"{d}.co2", "FRA")]),
        owid_dataset_url=lambda d: f"o/{d}",
        fetch_ghcnd_station=lambda s: rec("ghcnd", s) or _P([fig("us-noaa-ncei", "ghcnd.TMAX", s, "2020-01-01")]),
        ghcnd_url=lambda s: f"s/{s}",
    )
    climate.fetch_and_store(db, "gistemp", "NH", fetchers=f)
    climate.fetch_and_store(db, "nsidc", "S", fetchers=f)
    climate.fetch_and_store(db, "usgs", None, fetchers=f)
    climate.fetch_and_store(db, "owid", "co2", fetchers=f)
    climate.fetch_and_store(db, "ghcnd", "USW00094728", fetchers=f)
    assert [s[0] for s in seen] == ["gistemp", "nsidc", "usgs", "owid", "ghcnd"]
    assert seen[2] == ("usgs", "1973-01", 6.0)
    nsidc_rec = climate.load_record(db, "nsidc", "S")
    assert "coverage_gaps" not in nsidc_rec["diagnostics"] and nsidc_rec["diagnostics"]["coverage_gap_days"] == 1
    assert climate.load_record(db, "ghcnd", "USW00094728")["requested_urls"] == ["s/USW00094728"]


# --- the API -------------------------------------------------------------------------------- #
def test_the_fetch_refuses_under_the_kill_switch_and_names_airplane_mode(client, monkeypatch):
    monkeypatch.setattr(climate_api._FETCH_JOB, "start", lambda **kw: pytest.fail("started"))
    activate_kill_switch()
    try:
        r = client.post("/api/climate/fetch", json={"dataset": "oni", "consent": True})
    finally:
        clear_kill_switch()
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == NETWORK_REFUSED
    assert "airplane mode" in r.json()["detail"].lower()


def test_the_fetch_demands_consent_on_its_own(client, monkeypatch):
    monkeypatch.setattr(climate_api._FETCH_JOB, "start", lambda **kw: pytest.fail("started"))
    clear_kill_switch()
    for body in ({"dataset": "oni"}, {"dataset": "oni", "consent": False}):
        r = client.post("/api/climate/fetch", json=body)
        assert r.status_code == 400, r.text
        assert "consent" in r.json()["detail"]


def test_a_bad_station_is_a_plain_422_even_with_consent(client, monkeypatch):
    monkeypatch.setattr(climate_api._FETCH_JOB, "start", lambda **kw: pytest.fail("started"))
    clear_kill_switch()
    r = client.post("/api/climate/fetch", json={"dataset": "ghcnd", "param": "../../x", "consent": True})
    assert r.status_code == 422 and "GHCN station id" in r.json()["detail"]
    r = client.post("/api/climate/fetch", json={"dataset": "fires", "consent": True})
    assert r.status_code == 422


def test_a_consented_fetch_starts_the_job_with_the_normalised_param(client, monkeypatch):
    started = []
    monkeypatch.setattr(climate_api._FETCH_JOB, "start", lambda **kw: started.append(kw) or {"state": "running"})
    clear_kill_switch()
    r = client.post("/api/climate/fetch", json={"dataset": "ghcnd", "param": "usw00094728", "consent": True})
    assert r.status_code == 200 and r.json()["started"] is True
    assert started == [{"dataset": "ghcnd", "param": "USW00094728"}]


def test_a_second_click_while_running_reports_the_live_job(client, monkeypatch):
    def busy(**kw):
        raise RuntimeError("already running")

    monkeypatch.setattr(climate_api._FETCH_JOB, "start", busy)
    clear_kill_switch()
    r = client.post("/api/climate/fetch", json={"dataset": "oni", "consent": True})
    assert r.status_code == 200 and r.json()["started"] is False


def test_the_reads_work_in_airplane_mode_from_local_storage(client, maker):
    with maker() as s:
        climate.fetch_and_store(s, "oni", None, fetchers=_oni_fetchers(ONI_V1, "2026-11-01T00:00:00+00:00"))
        s.commit()
    activate_kill_switch()
    try:
        d = client.get("/api/climate/datasets").json()
        oni_unit = next(u for u in d["units"] if u["dataset"] == "oni")
        assert oni_unit["stored"]["stored_rows"] == 6
        assert oni_unit["last_fetch"]["fetched_at"] == "2026-11-01T00:00:00+00:00"
        assert oni_unit["licence"] and oni_unit["source_page"].startswith("https://")
        # The first station fetch's consent popup names its host before any station is stored.
        assert d["hosts"]["ghcnd"] == climate.DATASETS["ghcnd"].host and set(d["hosts"]) == set(climate.DATASETS)
        r = client.get("/api/climate/series", params={"dataset": "oni", "series_id": "oni.anom", "area": "nino34"})
        assert r.status_code == 200 and r.json()["n"] == 2
    finally:
        clear_kill_switch()
    # Seven units before any station: GISTEMP x3, NSIDC x2, ONI, USGS, OWID x2.
    assert len(d["units"]) == 9


def test_series_refuses_a_series_or_area_outside_the_dataset(client):
    r = client.get("/api/climate/series", params={"dataset": "oni", "series_id": "worldbank.gdp", "area": "nino34"})
    assert r.status_code == 404
    r = client.get("/api/climate/series", params={"dataset": "oni", "series_id": "oni.anom", "area": "GLB"})
    assert r.status_code == 404
    r = client.get("/api/climate/series", params={"dataset": "gistemp", "param": "XX", "series_id": "gistemp.monthly", "area": "XX"})
    assert r.status_code == 422


def test_ghcn_stations_already_fetched_become_units(client, maker):
    f = types.SimpleNamespace(
        fetch_ghcnd_station=lambda s: types.SimpleNamespace(
            figures=[StatFigure(agency="us-noaa-ncei", series_id="ghcnd.TMAX", ref_area=s, time_period="2020-01-01",
                                value=3.0, unit="degC", methodology_ref="m", adjustment=None, base_year=None,
                                extracted_at="2026-11-01T00:00:00+00:00")],
            summary=lambda: {}),
        ghcnd_url=lambda s: f"s/{s}",
    )
    with maker() as s:
        climate.fetch_and_store(s, "ghcnd", "USW00094728", fetchers=f)
        s.commit()
    d = client.get("/api/climate/datasets").json()
    st = [u for u in d["units"] if u["dataset"] == "ghcnd"]
    assert [u["param"] for u in st] == ["USW00094728"] and st[0]["stored"]["stored_rows"] == 1
    a = client.get("/api/climate/areas", params={"dataset": "ghcnd"}).json()
    assert [x["code"] for x in a["areas"]] == ["USW00094728"]


def test_each_dataset_names_the_host_its_fetcher_reaches():
    from urllib.parse import urlparse

    from src.stats import fetch

    bases = {
        "gistemp": fetch.GISTEMP_BASE, "nsidc": fetch.NSIDC_BASE, "oni": fetch.ONI_URL,
        "usgs": fetch.USGS_QUAKES_BASE, "owid": fetch.OWID_BULK_BASE, "ghcnd": fetch.GHCND_BASE,
    }
    assert set(bases) == set(climate.DATASETS)
    for ds_id, base in bases.items():
        assert climate.DATASETS[ds_id].host == urlparse(base).hostname, ds_id


# --- the UI ---------------------------------------------------------------------------------- #
_STATIC = pathlib.Path(__file__).resolve().parents[1] / "src" / "static"


def test_the_renderers_behave():
    proc = subprocess.run(["node", str(pathlib.Path(__file__).with_name("climate_node_test.js"))],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_tab_uses_the_one_subtab_component_and_no_inline_handlers():
    js = (_STATIC / "app-climate.js").read_text(encoding="utf-8")
    assert "ooSubtabs(nav, showClimateView" in js, "invariant #18: one subtab component"
    assert "onclick" not in js.lower().replace("_climateclick", ""), "no inline handlers"
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    page = html.split('id="tab-climate"', 1)[1].split('id="tab-indices"', 1)[0]
    assert "onclick" not in page.lower()
    assert html.index('src="/static/app-climate.js"') > html.index('src="/static/app-markets.js"'), "ooSubtabs loads first"


def test_the_only_request_the_tab_makes_off_the_machine_goes_through_the_consent():
    js = (_STATIC / "app-climate.js").read_text(encoding="utf-8")
    # Every request is the app's own loopback api(); no fetch(), no XHR, no absolute URL is requested.
    assert "fetch(" not in js.replace("climateFetch(", "").replace("_climateFetch", "")
    assert "XMLHttpRequest" not in js
    calls = re.findall(r'api\("([^"]+)"', js)
    # /api/system/network is the loopback read of airplane mode that decides between the consent
    # popup and the per-request confirmation for a typed place (R675); it sends nothing out.
    assert calls and all(c.startswith(("/api/climate/", "/api/weather/anomaly", "/api/system/network"))
                         for c in calls), calls
