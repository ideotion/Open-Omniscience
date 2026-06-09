"""World-events agenda (P0.5): calendars + tags + faceted filtering, honest dates.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from datetime import date

from fastapi.testclient import TestClient

from src.events.catalog import agenda, facets, load_calendars, load_events


def test_catalog_wellformed_honest_and_tagged():
    evs = load_events()
    assert len(evs) >= 40                                   # grew into a real catalog
    assert all(e["title"] and e["official_url"].startswith("http") for e in evs)
    assert all(e["calendar"] and isinstance(e["tags"], list) for e in evs)
    # Fixed civic days confirmed w/ month-day; movable summits not given a fabricated date.
    wpfd = next(e for e in evs if e["title"] == "World Press Freedom Day")
    assert wpfd["confirmed"] and wpfd["month"] == 5 and wpfd["day"] == 3
    assert "press-freedom" in wpfd["tags"]
    davos = next(e for e in evs if "Davos" in e["title"])
    assert davos["confirmed"] is False and davos["day"] is None


def test_calendars_and_facets():
    cals = {c["key"] for c in load_calendars()}
    assert {"un_days", "national_days", "summits"} <= cals
    f = facets()
    un = next(c for c in f["calendars"] if c["key"] == "un_days")
    assert un["count"] >= 10                                # several UN days
    assert "press-freedom" in f["tags"] and "FR" in f["countries"]


def test_agenda_facet_filters():
    # by calendar
    assert all(e["calendar"] == "un_days" for e in agenda(calendar="un_days"))
    # by country (Bastille Day is France)
    fr = agenda(country="FR")
    assert fr and all(e["country"] == "FR" for e in fr)
    assert any("Bastille" in e["title"] for e in fr)
    # by tag
    pf = agenda(tag="press-freedom")
    assert pf and all("press-freedom" in e["tags"] for e in pf)
    # next_occurrence only for fixed dates
    items = {e["title"]: e for e in agenda(today=date(2026, 6, 1))}
    assert items["World Press Freedom Day"]["next_occurrence"] == "2027-05-03"


def test_api_facets_and_filtering():
    from src.api.main import app

    with TestClient(app) as c:
        cals = c.get("/api/events/calendars").json()
        assert any(x["key"] == "un_days" for x in cals["calendars"])
        body = c.get("/api/events").json()
        assert body["count"] >= 40 and "fabricated" in body["caveat"].lower()
        un = c.get("/api/events?calendar=un_days").json()
        assert un["count"] >= 10 and all(e["calendar"] == "un_days" for e in un["events"])
        fr = c.get("/api/events?country=FR").json()
        assert fr["count"] >= 1 and all(e["country"] == "FR" for e in fr["events"])
        tag = c.get("/api/events?tag=climate").json()
        assert tag["count"] >= 1 and all("climate" in e["tags"] for e in tag["events"])
