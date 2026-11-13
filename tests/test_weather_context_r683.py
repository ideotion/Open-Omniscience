"""R683: the Home card's (and the Claim Workspace's) weather context gets the R675 treatment.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What is pinned here, each a refusal:

* the place is rounded to 0.1 degree before it is sent or kept, by the same arithmetic the page uses
  to name it in the question (a tie goes UP on both sides);
* a fetched slice is kept in the encrypted store, never a loose file under the data folder;
* the plaintext folder older versions wrote is deleted at startup, and nothing of it survives;
* after a panic wipe, nothing of the weather slices is left;
* the route refuses a fetch without consent (400) and under the kill switch (409), and answers a
  slice already held locally with neither;
* the shared question (``ooAskToSendPlace``) names the rounded place and the host, and asks for every
  request: the consent popup when offline, a confirmation when already online;
* a failure to keep a slice is logged without the URL (it carries the place).
"""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
_BODY = (b'{"daily": {"time": ["2023-05-01"], "precipitation_sum": [1.0]},'
         b' "daily_units": {"precipitation_sum": "mm"}}')


class _Fetcher:
    def __init__(self):
        self.urls: list[str] = []

    def fetch(self, url, require_html=False):
        self.urls.append(url)
        return SimpleNamespace(content=_BODY, final_url=url, status_code=200, fetched_at=datetime.now(UTC))


class _Mem:
    def __init__(self):
        self.d: dict = {}

    def get(self, url):
        return self.d.get(url)

    def put(self, url, payload):
        self.d[url] = payload


@pytest.fixture()
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


# --- rounding ------------------------------------------------------------------------------- #
@pytest.mark.parametrize(("raw", "rounded"), [
    (48.85661, 48.9), (2.35222, 2.4), (0.25, 0.3), (-0.25, -0.2), (7.75, 7.8), (-0.04, 0.0), (-1.2864, -1.3),
    (89.96, 90.0), (-179.96, -180.0),
])
def test_the_place_is_rounded_with_the_pages_arithmetic(raw, rounded):
    from src.weather.openmeteo import round_place

    assert round_place(raw, raw) == (rounded, rounded)
    assert str(round_place(-0.04, 0)[0]) == "0.0", "no -0.0 is sent or keyed"


def test_the_page_rounds_the_same_numbers_the_same_way():
    """The page names the place it asks consent for; it must be the place the server sends."""
    from src.weather.openmeteo import round_place

    values = [48.85661, 2.35222, 0.25, -0.25, 7.75, -0.04, -1.2864, 0.05, 0.15, 1.45, -2.35, 12.349999]
    script = (
        "const APP = require(" + repr(str(_ROOT / "tests" / "app_source.js")) + ").appJs();\n"
        "const at = APP.indexOf('function ooRoundPlace(');\n"
        "const end = APP.indexOf('\\n    }\\n', at) + 6;\n"
        "const ooRoundPlace = new Function(APP.slice(at, end) + '\\nreturn ooRoundPlace;')();\n"
        "console.log(JSON.stringify(" + repr(values) + ".map(ooRoundPlace)));\n"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60, cwd=_ROOT)
    assert proc.returncode == 0, proc.stderr
    import json

    page = json.loads(proc.stdout)
    assert page == [round_place(v, 0)[0] for v in values]


def test_every_request_url_carries_only_the_rounded_place():
    from src.weather.openmeteo import build_archive_url

    url = build_archive_url(48.85661, 2.35222, date(2023, 5, 1), date(2023, 5, 1), ["precipitation_sum"])
    assert "latitude=48.9000&longitude=2.4000" in url
    assert "48.85" not in url and "2.35" not in url


# --- keeping -------------------------------------------------------------------------------- #
def test_a_kept_slice_goes_to_the_store_and_nothing_to_disk(data_dir):
    from src.weather import openmeteo

    mem, f = _Mem(), _Fetcher()
    out = openmeteo.fetch_daily_slice(48.85661, 2.35222, date(2023, 5, 1), date(2023, 5, 1), ["precipitation_sum"],
                                      label="Paris", fetcher=f, store=mem)
    assert out["ok"] is True and out["kept"] is True and out["label"] == "Paris"
    assert list(mem.d) == f.urls and "latitude=48.9000" in f.urls[0]
    kept = mem.d[f.urls[0]]
    assert "label" not in kept and "cached" not in kept, "the store holds the slice, not one request's label"
    assert not any(p.is_file() for p in data_dir.rglob("*")), "nothing written under the data folder"
    again = openmeteo.fetch_daily_slice(48.86, 2.36, date(2023, 5, 1), date(2023, 5, 1), ["precipitation_sum"],
                                        fetcher=f, store=mem)
    assert again["cached"] is True and len(f.urls) == 1, "the same rounded place is answered locally"


def test_a_failure_to_keep_is_said_and_logged_without_the_place(data_dir, caplog):
    from src.weather import openmeteo

    class Broken:
        def get(self, url):
            raise RuntimeError("locked " + url)

        def put(self, url, payload):
            raise RuntimeError("locked " + url)

    f = _Fetcher()
    with caplog.at_level(logging.DEBUG):
        out = openmeteo.fetch_daily_slice(48.85661, 2.35222, date(2023, 5, 1), date(2023, 5, 1),
                                          ["precipitation_sum"], fetcher=f, store=Broken())
    assert out["ok"] is True and out["kept"] is False
    for rec in caplog.records:
        msg = rec.getMessage()
        assert "48.9" not in msg and "latitude" not in msg, msg


