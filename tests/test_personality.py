"""Personality library: attributed quotes + sourced fun facts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honesty bar: every quote carries an author and an attribution status (disputed lines
are flagged, not laundered); every fun fact carries a source.
"""

from fastapi.testclient import TestClient

from src.personality.catalog import load_catalog, random_item


def test_catalog_is_wellformed_and_honest():
    cat = load_catalog()
    assert len(cat["quotes"]) >= 6 and len(cat["fun_facts"]) >= 4
    for qt in cat["quotes"]:
        assert qt["text"] and qt["author"]                 # always attributed
        assert qt["attribution"] in ("confirmed", "disputed", "traditional")
    # At least one disputed attribution is honestly flagged (we don't pretend certainty).
    assert any(q["attribution"] == "disputed" for q in cat["quotes"])
    for f in cat["fun_facts"]:
        assert f["text"] and f["source"]                   # facts must be citable


def test_random_item_kinds():
    assert random_item("quote")["kind"] == "quote"
    assert random_item("fact")["kind"] == "fact"


def test_api_random_and_all():
    from src.api.main import app

    with TestClient(app) as c:
        q = c.get("/api/personality/random").json()
        assert q["kind"] == "quote" and q["item"]["text"]
        f = c.get("/api/personality/random?kind=fact").json()
        assert f["kind"] == "fact" and f["item"]["source"]
        assert c.get("/api/personality/random?kind=bogus").status_code == 422
        allc = c.get("/api/personality/all").json()
        assert allc["counts"]["quotes"] >= 6
