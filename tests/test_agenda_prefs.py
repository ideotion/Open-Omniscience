"""
Server-side agenda subscription preferences (DB-reliability D4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import agenda_prefs as ap
from src.config import kv_store


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    kv_store.kv_invalidate()
    yield
    kv_store.kv_invalidate()


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
def test_defaults_are_unconfigured():
    p = ap.load_prefs()
    assert p.configured is False
    assert p.subs == [] and p.excluded == [] and p.view == "month"


def test_save_round_trips_and_marks_configured(tmp_path):
    ap.save_prefs({"subs": ["holidays", "eclipses"], "excluded": ["fifa"], "view": "year"})
    assert not (tmp_path / "app_settings.json").exists()  # it's in the DB, not a JSON file
    p = ap.load_prefs()
    assert p.configured is True
    assert p.subs == ["holidays", "eclipses"]
    assert p.excluded == ["fifa"]
    assert p.view == "year"


def test_partial_update_leaves_other_fields():
    ap.save_prefs({"subs": ["a", "b"], "view": "week"})
    ap.save_prefs({"view": "month"})
    p = ap.load_prefs()
    assert p.subs == ["a", "b"]  # untouched
    assert p.view == "month"


def test_dedups_and_drops_blanks():
    ap.save_prefs({"subs": ["a", "a", " ", "b"]})
    assert ap.load_prefs().subs == ["a", "b"]


def test_rejects_non_string_entries():
    with pytest.raises(ap.AgendaPrefsError):
        ap.save_prefs({"subs": [1, 2, 3]})


def test_rejects_too_many_entries():
    with pytest.raises(ap.AgendaPrefsError):
        ap.save_prefs({"subs": [f"k{i}" for i in range(ap._MAX_ITEMS + 1)]})


# --------------------------------------------------------------------------- #
# REST path
# --------------------------------------------------------------------------- #
def test_rest_get_then_put_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        got = c.get("/api/agenda/prefs")
        assert got.status_code == 200
        assert got.json()["configured"] is False

        put = c.put("/api/agenda/prefs", json={"subs": ["holidays"], "view": "week"})
        assert put.status_code == 200
        body = put.json()
        assert body["configured"] is True
        assert body["subs"] == ["holidays"]
        assert body["view"] == "week"

        again = c.get("/api/agenda/prefs")
        assert again.json()["subs"] == ["holidays"]


def test_rest_rejects_bad_view(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        r = c.put("/api/agenda/prefs", json={"view": "x" * 100})
        assert r.status_code == 400
