"""
Tests for the briefing API (feed, dismiss, draft, Markdown export).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Uses the real app with an isolated data dir (OO_DATA_DIR). The corpus is empty here:
the contract under test is the API surface (shape, dismiss/restore, draft round-trip,
Markdown export), not specific card content — empty corpus → an honest empty feed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_briefing_feed_shape(client):
    r = client.get("/api/briefing")
    assert r.status_code == 200
    body = r.json()
    for key in ("generated_at", "count", "buckets", "cards", "dismissed_count"):
        assert key in body


def test_refresh_recomputes(client):
    r = client.post("/api/briefing/refresh")
    assert r.status_code == 200
    assert "cards" in r.json()


def test_briefing_get_is_nonblocking(client):
    # Field test 2026-06-24: the GET recompute ran SYNCHRONOUSLY on the request, so at
    # 60K articles Home hung forever on "Loading the briefing…". The HTTP path now
    # recomputes OFF the request thread: it returns immediately with a `refreshing`
    # flag (and, with no cache yet, an honest `building` placeholder), never blocking.
    r = client.get("/api/briefing")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("refreshing"), bool)
    # The placeholder/feed always carries the same keys (never an error or a blank div).
    for key in ("generated_at", "count", "buckets", "cards", "dismissed_count"):
        assert key in body


def test_dismiss_and_restore_roundtrip(client):
    # Inject a card via the draft path is not how dismiss works; dismiss just records
    # an id, so any id round-trips through dismissed state honestly.
    r = client.post("/api/briefing/dismiss", json={"id": "deadbeef"})
    assert r.status_code == 200
    assert "deadbeef" in r.json()["dismissed"]
    r = client.post("/api/briefing/restore", json={"id": "deadbeef"})
    assert "deadbeef" not in r.json()["dismissed"]


def test_draft_add_export_remove(client):
    card = {
        "id": "abc123",
        "type": "rising",
        "title": "“x” is rising",
        "summary": "Climbing fast.",
        "bucket": "rising",
        "method": "ratio",
        "caveat": "noisy on small n",
        "signal": {"metric": "growth_ratio", "value": 3.0},
        "evidence": [{"title": "A story", "url": "https://x.test/a", "source": "Alpha"}],
        "n": 5,
    }
    r = client.post("/api/briefing/draft/add", json={"card": card, "note": "keep"})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    md = client.get("/api/briefing/draft/export.md")
    assert md.status_code == 200
    assert "“x” is rising" in md.text
    assert "https://x.test/a" in md.text

    r = client.request("DELETE", f"/api/briefing/draft/{card['id']}")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_draft_add_rejects_card_without_id(client):
    r = client.post("/api/briefing/draft/add", json={"card": {"title": "no id"}})
    assert r.status_code == 400


def test_briefing_with_cards_and_target_lang_does_not_500(client, monkeypatch):
    # Regression (2026-09-17 → 2026-09-25): `_annotate_card_terms` read `cards` as a dict
    # of buckets, but `_present` serves it as a LIST, so `.values()` raised on every
    # non-empty briefing. Home always sends `target_lang` (English included), so every
    # install with at least one card saw the error state. The empty-corpus tests above
    # never reached the loop; this one feeds the REAL `_present` shape through the route.
    from src.briefing import service

    cache = {
        "generated_at": "2026-09-25T00:00:00Z",
        "cards": [
            {"id": "kw1", "bucket": "rising", "title_vars": {"term": "Wahl"}},
            {"id": "plain", "bucket": "rising", "title": "no term here"},
        ],
    }
    monkeypatch.setattr(
        service, "get_briefing",
        lambda db, **kw: service._present(cache, include_dismissed=False),
    )
    for lang in ("en", "fr", "ar"):
        r = client.get(f"/api/briefing?target_lang={lang}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert [c["id"] for c in body["cards"]] == ["kw1", "plain"]
        # Both views carry the same annotation; the flat list and the bucket agree.
        bucket_cards = {c["id"]: c for b in body["buckets"] for c in b["cards"]}
        for card in body["cards"]:
            assert card == bucket_cards[card["id"]]
        assert "translation_tier" in bucket_cards["kw1"]
        assert "translation_tier" not in bucket_cards["plain"]
    # The shared cache must not carry one reader's annotation into the next.
    assert "translation_tier" not in cache["cards"][0]
