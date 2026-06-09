"""World-events agenda (P0): curated, offline, honest dates.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from datetime import date

from fastapi.testclient import TestClient

from src.events.catalog import agenda, load_events


def test_catalog_wellformed_and_honest():
    evs = load_events()
    assert len(evs) >= 12
    assert all(e["title"] and e["official_url"].startswith("http") for e in evs)
    # Fixed civic days are confirmed AND carry a real month/day; movable summits don't
    # claim a confirmed exact date.
    wpfd = next(e for e in evs if e["title"].startswith("World Press Freedom Day"))
    assert wpfd["confirmed"] and wpfd["month"] == 5 and wpfd["day"] == 3
    davos = next(e for e in evs if "Davos" in e["title"])
    assert davos["confirmed"] is False and davos["day"] is None   # exact date not fabricated


def test_agenda_next_occurrence_only_for_fixed_dates():
    # World Press Freedom Day (May 3) → a real next date; Davos (movable) → None.
    items = {e["title"].split(" (")[0]: e for e in agenda(today=date(2026, 6, 1))}
    wpfd = items["World Press Freedom Day"]
    assert wpfd["next_occurrence"] == "2027-05-03"      # already past in 2026 → next year
    assert any(e["next_occurrence"] is None for e in agenda())   # movable events stay undated


def test_api_list_and_filter():
    from src.api.main import app

    with TestClient(app) as c:
        body = c.get("/api/events").json()
        assert body["count"] >= 12 and body["confirmed"] >= 4
        assert "fabricated" in body["caveat"].lower()
        civic = c.get("/api/events?category=civic").json()
        assert civic["count"] >= 4 and all(e["category"] == "civic" for e in civic["events"])
