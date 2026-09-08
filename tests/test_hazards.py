"""Hazards channel: parse open feeds into honest space-time records + best-effort API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import json

from fastapi.testclient import TestClient

from src.hazards.parse import parse_gdacs, parse_usgs

_USGS = json.dumps(
    {
        "features": [
            {
                "id": "us7000abcd",
                "properties": {
                    "mag": 7.1,
                    "place": "120km SSW of Town",
                    "title": "M 7.1 - 120km SSW of Town",
                    "time": 1_700_000_000_000,
                    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                },
                "geometry": {"coordinates": [142.5, 38.1, 30.0]},
            },
            {
                "id": "us7000efgh",
                "properties": {
                    "mag": 4.6,
                    "place": "near City",
                    "title": "M 4.6 - near City",
                    "time": 1_700_100_000_000,
                    "url": "https://earthquake.usgs.gov/x",
                },
                "geometry": {"coordinates": [-70.0, -33.4]},
            },
            {
                "id": "bad",
                "properties": {"mag": 5.0},
                "geometry": {"coordinates": []},
            },  # no coords -> skipped
        ]
    }
)

_GDACS = json.dumps(
    {
        "features": [
            {
                "properties": {
                    "eventid": 1001,
                    "eventtype": "TC",
                    "alertlevel": "Red",
                    "name": "Cyclone Xyz",
                    "fromdate": "2026-06-01T00:00:00",
                    "country": "Philippines",
                    "url": {"report": "https://www.gdacs.org/report?eventid=1001"},
                },
                "geometry": {"coordinates": [125.0, 12.0]},
            },
            {
                "properties": {
                    "eventid": 1002,
                    "eventtype": "FL",
                    "alertlevel": "Orange",
                    "name": "Floods",
                    "fromdate": "2026-06-02T00:00:00",
                    "country": "Bangladesh",
                    "url": "https://www.gdacs.org/x",
                },
                "geometry": {"coordinates": [90.4, 23.7]},
            },
        ]
    }
)


def test_parse_usgs_normalises_and_skips_bad():
    rows = parse_usgs(_USGS)
    assert len(rows) == 2  # the coord-less entry is skipped, never guessed
    big = next(r for r in rows if r["id"] == "us7000abcd")
    assert big["type"] == "earthquake" and big["magnitude"] == 7.1 and big["severity"] == "major"
    assert big["lat"] == 38.1 and big["lon"] == 142.5  # [lon,lat] -> (lat,lon)
    assert big["time"].startswith("20") and big["url"].startswith("https://")
    assert next(r for r in rows if r["id"] == "us7000efgh")["severity"] == "moderate"
    assert parse_usgs("not json") == []  # malformed feed -> empty, no raise


def test_parse_gdacs_alertlevel_to_tier_and_nested_url():
    rows = parse_gdacs(_GDACS)
    tc = next(r for r in rows if r["type"] == "cyclone")
    assert tc["severity"] == "urgent" and tc["place"] == "Philippines"  # Red -> urgent
    assert tc["url"] == "https://www.gdacs.org/report?eventid=1001"  # nested {report:…} unwrapped
    assert next(r for r in rows if r["type"] == "flood")["severity"] == "watch"  # Orange -> watch


def test_parse_gdacs_green_maps_to_info():
    green = json.dumps(
        {
            "features": [
                {
                    "properties": {
                        "eventid": 1003,
                        "eventtype": "DR",
                        "alertlevel": "Green",
                        "name": "Drought",
                        "fromdate": "2026-06-03T00:00:00",
                        "country": "Kenya",
                        "url": "https://www.gdacs.org/y",
                    },
                    "geometry": {"coordinates": [37.0, -1.0]},
                }
            ]
        }
    )
    assert parse_gdacs(green)[0]["severity"] == "info"  # Green -> info


def test_parse_gdacs_missing_or_unrecognized_level_is_unknown_not_info():
    # a malformed/renamed alertlevel must never be silently reported as the
    # lowest provider tier ("info") -- honest "unknown" is the only correct
    # answer here, mirroring _quake_band(None) -> "unknown" above.
    missing = json.dumps(
        {
            "features": [
                {
                    "properties": {
                        "eventid": 1004,
                        "eventtype": "VO",
                        "name": "Volcano with no alertlevel",
                        "fromdate": "2026-06-04T00:00:00",
                        "country": "Indonesia",
                        "url": "https://www.gdacs.org/z",
                    },
                    "geometry": {"coordinates": [110.0, -7.0]},
                },
                {
                    "properties": {
                        "eventid": 1005,
                        "eventtype": "VO",
                        "alertlevel": "yellow",  # not a GDACS level this app recognises
                        "name": "Volcano with an unrecognized alertlevel",
                        "fromdate": "2026-06-05T00:00:00",
                        "country": "Indonesia",
                        "url": "https://www.gdacs.org/z2",
                    },
                    "geometry": {"coordinates": [110.1, -7.1]},
                },
            ]
        }
    )
    rows = parse_gdacs(missing)
    assert [r["severity"] for r in rows] == ["unknown", "unknown"]


def test_api_relays_and_is_best_effort(monkeypatch):
    import src.api.hazards as hz
    from src.api.main import app

    class _Fetched:
        def __init__(self, content):
            self.content = content
            self.final_url = "x"

    def _fake_fetch(url, require_html=True):
        if "usgs" in url:
            return _Fetched(_USGS)
        raise RuntimeError("gdacs feed unreachable")  # exercise per-source failure

    monkeypatch.setattr(hz._fetcher, "fetch", _fake_fetch)
    with TestClient(app) as c:
        body = c.get("/api/hazards?min_magnitude=5").json()
        # USGS parsed (M>=5 keeps only the 7.1); GDACS failure reported, not a 500.
        assert body["count"] == 1 and body["hazards"][0]["magnitude"] == 7.1
        assert any("gdacs" in f for f in body["failures"])
        assert "silence is not safety" in body["caveat"].lower()
