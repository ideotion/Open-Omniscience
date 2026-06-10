"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Regression tests for RM-03 (0.0.8 WP1, audit finding ETH-02): the one
external-service call in the app -- POST /api/sources/discover/topic sending the
topic query to DuckDuckGo -- must be OFF by default, refuse with an honest 403
when disabled, and work only after a knowing opt-in via the safety settings.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app
from src.safety.settings import SafetySettings, load_settings

client = TestClient(app)


def test_external_discovery_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))  # fresh settings file location
    monkeypatch.delenv("OO_DISCOVERY_EXTERNAL", raising=False)
    assert SafetySettings().discovery_external_enabled is False
    assert load_settings().discovery_external_enabled is False


def test_topic_discovery_refuses_with_honest_403_when_disabled(monkeypatch):
    monkeypatch.delenv("OO_DISCOVERY_EXTERNAL", raising=False)
    monkeypatch.setattr(
        "src.safety.settings.load_settings",
        lambda: SafetySettings(discovery_external_enabled=False),
    )
    resp = client.post("/api/sources/discover/topic?topic=press+freedom")
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    # The refusal must say what would happen and where to enable it -- honest UX.
    assert "DuckDuckGo" in detail
    assert "Settings" in detail


def test_topic_discovery_runs_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "src.safety.settings.load_settings",
        lambda: SafetySettings(discovery_external_enabled=True),
    )
    # The external search itself is stubbed -- no network in tests.
    monkeypatch.setattr(
        "src.database.source_manager.SourceManager.discover_sources_by_topic",
        lambda self, topic, max_sources, region="wt-wt": [
            {"name": "Example Outlet", "domain": "example.com", "url": "https://example.com"}
        ],
    )
    resp = client.post("/api/sources/discover/topic?topic=press+freedom")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["sources"][0]["domain"] == "example.com"


def test_settings_api_roundtrips_the_toggle(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.delenv("OO_DISCOVERY_EXTERNAL", raising=False)

    r = client.get("/api/safety/settings")
    assert r.status_code == 200
    assert r.json()["discovery_external_enabled"] is False  # default off

    r = client.put("/api/safety/settings", json={"discovery_external_enabled": True})
    assert r.status_code == 200
    assert r.json()["discovery_external_enabled"] is True

    r = client.get("/api/safety/settings")
    assert r.json()["discovery_external_enabled"] is True

    # ...and back off (the off state must persist too).
    r = client.put("/api/safety/settings", json={"discovery_external_enabled": False})
    assert r.json()["discovery_external_enabled"] is False


def test_env_override_enables_headless_use(monkeypatch, tmp_path):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.setenv("OO_DISCOVERY_EXTERNAL", "1")
    assert load_settings().discovery_external_enabled is True
    monkeypatch.setenv("OO_DISCOVERY_EXTERNAL", "0")
    assert load_settings().discovery_external_enabled is False


def test_rss_discovery_for_own_sources_is_not_gated(monkeypatch):
    """RSS discovery fetches operator-added sources via the EthicalFetcher --
    no third party involved -- so the external gate must NOT block it."""
    monkeypatch.setattr(
        "src.safety.settings.load_settings",
        lambda: SafetySettings(discovery_external_enabled=False),
    )
    monkeypatch.setattr(
        "src.database.source_manager.SourceManager.discover_rss_feeds",
        lambda self, source_ids=None, timeout=10: [],
    )
    resp = client.post("/api/sources/discover/rss")
    assert resp.status_code == 200  # not 403: local-path discovery stays available
