"""Tests for the temporal-map space-time signal layer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap import year_float
from src.timemap.anchors import load_anchors
from src.timemap.collect import articles_to_signals, collect, time_range


def test_year_float_is_monotonic_and_in_range():
    assert int(year_float(date(2001, 9, 11))) == 2001
    assert year_float(date(79, 10, 24)) < year_float(date(1755, 11, 1))
    # within a year: later date -> larger fraction, never reaching the next year
    jan = year_float(date(2020, 1, 1))
    dec = year_float(date(2020, 12, 31))
    assert 2020.0 == jan < dec < 2021.0


def test_anchors_load_with_coord_and_date():
    anchors = load_anchors()
    assert anchors, "curated anchors should be present"
    for a in anchors:
        assert -90 <= a["lat"] <= 90 and -180 <= a["lon"] <= 180
        assert a["date"] and a["t"] is not None
        assert a["source"] == "anchor"
        # an anchor declares its own real coordinate
        assert a["geocode"] == "exact"


def test_anchor_skipped_without_coordinate(monkeypatch):
    import src.timemap.anchors as mod

    mod._raw.cache_clear()
    mod.load_anchors.cache_clear()
    monkeypatch.setattr(mod, "_raw", lambda: {"anchors": [
        {"id": "no-coord", "title": "Somewhere", "date": "2000-01-01"},
        {"id": "ok", "title": "Placed", "date": "2000-01-01", "lat": 10, "lon": 20},
    ]})
    got = mod.load_anchors()
    ids = {a["id"] for a in got}
    assert "ok" in ids and "no-coord" not in ids
    mod.load_anchors.cache_clear()


def test_collect_window_and_kind_filter():
    everything = collect()
    assert len(everything) >= 1
    # sorted ascending by time
    ts = [s["t"] for s in everything]
    assert ts == sorted(ts)

    windowed = collect(start=2000, end=2010)
    assert all(2000 <= s["t"] <= 2010 for s in windowed)
    assert len(windowed) < len(everything)

    kinds = {s["kind"] for s in everything}
    one = next(iter(kinds))
    assert all(s["kind"] == one for s in collect(kinds={one}))


def test_extra_signals_injected_and_validated():
    base = len(collect())
    good = {"id": "x", "title": "Live", "kind": "hazard", "lat": 0.0, "lon": 0.0,
            "t": 2026.5, "date": "2026-07-01"}
    bad_no_coord = {"id": "y", "title": "No coord", "kind": "hazard", "lat": None,
                    "t": 2026.5}
    out = collect(extra=[good, bad_no_coord])
    titles = {s["title"] for s in out}
    assert "Live" in titles and "No coord" not in titles
    assert len(out) == base + 1


def test_articles_to_signals_geocodes_and_dates():
    from datetime import datetime

    rows = [
        # a known gazetteer city -> placed (Paris is in the shipped sample)
        {"title": "A story", "url": "https://x/1", "published": datetime(2024, 5, 1, 9, 0),
         "country": "fr", "city": "Paris"},
        # no date -> skipped
        {"title": "No date", "url": "https://x/2", "published": None, "country": "fr", "city": "Paris"},
        # unknown country, no city -> not geocodable -> skipped (never plotted at 0,0)
        {"title": "Nowhere", "url": "https://x/3", "published": datetime(2024, 5, 2),
         "country": "zz", "city": None},
    ]
    sigs = articles_to_signals(rows)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["kind"] == "article" and s["source"] == "corpus" and s["confirmed"] is True
    assert s["date"] == "2024-05-01" and int(s["t"]) == 2024
    assert s["lat"] is not None and s["lon"] is not None


def test_articles_join_the_collected_stream():
    from datetime import date

    base = len(collect())
    extra = articles_to_signals([
        {"title": "T", "url": "u", "published": date(2024, 1, 1), "country": "gb", "city": "London"},
    ])
    assert len(collect(extra=extra)) == base + 1
    # respects the kind filter like any other signal
    assert all(s["kind"] == "article" for s in collect(kinds={"article"}, extra=extra))


def test_geocode_does_not_mislabel_wrong_country_city():
    from src.timemap.geocode import geocode

    # Paris exists in the gazetteer under FR; asking for a US "Paris" must NOT return
    # France tagged as a precise city — it falls back to a US country-level point.
    us = geocode("us", "Paris")
    assert us is not None
    if us["geocode"] == "city":
        assert (us.get("place") or "").lower() != "paris"   # never France-as-city for a US article
    else:
        assert us["geocode"] == "country"
    # the matching country/city pair is still a precise city hit
    fr = geocode("fr", "Paris")
    assert fr and fr["geocode"] == "city" and fr["place"] == "Paris"


def test_time_range_reports_bounds_and_counts():
    rng = time_range(collect())
    assert rng["min"] <= rng["max"]
    assert rng["count"] == sum(rng["by_kind"].values())
