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
        "id": "abc123", "type": "rising", "title": "“x” is rising",
        "summary": "Climbing fast.", "bucket": "rising",
        "method": "ratio", "caveat": "noisy on small n",
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
