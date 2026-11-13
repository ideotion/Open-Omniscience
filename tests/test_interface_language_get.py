"""``GET /api/ai/interface-language``: the terminal panel reads the language the person chose (R665).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A read of one stored code and nothing else: the POST stores it (S05-08), the GET answers it, and a GET never stores, normalises
into the store or guesses. Its read-only nature is also measured app-wide by tests/test_get_routes_side_effects.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.ai_layer import translation_sweep as TSW
from src.api.main import app
from src.database.session import init_db


def test_the_get_answers_what_the_post_stored_and_only_the_code(monkeypatch):
    init_db()
    store: dict = {}
    monkeypatch.setattr("src.config.kv_store.kv_set_json", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda k: store.get(k))
    c = TestClient(app)
    assert c.get("/api/ai/interface-language").json() == {"lang": None}, "nothing reported: null, never a guess"
    assert c.post("/api/ai/interface-language", json={"lang": "fr-FR"}).json() == {"lang": "fr"}
    before = dict(store)
    r = c.get("/api/ai/interface-language")
    assert r.status_code == 200 and r.json() == {"lang": "fr"}, "only the code, not the reported_at time"
    assert store == before, "the GET wrote nothing"


def test_an_unreadable_store_answers_null(monkeypatch):
    init_db()

    def boom(_k):
        raise RuntimeError("locked")

    monkeypatch.setattr("src.config.kv_store.kv_get_json", boom)
    assert TSW.interface_lang() is None
    assert TestClient(app).get("/api/ai/interface-language").json() == {"lang": None}
