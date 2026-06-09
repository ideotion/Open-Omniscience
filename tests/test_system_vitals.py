"""Live activity monitor + /api/system/vitals endpoint.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The vitals endpoint is the app observing *itself* (loopback-only, never telemetry).
These tests assert the honest contract: the fetcher-measured scraping counters are
real and reflect live state, and any network figure is labelled system-wide.
"""

from fastapi.testclient import TestClient

from src.api.main import app
from src.monitoring.activity import activity_monitor


def test_activity_monitor_tracks_current_bytes_and_completion():
    activity_monitor.fetch_started("https://www.example.com/news/article-9")
    assert activity_monitor.snapshot()["current_fetch"]["url"].endswith("article-9")

    before = activity_monitor.snapshot()["bytes_total"]
    activity_monitor.fetch_bytes(5000)
    activity_monitor.fetch_bytes(-7)  # non-positive deltas are ignored
    activity_monitor.fetch_bytes(0)
    activity_monitor.fetch_finished()

    after = activity_monitor.snapshot()
    assert after["current_fetch"] is None  # cleared on completion
    assert after["bytes_total"] == before + 5000  # only the real bytes counted
    assert after["last_url"].endswith("article-9")


def test_vitals_endpoint_shape_and_honesty():
    with TestClient(app) as c:
        body = c.get("/api/system/vitals").json()

    assert {"at", "uptime_s", "process", "scraping", "network_system_wide"} <= set(body)
    # Process vitals always expose these keys (real values, or honest null).
    assert {"cpu_percent", "rss_bytes", "io_read_bytes", "io_write_bytes"} <= set(body["process"])
    # Scraping counters are cumulative + carry a clock so the UI can derive a rate.
    assert {"bytes_total", "fetches_total", "current_fetch", "at"} <= set(body["scraping"])
    # Network is labelled system-wide; it is never passed off as the app's own traffic.
    assert "network_system_wide" in body
    assert "app_network" not in body


def test_vitals_reflects_an_in_flight_fetch():
    activity_monitor.fetch_started("https://www.test.example/live/42")
    try:
        with TestClient(app) as c:
            cur = c.get("/api/system/vitals").json()["scraping"]["current_fetch"]
        assert cur is not None and cur["url"].endswith("/live/42")
        assert cur["elapsed_s"] >= 0
    finally:
        activity_monitor.fetch_finished()
