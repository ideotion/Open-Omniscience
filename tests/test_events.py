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


def test_dedup_collapses_cross_calendar_duplicates():
    from src.events.dedup import dedup, fingerprint

    # World Press Freedom Day is intentionally in both `civic` and `un_days`.
    same = [e for e in agenda() if "Press Freedom Day" in e["title"]]
    assert len({e["calendar"] for e in same}) >= 2          # really duplicated across calendars
    assert len({fingerprint(e) for e in same}) == 1         # …but one identity

    merged = dedup(agenda(), {c["key"]: c["name"] for c in load_calendars()})
    wpfd = [m for m in merged if "Press Freedom Day" in m["title"]]
    assert len(wpfd) == 1                                   # collapsed to a single row
    m = wpfd[0]
    assert set(m["sources"]) >= {"civic", "un_days"} and m["also_in"]   # provenance kept
    assert "date_variants" not in m                        # both agree on May 3 → no false alarm


def test_dedup_surfaces_date_disagreement():
    from src.events.dedup import dedup

    rows = [
        {"title": "Foo Day", "calendar": "a", "country": "FR", "next_occurrence": "2026-07-14", "month": 7, "day": 14},
        {"title": "Foo Day (alt source)", "calendar": "b", "country": "FR", "next_occurrence": "2026-07-15", "month": 7, "day": 15},
    ]
    out = dedup(rows, {"a": "A", "b": "B"})
    assert len(out) == 1 and out[0]["date_variants"] == ["2026-07-14", "2026-07-15"]


def test_api_dedup_default_on_and_off():
    from src.api.main import app

    with TestClient(app) as c:
        on = c.get("/api/events").json()["events"]
        off = c.get("/api/events?dedup=false").json()["events"]
        wp_on = [e for e in on if "Press Freedom Day" in e["title"]]
        wp_off = [e for e in off if "Press Freedom Day" in e["title"]]
        assert len(wp_on) == 1 and len(wp_off) >= 2        # collapsed vs raw
        assert "also_in" in wp_on[0]
