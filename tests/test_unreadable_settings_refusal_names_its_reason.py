"""R766 (row 233): settings that cannot be read are still refused as protected mode, but the refusal says what is true.

Before: the update and the AI install answered "Protected mode is on" whenever the safety settings could not be read
(locked, keyed to another passphrase, damaged). Nobody had chosen protected mode; the choice was unknown. Now:
- what is refused is unchanged (R117: unreadable counts as protected; ``protected_mode_chosen`` / ``ai_install_protected``
  are still True in every unreadable case);
- the reason has its own code, ``settings_unreadable``, and its own sentence with the way out, in twelve languages;
- "Protected mode is on" is said only when protected mode was actually read from the settings.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.llm import install_transport as it
from src.maintenance import self_update as su
from tests.test_self_update import SHA_B, _checked_for_apply

ROOT = Path(__file__).resolve().parents[1]
UPDATE_UI = (
    "The settings could not be read, so the update did not start: network actions are refused as if protected mode were "
    "on. Unlock the app if it is locked. If the saved choice is damaged, choose the network fetch mode and proxy again in "
    "Settings and save. Then try again."
)
AI_UI = (
    "The settings could not be read, so the AI install did not start: network actions are refused as if protected mode "
    "were on. Unlock the app if it is locked. If the saved choice is damaged, choose the network fetch mode and proxy again "
    "in Settings and save. Then try again."
)


def _settings(monkeypatch, **kw):
    import src.safety.settings as settings

    st = settings.SafetySettings(**kw)
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    return st


def _raises(monkeypatch):
    import src.safety.settings as settings

    monkeypatch.setattr(settings, "load_settings", lambda: (_ for _ in ()).throw(RuntimeError("locked")))


def _read_fails(monkeypatch):
    """The REAL load_settings, with the store unreadable underneath it."""
    import src.safety.settings as settings
    from src.config.kv_store import KvReadError

    def boom():
        raise KvReadError("locked")

    monkeypatch.setattr(settings, "_read_raw", boom)


def _client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv(k.lower(), raising=False)


# -- the reason, case by case ------------------------------------------------------------------------------------------ #


def test_each_case_has_its_own_reason_and_what_is_refused_does_not_change(monkeypatch):
    _settings(monkeypatch)
    assert su.protected_reason() is None and su.protected_mode_chosen() is False
    _settings(monkeypatch, fetch_mode="protected")
    assert su.protected_reason() == "protected" and su.protected_mode_chosen() is True
    st = _settings(monkeypatch)
    st.read_failed = True
    assert su.protected_reason() == "settings_unreadable" and su.protected_mode_chosen() is True
    _raises(monkeypatch)
    assert su.protected_reason() == "settings_unreadable" and su.protected_mode_chosen() is True
    assert it.ai_install_protected() is True


def test_an_unreadable_store_reads_as_unknown_even_when_the_environment_names_a_proxy(monkeypatch):
    """``read_failed`` alone is False when the environment supplies a proxy; the store is just as unreadable."""
    from src.safety import settings

    _read_fails(monkeypatch)
    st = settings.load_settings()
    assert st.is_protected and st.mode_unknown and st.read_failed
    assert su.protected_reason() == "settings_unreadable"
    monkeypatch.setenv("OO_HTTP_PROXY", "socks5h://127.0.0.1:9050")
    st = settings.load_settings()
    assert st.is_protected and st.mode_unknown and not st.read_failed
    assert su.protected_reason() == "settings_unreadable", "unknown, whatever proxy the environment names"
    assert su.protected_mode_chosen() is True


def test_a_mode_the_environment_names_is_not_unknown(monkeypatch):
    from src.safety import settings

    _read_fails(monkeypatch)
    monkeypatch.setenv("OO_FETCH_MODE", "protected")
    st = settings.load_settings()
    assert not st.mode_unknown
    assert su.protected_reason() == "protected"


def test_mode_unknown_is_never_saved_or_served(monkeypatch):
    """Checked on settings that really carry it: the dict a save writes and the safety endpoint serves leave it out."""
    from src.safety import settings

    _read_fails(monkeypatch)
    st = settings.load_settings()
    assert st.mode_unknown is True
    assert "mode_unknown" not in st.to_dict()
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    import src.api.safety as safety_api

    monkeypatch.setattr(safety_api, "load_settings", lambda: st, raising=False)
    served = _client().get("/api/safety/settings").json()
    assert "mode_unknown" not in served


# -- the update ------------------------------------------------------------------------------------------------------ #


def test_the_update_refusal_names_unreadable_settings_and_starts_nothing(monkeypatch):
    started: list = []
    _checked_for_apply(monkeypatch, started)
    _raises(monkeypatch)
    with pytest.raises(su.SettingsUnreadableRefused) as exc:
        su.begin_apply("v0.6.0", SHA_B)
    assert isinstance(exc.value, su.ProtectedRefused), "still a protected-mode refusal for every caller"
    assert str(exc.value) == su.SETTINGS_UNREADABLE_REFUSAL
    assert "Protected mode is on" not in str(exc.value)
    assert started == []
    _settings(monkeypatch, fetch_mode="protected")
    with pytest.raises(su.ProtectedRefused) as exc2:
        su.begin_apply("v0.6.0", SHA_B)
    assert not isinstance(exc2.value, su.SettingsUnreadableRefused)
    assert str(exc2.value) == su.PROTECTED_REFUSAL
    assert started == []


def test_the_update_endpoints_carry_the_distinct_code(monkeypatch):
    import src.safety.shutdown as shutdown
    from src.ingest import clear_kill_switch

    started: list = []
    stopped: list = []
    _checked_for_apply(monkeypatch, started)
    monkeypatch.setattr(shutdown, "request_shutdown", lambda **k: stopped.append(k) or {})
    clear_kill_switch()
    _raises(monkeypatch)
    assert _client().get("/api/system/update/status").json()["blocked"] == "settings_unreadable"
    r = _client().post("/api/system/update/apply", json={"confirm": True, "ref": "v0.6.0", "sha": SHA_B})
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "settings_unreadable", "message": su.SETTINGS_UNREADABLE_REFUSAL}
    _settings(monkeypatch, fetch_mode="protected")
    assert _client().get("/api/system/update/status").json()["blocked"] == "protected"
    r = _client().post("/api/system/update/apply", json={"confirm": True, "ref": "v0.6.0", "sha": SHA_B})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "protected"
    assert started == [] and stopped == []


# -- the AI install -------------------------------------------------------------------------------------------------- #


def test_the_ai_install_steps_name_unreadable_settings(monkeypatch):
    class Boom(Exception):
        pass

    _raises(monkeypatch)
    with pytest.raises(Boom) as exc:
        it.refuse_if_protected(Boom)
    assert str(exc.value) == it.AI_INSTALL_SETTINGS_UNREADABLE_REFUSAL
    assert "Protected mode is on" not in str(exc.value)
    _settings(monkeypatch, fetch_mode="protected")
    with pytest.raises(Boom) as exc:
        it.refuse_if_protected(Boom)
    assert str(exc.value) == it.AI_INSTALL_PROTECTED_REFUSAL
    _settings(monkeypatch)
    it.refuse_if_protected(Boom)  # standard mode: nothing refused


def test_the_ai_install_route_and_the_dialog_status_carry_the_reason(monkeypatch):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _raises(monkeypatch)
    assert _client().get("/api/system/egress-window").json()["ai_install_blocked"] == "settings_unreadable"
    r = _client().post("/api/llm/pull", json={"model": "qwen2.5:3b"})
    assert r.status_code == 409 and r.json()["detail"] == it.AI_INSTALL_SETTINGS_UNREADABLE_REFUSAL
    _settings(monkeypatch, fetch_mode="protected")
    assert _client().get("/api/system/egress-window").json()["ai_install_blocked"] == "protected"


# -- what the user reads ----------------------------------------------------------------------------------------------- #


def test_the_ui_says_each_reason_in_twelve_languages():
    settings_js = (ROOT / "src/static/app-settings.js").read_text(encoding="utf-8")
    assert 'st.blocked === "settings_unreadable"' in settings_js
    assert 'code === "settings_unreadable"' in settings_js
    assert f't("{UPDATE_UI}")' in settings_js
    core = (ROOT / "src/static/app-core.js").read_text(encoding="utf-8")
    assert 'st.ai_install_blocked === "settings_unreadable"' in core
    assert f't("{AI_UI}")' in core
    assert su.SETTINGS_UNREADABLE_REFUSAL == UPDATE_UI and it.AI_INSTALL_SETTINGS_UNREADABLE_REFUSAL == AI_UI
    locales = sorted((ROOT / "src/static/locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in (UPDATE_UI, AI_UI):
            assert table.get(key), f"{path.name} lacks: {key[:50]}"
