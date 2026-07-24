"""
Tests for the application settings API and the backup download endpoint.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Settings writes are redirected to a temp data dir (OO_DATA_DIR) so the test does
not touch the developer's real preferences. The backup download is non-destructive
and is checked end-to-end through the API.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from src.api.main import app
from src.database.session import init_db


def test_get_and_update_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        r = client.get("/api/settings")
        assert r.status_code == 200
        body = r.json()
        assert body["theme"] in body["valid_themes"]

        r = client.put("/api/settings", json={"theme": "light", "default_result_limit": 25})
        assert r.status_code == 200
        assert r.json()["theme"] == "light"
        assert r.json()["default_result_limit"] == 25

        # Invalid theme is rejected with an explicit 400, not silently coerced.
        bad = client.put("/api/settings", json={"theme": "neon"})
        assert bad.status_code == 400

        # Out-of-range limit is rejected too.
        bad2 = client.put("/api/settings", json={"default_result_limit": 99999})
        assert bad2.status_code == 400


def test_ai_langdetect_auto_setting_defaults_on_and_round_trips(tmp_path, monkeypatch):
    """2026-07-24 Session A §1: default-ON auto-start toggle, opt-out validated as a bool."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        body = client.get("/api/settings").json()
        assert body["ai_langdetect_auto"] is True

        r = client.put("/api/settings", json={"ai_langdetect_auto": False})
        assert r.status_code == 200
        assert r.json()["ai_langdetect_auto"] is False
        # persists across a fresh read
        assert client.get("/api/settings").json()["ai_langdetect_auto"] is False

        bad = client.put("/api/settings", json={"ai_langdetect_auto": "banana"})
        assert bad.status_code == 422  # pydantic rejects a non-bool before it reaches save_settings


def test_backup_download_returns_valid_sqlite(tmp_path):
    init_db()
    with TestClient(app) as client:
        r = client.get("/api/database/backup")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-sqlite3")
    out = tmp_path / "dl.db"
    out.write_bytes(r.content)
    # The downloaded bytes open as a real SQLite DB containing core tables.
    conn = sqlite3.connect(str(out))
    try:
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {"articles", "sources"} <= names


def test_stats_reports_backup_supported():
    init_db()
    with TestClient(app) as client:
        body = client.get("/api/database/stats").json()
    # SQLite default build supports backup/restore.
    assert body["backup_supported"] is True
