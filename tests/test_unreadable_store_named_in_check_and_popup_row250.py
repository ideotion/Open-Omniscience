"""Row 250 (follows R766/R769): the update CHECK and the consent popup name settings that could not be read.

R766 made the update and the AI install say "the settings could not be read" instead of "Protected mode is on". Two
places still misnamed the same state:
- the update check answered "Protected mode has no usable proxy" when the fetch path refused because the settings could
  not be read: it now answers ``settings_unreadable`` with R766's sentence and its way out;
- the consent popup, when the stored choice could not be read but the environment names a proxy, described that proxy
  transport as if protected mode had been chosen. ``transport_summary`` now marks it ``stored: "unreadable"`` and the
  popup's lines say so (driven as real code in ``net_lane_unreadable_store_node_test.js``).
What is refused does not change.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.maintenance import self_update as su

ROOT = Path(__file__).resolve().parents[1]
CHECK_UI = (
    "The settings could not be read, so the update check did not run: network actions are refused as if protected mode "
    "were on. Unlock the app if it is locked. If the saved choice is damaged, choose the network fetch mode and proxy "
    "again in Settings and save. Then try again."
)

POPUP = (
    "The settings could not be read, so protected mode is assumed: fetches ride the proxy named in this computer's "
    "environment, and a lane never falls back to the clear internet on its own.",
    "The settings could not be read, so fetches are refused as if protected mode were on: the proxy named in this "
    "computer's environment cannot be used.",
    "Transport: none — the settings could not be read, so these fetches are refused, never sent direct.",
    "Transport: the install or update itself is refused while the settings cannot be read; any check that runs goes "
    "through the proxy named in this computer's environment.",
    "Transport: direct, even though the unreadable settings are treated as protected mode — this lane does not use a "
    "proxy, so these hosts see your address.",
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv(k.lower(), raising=False)


def _read_fails(monkeypatch):
    import src.safety.settings as settings
    from src.config.kv_store import KvReadError

    def boom():
        raise KvReadError("locked")

    monkeypatch.setattr(settings, "_read_raw", boom)


def _check(monkeypatch):
    from fastapi.testclient import TestClient

    import src.safety.fetcher as fetcher
    from src.api.main import app

    def no_transport(url):
        raise fetcher.TransportUnavailable("no usable proxy")

    monkeypatch.setattr(su, "_get_json", no_transport)
    return TestClient(app, base_url="http://127.0.0.1").post("/api/system/update/check")


def test_a_check_refused_because_the_settings_could_not_be_read_says_so(monkeypatch):
    _read_fails(monkeypatch)
    r = _check(monkeypatch)
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "settings_unreadable", "message": su.SETTINGS_UNREADABLE_CHECK_REFUSAL}
    assert "Protected mode" not in r.json()["detail"]["message"]
    assert su.SETTINGS_UNREADABLE_CHECK_REFUSAL == CHECK_UI


def test_a_check_refused_in_chosen_protected_mode_keeps_its_own_words(monkeypatch):
    import src.safety.settings as settings

    st = settings.SafetySettings(fetch_mode="protected")
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    r = _check(monkeypatch)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "protected_no_proxy"


def test_the_server_marks_a_transport_read_from_the_environment_alone(monkeypatch):
    from src.safety import settings
    from src.safety.fetcher import transport_summary

    _read_fails(monkeypatch)
    assert transport_summary(settings.load_settings()) == {"kind": "unknown", "reason": "unreadable"}
    monkeypatch.setenv("OO_HTTP_PROXY", "socks5h://127.0.0.1:9050")
    st = settings.load_settings()
    assert st.mode_unknown and not st.read_failed
    assert transport_summary(st) == {"kind": "proxy", "stored": "unreadable"}
    # a readable choice of protected mode carries no mark
    chosen = settings.SafetySettings(fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9050")
    assert transport_summary(chosen) == {"kind": "proxy"}


def test_the_safety_endpoint_serves_the_mark(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _read_fails(monkeypatch)
    monkeypatch.setenv("OO_HTTP_PROXY", "socks5h://127.0.0.1:9050")
    served = TestClient(app, base_url="http://127.0.0.1").get("/api/safety/settings").json()
    assert served["transport"] == {"kind": "proxy", "stored": "unreadable"}
    assert "mode_unknown" not in served


def test_the_popup_lines_run_as_real_code():
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "net_lane_unreadable_store_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_ui_says_it_in_twelve_languages():
    from tests.js_source_helper import function_body, read_static

    body = function_body(read_static("app-settings.js"), "updCheck")
    assert 'code === "settings_unreadable"' in body and f't("{CHECK_UI}")' in body
    core = read_static("app-core.js")
    keys = [CHECK_UI, *POPUP]
    for key in POPUP:
        assert f't("{key}")' in core, key[:60]
    locales = sorted((ROOT / "src/static/locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert table.get(key), f"{path.name} lacks: {key[:60]}"
