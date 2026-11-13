"""Climate -> Your place (R675): the anomaly view's privacy and consent refusals.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What R675 asks, each pinned as a refusal: the place is ROUNDED before it leaves the machine; the
route refuses without ``consent: true`` and under the kill switch, before any fetch; the slices are
kept in the encrypted key-value store and never in a loose file; a re-view reads only what is held
and sends nothing; the activity readout never shows the coordinates. Fixtures are hand-built; the
live Open-Meteo shape is unverified from this sandbox.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ingest import activate_kill_switch, clear_kill_switch
from src.weather import anomaly, held
from src.weather.openmeteo import build_archive_url

_ROOT = Path(__file__).resolve().parents[1]
UNITS = {"temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"}


def _slice(lat, lon, start, end, value=1.0):
    days, d = [], start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    daily = {"time": [x.isoformat() for x in days]}
    for v in UNITS:
        daily[v] = [value for _ in days]
    url = build_archive_url(lat, lon, start, end, sorted(anomaly.SUPPORTED))
    return {"ok": True, "daily": daily, "units": dict(UNITS), "cached": False, "label": None,
            "provenance": {"requested_url": url, "fetched_at": "2026-11-13T10:00:00+00:00"}}


class _Mem:
    def __init__(self):
        self.d = {}

    def get(self, url):
        return self.d.get(url)

    def put(self, url, payload):
        self.d[url] = payload


@pytest.fixture()
def fake_fetch(monkeypatch):
    calls = []

    def fake(lat, lon, s, e, vs, **kw):
        calls.append({"lat": lat, "lon": lon, "start": s, "end": e, "vars": tuple(vs), **kw})
        return _slice(lat, lon, s, e)

    monkeypatch.setattr(anomaly, "fetch_daily_slice", fake)
    return calls


W = (date(2023, 5, 1), date(2023, 5, 3))


def test_the_place_is_rounded_to_one_decimal_before_it_is_sent(fake_fetch):
    assert anomaly.place(48.85661, 2.35222) == (48.9, 2.4)
    assert anomaly.place(-0.04, -0.04) == (0.0, 0.0) and str(anomaly.place(-0.04, 0)[0]) == "0.0"
    anomaly.fetch_anomalies(48.85661, 2.35222, *W, store=_Mem())
    assert {(c["lat"], c["lon"]) for c in fake_fetch} == {(48.9, 2.4)}
    # Never through the loose JSON file cache.
    assert all(c["use_file_cache"] is False for c in fake_fetch)


def test_a_second_window_for_the_same_place_fetches_only_the_window(fake_fetch):
    mem = _Mem()
    anomaly.fetch_anomalies(48.85661, 2.35222, *W, store=mem)
    assert len(fake_fetch) == 2
    out = anomaly.fetch_anomalies(48.86, 2.36, date(2023, 6, 1), date(2023, 6, 2), store=mem)
    assert len(fake_fetch) == 3 and fake_fetch[-1]["start"] == date(2023, 6, 1)
    assert out["provenance"]["baseline_cached"] is True and out["provenance"]["window_cached"] is False


def test_a_re_view_reads_only_what_is_held_and_sends_nothing(fake_fetch):
    mem = _Mem()
    first = anomaly.held_anomalies(48.85661, 2.35222, *W, store=mem)
    assert first["held"] is False and first["missing"] == ["baseline", "window"] and "results" not in first
    anomaly.fetch_anomalies(48.85661, 2.35222, *W, store=mem)
    n = len(fake_fetch)
    again = anomaly.held_anomalies(48.85661, 2.35222, *W, store=mem)
    assert len(fake_fetch) == n, "a re-view never fetches"
    assert again["held"] is True and again["place"]["lat"] == 48.9
    assert all(r["value"] == 0.0 for r in again["results"] if r["kind"] == "mean")


def test_a_failed_fetch_keeps_nothing_and_names_the_stage(monkeypatch):
    mem = _Mem()
    monkeypatch.setattr(anomaly, "fetch_daily_slice", lambda *a, **k: {"ok": False, "verdict": "network-refused"})
    out = anomaly.fetch_anomalies(1, 2, *W, store=mem)
    assert out["ok"] is False and out["stage"] == "baseline" and mem.d == {}


def test_a_store_that_cannot_write_still_shows_the_numbers_and_says_so(fake_fetch):
    class Broken(_Mem):
        def put(self, url, payload):
            raise OSError("locked")

    out = anomaly.fetch_anomalies(1, 2, *W, store=Broken())
    assert out["ok"] is True and out["kept"] is False


def test_held_slices_live_in_the_key_value_store_keyed_by_the_url_hash(monkeypatch):
    box = {}
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda k: box.get(k))
    monkeypatch.setattr("src.config.kv_store.kv_set_json", lambda k, v: box.__setitem__(k, v))
    url = build_archive_url(48.9, 2.4, *W, sorted(anomaly.SUPPORTED))
    payload = _slice(48.9, 2.4, *W)
    held.HeldSlices().put(url, payload)
    (key,) = box
    assert key.startswith("weather.slice.") and "48.9" not in key, "the key carries no readable coordinate"
    assert held.HeldSlices().get(url) == payload
    # A row whose own URL is another place's is a miss, never another place's numbers.
    other = build_archive_url(10.0, 10.0, *W, sorted(anomaly.SUPPORTED))
    box[held.slice_key(other)] = payload
    assert held.HeldSlices().get(other) is None


def test_the_slice_fetch_writes_no_file_when_the_caller_keeps_it(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.weather import openmeteo

    monkeypatch.setattr(openmeteo, "data_dir", lambda: tmp_path)
    body = b'{"daily": {"time": ["2023-05-01"], "precipitation_sum": [1.0]}, "daily_units": {"precipitation_sum": "mm"}}'

    class F:
        def fetch(self, url, require_html=False):
            from datetime import datetime

            return SimpleNamespace(content=body, final_url=url, status_code=200, fetched_at=datetime.now(UTC))

    out = openmeteo.fetch_daily_slice(1.0, 2.0, date(2023, 5, 1), date(2023, 5, 1), ["precipitation_sum"],
                                      fetcher=F(), use_file_cache=False)
    assert out["ok"] is True
    assert not any(tmp_path.rglob("*")), "nothing written to disk"


# --- the route ---------------------------------------------------------------------------- #
@pytest.fixture()
def client():
    from src.api import weather

    app = FastAPI()
    app.include_router(weather.router)
    return TestClient(app)


def _body(**over):
    b = {"lat": 48.85661, "lon": 2.35222, "start_date": "2023-05-01", "end_date": "2023-05-03"}
    b.update(over)
    return b


def test_the_route_refuses_without_consent_before_any_fetch(client, monkeypatch):
    called = []
    monkeypatch.setattr("src.weather.anomaly.fetch_anomalies", lambda *a, **k: called.append(1))
    r = client.post("/api/weather/anomaly", json=_body())
    assert r.status_code == 400 and "Open-Meteo" in r.json()["detail"] and not called


def test_the_route_refuses_under_the_kill_switch_and_names_it(client, monkeypatch):
    from src.ingest.fetch_verdict import NETWORK_REFUSED

    called = []
    monkeypatch.setattr("src.weather.anomaly.fetch_anomalies", lambda *a, **k: called.append(1))
    activate_kill_switch()
    try:
        r = client.post("/api/weather/anomaly", json=_body(consent=True))
    finally:
        clear_kill_switch()
    assert r.status_code == 409 and r.json()["detail"] == NETWORK_REFUSED and not called


def test_the_held_read_works_in_airplane_mode_and_never_fetches(client, monkeypatch):
    monkeypatch.setattr("src.weather.anomaly.fetch_daily_slice", lambda *a, **k: pytest.fail("a held read fetched"))
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda k: None)
    activate_kill_switch()
    try:
        r = client.get("/api/weather/anomaly/held", params={"lat": 48.85, "lon": 2.35, "start_date": "2023-05-01", "end_date": "2023-05-03"})
    finally:
        clear_kill_switch()
    assert r.status_code == 200 and r.json()["held"] is False and r.json()["place"]["lat"] == 48.9


@pytest.mark.parametrize("params", [
    {"lat": 91, "lon": 0, "start_date": "2023-05-01", "end_date": "2023-05-03"},
    {"lat": 0, "lon": 0, "start_date": "2023-05-03", "end_date": "2023-05-01"},
    {"lat": 0, "lon": 0, "start_date": "2020-01-01", "end_date": "2021-06-01"},
    {"lat": 0, "lon": 0, "start_date": "1939-12-01", "end_date": "1940-01-02"},
])
def test_the_held_read_refuses_a_window_the_fetch_would_refuse(client, params):
    assert client.get("/api/weather/anomaly/held", params=params).status_code == 422


# --- what the rest of the app can see ---------------------------------------------------- #
def test_the_activity_readout_never_shows_the_coordinates():
    from src.monitoring.activity import ActivityMonitor

    mon = ActivityMonitor()
    url = build_archive_url(48.9, 2.4, *W, sorted(anomaly.SUPPORTED))
    tok = mon.fetch_started(url)
    shown = mon.snapshot()["current_fetch"]["url"]
    mon.fetch_finished(tok)
    last = mon.snapshot()["last_url"]
    for s in (shown, last):
        assert "48.9" not in s and "latitude" not in s and s.startswith("https://archive-api.open-meteo.com/")
    # Other hosts keep their query (it is the feed's address, not a person's place).
    tok = mon.fetch_started("https://example.org/feed?page=2")
    assert mon.snapshot()["current_fetch"]["url"].endswith("?page=2")
    mon.fetch_finished(tok)


def test_the_view_asks_consent_names_the_rounded_place_and_reads_held_first():
    js = (_ROOT / "src" / "static" / "app-climate.js").read_text(encoding="utf-8")
    from tests.js_source_helper import function_body

    body = function_body(js, "climatePlaceShow")
    held_at, gate_at, post_at = (body.find(s) for s in ('"/api/weather/anomaly/held?', "ensureOnline(", '"/api/weather/anomaly", {method: "POST"'))
    assert -1 < held_at < gate_at < post_at, "held read first, then the ONE consent, then the request"
    assert "consent: true" in body and "rounded to 0.1 degree" in body
    assert "window.confirm(ask)" in body and "ensureOnline(ask)" in body, \
        "asked for every request: a confirmation when already online, the consent popup otherwise"
    assert "climatePlaceRound(q.lat)" in body, "the browser rounds too, so the popup names what is sent"
    save = function_body(js, "_climatePlaceSave")
    assert "climatePlaceRound(q.lat)" in save and "climatePlaceRound(q.lon)" in save, \
        "browser storage keeps only the rounded place, never the coordinates as typed"


def test_the_node_renderer_checks_pass():
    proc = subprocess.run(["node", str(_ROOT / "tests" / "climate_node_test.js")], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
