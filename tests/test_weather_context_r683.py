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
    from tests.js_source_helper import function_body

    body = function_body((_ROOT / "src" / "static" / "app-home.js").read_text(encoding="utf-8"), "ooRoundPlace")
    script = "function ooRoundPlace(v) " + body + "\nconsole.log(JSON.stringify(" + repr(values) + ".map(ooRoundPlace)));\n"
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
        (old / f"{i:024x}.json").write_text('{"ok": true, "provenance": {"requested_url": "latitude=48.8566"}}', encoding="utf-8")
    (data_dir / "keep.txt").write_text("unrelated", encoding="utf-8")
    assert purge_plaintext_cache() == 3
    assert not old.exists(), "no plaintext coordinate file remains"
    assert (data_dir / "keep.txt").exists(), "only the weather folder is touched"
    assert purge_plaintext_cache() == 0


def test_startup_runs_the_purge_before_the_lock_check():
    import inspect

    from src.api import main

    src = inspect.getsource(main.lifespan)
    assert "purge_plaintext_cache()" in src, "the purge runs on the first start after the update"
    assert src.index("purge_plaintext_cache()") < src.index("state = app_lock_state()"), \
        "before the lock check: it needs no key, and a store never unlocked again keeps no location"


def test_a_panic_wipe_leaves_nothing_of_the_weather_slices(data_dir):
    from src.ingest import clear_kill_switch
    from src.safety import panic_wipe
    from src.weather import openmeteo

    (data_dir / openmeteo.LEGACY_CACHE_DIR).mkdir()
    (data_dir / openmeteo.LEGACY_CACHE_DIR / "a.json").write_text("{}", encoding="utf-8")
    (data_dir / "oo.db").write_bytes(b"x" * 64)  # where app_state, and so every held slice, lives
    try:
        panic_wipe(data_dir, confirm=True)
    finally:
        clear_kill_switch()
    # (Clearing the switch afterwards may write its own state file back into the folder; that is not ours.)
    assert not (data_dir / "oo.db").exists(), "the store holding every slice is gone"
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
    assert "await ensureOnline(ask, {shadow: shadow, confirmIfOnline:" in ask
    assert "ensureOnline(ask, opts" not in ask, "only shadow and the confirmation reach the popup, never the caller's options"
    assert 'if (typeof ensureOnline !== "function") return false;' in ask
    card = function_body(home, "cardWeatherFetch")
    assert card.index('"/api/weather/context/held?"') < card.index("!await ooAskToSendPlace(") < card.index('"/api/weather/context"')
    assert "consent: true" in card and "Dates sent: {start} to {end}." in card
    claim = function_body((_ROOT / "src" / "static" / "app-claim.js").read_text(encoding="utf-8"), "claimWeather")
    assert claim.index('"/api/weather/context/held?"') < claim.index("!await ooAskToSendPlace(") < claim.index('"/api/weather/context"')
    assert "consent: true" in claim and "consent: false" not in claim
    assert "d.kept !== false" in claim, "held from then on only when the server kept it"