# --- the plaintext folder older versions wrote --------------------------------------------- #
def test_the_plaintext_folder_is_deleted_once_and_then_nothing_happens(data_dir):
    from src.weather.openmeteo import LEGACY_CACHE_DIR, purge_plaintext_cache

    old = data_dir / LEGACY_CACHE_DIR
    old.mkdir()
    for i in range(3):
        (old / f"{i:024x}.json").write_text('{"ok": true, "provenance": {"requested_url": "latitude=48.8566"}}')
    (data_dir / "keep.txt").write_text("unrelated")
    assert purge_plaintext_cache() == 3
    assert not old.exists(), "no plaintext coordinate file remains"
    assert (data_dir / "keep.txt").exists(), "only the weather folder is touched"
    assert purge_plaintext_cache() == 0


def test_startup_upkeep_runs_the_purge():
    from tests.js_source_helper import function_body  # noqa: F401  (import check only; the read below is plain text)

    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    start = src.index("def _run_startup_upkeep(")
    end = src.index("\ndef ", start + 1)
    assert "purge_plaintext_cache()" in src[start:end], "the purge runs on the first start after the update"


def test_a_panic_wipe_leaves_nothing_of_the_weather_slices(data_dir):
    from src.ingest import clear_kill_switch
    from src.safety import panic_wipe
    from src.weather import openmeteo

    (data_dir / openmeteo.LEGACY_CACHE_DIR).mkdir()
    (data_dir / openmeteo.LEGACY_CACHE_DIR / "a.json").write_text("{}")
    (data_dir / "oo.db").write_bytes(b"x" * 64)  # where app_state, and so every held slice, lives
    try:
        panic_wipe(data_dir, confirm=True)
    finally:
        clear_kill_switch()
    assert not data_dir.exists()
    assert not list(Path(data_dir.parent).glob("**/" + openmeteo.LEGACY_CACHE_DIR))


# --- the route ------------------------------------------------------------------------------ #
@pytest.fixture()
def client(monkeypatch):
    from src.api import weather

    box: dict = {}
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda k: box.get(k))
    monkeypatch.setattr("src.config.kv_store.kv_set_json", lambda k, v: box.__setitem__(k, v))
    app = FastAPI()
    app.include_router(weather.router)
    c = TestClient(app)
    c.box = box  # type: ignore[attr-defined]
    return c


_REQ = {"lat": 48.85661, "lon": 2.35222, "start_date": "2023-05-01", "end_date": "2023-05-01",
        "variables": ["precipitation_sum"]}


def test_the_route_refuses_without_consent_and_in_airplane_mode(client, monkeypatch):
    import src.safety.fetcher as sf
    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.ingest.fetch_verdict import NETWORK_REFUSED

    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: pytest.fail("refused requests build no fetcher"))
    r = client.post("/api/weather/context", json=_REQ)
    assert r.status_code == 400 and "Open-Meteo" in r.json()["detail"]
    activate_kill_switch()
    try:
        r = client.post("/api/weather/context", json={**_REQ, "consent": True})
        assert r.status_code == 409 and r.json()["detail"] == NETWORK_REFUSED
    finally:
        clear_kill_switch()


def test_a_held_slice_is_answered_without_consent_even_in_airplane_mode(client, monkeypatch):
    import src.safety.fetcher as sf
    from src.ingest import activate_kill_switch, clear_kill_switch

    f = _Fetcher()
    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: f)
    first = client.post("/api/weather/context", json={**_REQ, "consent": True}).json()
    assert first["ok"] is True and first["kept"] is True and len(f.urls) == 1
    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: pytest.fail("a held slice builds no fetcher"))
    activate_kill_switch()
    try:
        again = client.post("/api/weather/context", json=_REQ).json()
    finally:
        clear_kill_switch()
    assert again["ok"] is True and again["cached"] is True
    assert again["provenance"]["fetched_at"] == first["provenance"]["fetched_at"]


# --- the question the page asks ------------------------------------------------------------- #
def test_every_weather_button_asks_through_the_one_helper_naming_place_and_host():
    from tests.js_source_helper import function_body

    home = (_ROOT / "src" / "static" / "app-home.js").read_text(encoding="utf-8")
    ask = function_body(home, "ooAskToSendPlace")
    assert '"Send the place {lat}, {lon} (rounded to 0.1 degree) and the dates to {host}"' in ask
    assert "ooRoundPlace(" in ask and "host: OO_WEATHER_HOST" in ask
    assert 'const OO_WEATHER_HOST = "archive-api.open-meteo.com";' in home
    assert "window.confirm(" in ask and "await ensureOnline(ask" in ask
    card = function_body(home, "cardWeatherFetch")
    assert card.index("!await ooAskToSendPlace(") < card.index('"/api/weather/context"')
    assert "consent: true" in card
    claim = function_body((_ROOT / "src" / "static" / "app-claim.js").read_text(encoding="utf-8"), "claimWeather")
    assert claim.index("!await ooAskToSendPlace(") < claim.index('"/api/weather/context"')
    assert "consent: !op.cached" in claim
