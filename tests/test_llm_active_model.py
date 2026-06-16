"""
The stored active-LLM-model setting (maintainer Q10, 2026-06-16): a persisted UI
preference that replaces env-only OO_LLM_MODEL as the operator's default model.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient


def test_llm_model_setting_roundtrip_and_validation(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    p = tmp_path / "app_settings.json"
    monkeypatch.setattr(aps, "_settings_path", lambda: p)

    assert aps.load_settings().llm_model is None  # default: no override
    aps.save_settings({"llm_model": "llama3.2:3b"})
    assert aps.load_settings().llm_model == "llama3.2:3b"
    aps.save_settings({"llm_model": ""})  # "" clears the override
    assert aps.load_settings().llm_model is None
    with pytest.raises(aps.AppSettingsError):  # injection-shaped name rejected
        aps.save_settings({"llm_model": "../etc/passwd"})
    # A corrupt/invalid STORED value is ignored on load (never trusted blindly).
    p.write_text('{"llm_model": "../evil"}', "utf-8")
    assert aps.load_settings().llm_model is None


def test_active_model_prefers_stored_setting(tmp_path, monkeypatch):
    import src.config.app_settings as aps
    from src.api.llm import active_model
    from src.llm.ollama import DEFAULT_MODEL

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    assert active_model() == DEFAULT_MODEL  # no override -> the built-in default
    aps.save_settings({"llm_model": "gemma2:2b"})
    assert active_model() == "gemma2:2b"  # the stored choice wins


def test_models_endpoint_and_put_report_active(tmp_path, monkeypatch):
    import src.config.app_settings as aps
    from src.api.llm import get_llm_client
    from src.api.main import app
    from src.llm.ollama import OllamaClient

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")

    def _down(_req):
        raise httpx.ConnectError("ollama down")

    def _mk():
        http = httpx.Client(transport=httpx.MockTransport(_down), base_url="http://t")
        return OllamaClient(client=http, base_url="http://t")

    app.dependency_overrides[get_llm_client] = _mk
    try:
        with TestClient(app) as c:
            # PUT the setting through the normal settings API.
            assert c.put("/api/settings", json={"llm_model": "qwen2.5:3b"}).status_code == 200
            assert c.get("/api/settings").json()["llm_model"] == "qwen2.5:3b"
            # /api/llm/models reports it as `active` even when Ollama is down
            # (the active model is a stored choice, not read from Ollama).
            d = c.get("/api/llm/models").json()
            assert d["active"] == "qwen2.5:3b"
            # An invalid model name is rejected at the API boundary.
            assert c.put("/api/settings", json={"llm_model": "bad name!"}).status_code == 400
    finally:
        app.dependency_overrides.clear()