def test_ensure_online_asks_the_confirmation_on_the_read_that_found_it_online():
    """First security read: two separate network reads let a state change skip both questions."""
    from tests.js_source_helper import function_body

    body = function_body((_ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8"), "ensureOnline")
    assert "if (nm.online) return opts.confirmIfOnline ? window.confirm(opts.confirmIfOnline) : true;" in body


def test_a_panic_wipe_clears_the_place_this_browser_kept():
    from tests.js_source_helper import function_body

    body = function_body((_ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8"), "panicWipe")
    assert body.index('"/api/safety/panic"') < body.index('localStorage.removeItem("oo.climate.place")')
    climate = (_ROOT / "src" / "static" / "app-climate.js").read_text(encoding="utf-8")
    assert 'const _PLACE_KEY = "oo.climate.place";' in climate


def test_the_place_is_kept_in_the_browser_only_after_the_question_or_a_held_read():
    from tests.js_source_helper import function_body

    body = function_body((_ROOT / "src" / "static" / "app-climate.js").read_text(encoding="utf-8"), "climatePlaceShow")
    first_save = body.index("_climatePlaceSave(q)")
    assert first_save > body.index('"/api/weather/anomaly/held?"')
    assert body.rindex("_climatePlaceSave(q)") > body.index("!await ooAskToSendPlace(")
    assert body.rindex("_climatePlaceSave(q)") < body.index('"/api/weather/anomaly", {method: "POST"')


def test_the_held_read_route_never_fetches_and_needs_no_consent(client, monkeypatch):
    import src.safety.fetcher as sf
    from src.ingest import activate_kill_switch, clear_kill_switch

    q = {"lat": 48.85661, "lon": 2.35222, "start_date": "2023-05-01", "end_date": "2023-05-01",
         "variables": "precipitation_sum", "label": "Paris"}
    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: pytest.fail("a held read builds no fetcher"))
    assert client.get("/api/weather/context/held", params=q).json() == {"ok": True, "held": False}
    f = _Fetcher()
    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: f)
    client.post("/api/weather/context", json={**_REQ, "consent": True})
    monkeypatch.setattr(sf, "make_fetcher", lambda **kw: pytest.fail("a held read builds no fetcher"))
    activate_kill_switch()
    try:
        got = client.get("/api/weather/context/held", params=q).json()
    finally:
        clear_kill_switch()
    assert got["held"] is True and got["cached"] is True and got["label"] == "Paris"
    assert client.get("/api/weather/context/held", params={**q, "variables": "evil"}).status_code == 422


def test_a_place_looked_up_for_oneself_is_never_found_by_a_corroboration_read(monkeypatch):
    """First security read: the Your place slices live under their own prefix, so a claim offer that rounds to the
    same point and window never shows them as held or carries them in a bundle."""
    from src.weather import anomaly, held, openmeteo

    box: dict = {}
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda k: box.get(k))
    monkeypatch.setattr("src.config.kv_store.kv_set_json", lambda k, v: box.__setitem__(k, v))
    w = (date(2023, 5, 1), date(2023, 5, 1))
    monkeypatch.setattr(anomaly, "fetch_daily_slice", lambda lat, lon, s, e, vs, **kw: {
        "ok": True, "daily": {"time": [s.isoformat()], **{v: [1.0] for v in vs}},
        "units": {v: anomaly.SUPPORTED[v][1] for v in vs},
        "provenance": {"requested_url": openmeteo.build_archive_url(lat, lon, s, e, vs)}})
    anomaly.fetch_anomalies(48.85661, 2.35222, *w)
    assert box and all(k.startswith(held.PLACE_KEY_PREFIX) for k in box)
    url = openmeteo.build_archive_url(48.85661, 2.35222, *w, sorted(anomaly.SUPPORTED))
    assert openmeteo.read_cached_slice(url) is None
    assert anomaly.held_anomalies(48.85661, 2.35222, *w)["held"] is True


def test_a_symlinked_legacy_folder_is_unlinked_and_its_target_left_alone(data_dir, tmp_path_factory):
    from src.weather.openmeteo import LEGACY_CACHE_DIR, purge_plaintext_cache

    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (elsewhere / "x.json").write_text("{}", encoding="utf-8")
    (data_dir / LEGACY_CACHE_DIR).symlink_to(elsewhere, target_is_directory=True)
    assert purge_plaintext_cache() == 0
    assert not (data_dir / LEGACY_CACHE_DIR).exists() and (elsewhere / "x.json").exists()


def test_the_claim_workspace_reads_held_state_for_the_shown_offers_only():
    import inspect

    from src.analytics import claim_workspace

    src = inspect.getsource(claim_workspace)
    assert "for offer in shown:" in src and '"cached": read_cached_slice' not in src
