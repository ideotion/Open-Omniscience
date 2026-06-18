"""Official-statistics FIGURE API (Group N): consented fetch + vintaged store + views.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ONE networked stats action (``POST /figures/fetch``) is exercised with an injected
getter so NO socket is opened, and the kill-switch refusal is proven (airplane mode →
409, no fetch attempted). The read views (figures / vintages / triangulate / sources)
round-trip stored data. The honesty contract is asserted: no score field, gaps kept
as null, producers side by side never averaged.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.ingest import activate_kill_switch, clear_kill_switch


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# A minimal but real-shaped World Bank API v2 JSON payload: [page_meta, [observations]].
_WB_PAYLOAD = [
    {"page": 1, "pages": 1, "per_page": 50, "total": 2},
    [
        {"indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP"},
         "country": {"id": "FR", "value": "France"}, "countryiso3code": "FRA",
         "date": "2021", "value": 2957000000000.0, "unit": ""},
        {"indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP"},
         "country": {"id": "FR", "value": "France"}, "countryiso3code": "FRA",
         "date": "2020", "value": None, "unit": ""},  # a published gap -> value None
    ],
]


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c
    clear_kill_switch()  # never leak airplane state across tests


def test_fetch_refused_under_airplane_mode(client):
    activate_kill_switch()
    try:
        r = client.post("/api/stats/figures/fetch",
                        json={"source": "worldbank", "indicator": "NY.GDP.MKTP.CD", "country": "FR"})
        assert r.status_code == 409
        assert "airplane" in r.json()["detail"].lower()
    finally:
        clear_kill_switch()


def test_fetch_stores_figures_with_injected_getter(client, monkeypatch):
    clear_kill_switch()
    # Patch the production getter so the real fetch + parse path runs with NO socket.
    import src.stats.fetch as statfetch
    monkeypatch.setattr(statfetch, "_default_getter", lambda url: _FakeResp(_WB_PAYLOAD))

    r = client.post("/api/stats/figures/fetch",
                    json={"source": "worldbank", "indicator": "NY.GDP.MKTP.CD", "country": "FR"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fetched"] == 2 and body["stored"] == 2 and body["gaps"] == 1
    # No fabricated score field on any sampled figure.
    for f in body["sample"]:
        assert not any("score" in k for k in f)

    # The stored figures are now visible in the filterable view (latest vintage).
    v = client.get("/api/stats/figures", params={"series_id": "NY.GDP.MKTP.CD", "ref_area": "FRA"}).json()
    assert v["count"] >= 2
    vals = {row["time_period"]: row["value"] for row in v["figures"]}
    assert vals["2021"] == 2957000000000.0
    assert vals["2020"] is None  # gap preserved, never 0

    # A second identical fetch is idempotent per vintage (extracted_at differs only if
    # the clock advanced; the same payload at the same instant dedups). Re-fetching
    # never errors and never averages.
    r2 = client.post("/api/stats/figures/fetch",
                     json={"source": "worldbank", "indicator": "NY.GDP.MKTP.CD", "country": "FR"})
    assert r2.status_code == 200


def test_fetch_records_a_subscription_for_scheduled_refresh(client, monkeypatch):
    """Ruling #12: a user fetch is recorded as a tracked subscription the scheduler
    replays for new vintages. Idempotent; toggle + delete work; refresh is airplane-gated."""
    clear_kill_switch()
    import src.stats.fetch as statfetch
    monkeypatch.setattr(statfetch, "_default_getter", lambda url: _FakeResp(_WB_PAYLOAD))

    client.post("/api/stats/figures/fetch",
                json={"source": "worldbank", "indicator": "NY.GDP.MKTP.CD", "country": "FR"})
    subs = client.get("/api/stats/subscriptions").json()
    assert subs["count"] >= 1
    mine = [s for s in subs["subscriptions"] if s["indicator"] == "NY.GDP.MKTP.CD"]
    assert mine and mine[0]["enabled"] is True and mine[0]["source"] == "worldbank"
    sid = mine[0]["id"]
    # The SAME fetch again does not create a second subscription (idempotent).
    client.post("/api/stats/figures/fetch",
                json={"source": "worldbank", "indicator": "NY.GDP.MKTP.CD", "country": "FR"})
    again = [s for s in client.get("/api/stats/subscriptions").json()["subscriptions"]
             if s["indicator"] == "NY.GDP.MKTP.CD"]
    assert len(again) == 1

    # Toggle interval + disable; delete.
    assert client.patch(f"/api/stats/subscriptions/{sid}", json={"interval_days": 90}).json()["interval_days"] == 90
    assert client.patch(f"/api/stats/subscriptions/{sid}", json={"enabled": False}).json()["enabled"] is False
    assert client.delete(f"/api/stats/subscriptions/{sid}").status_code == 200
    assert client.patch("/api/stats/subscriptions/99999", json={"enabled": True}).status_code == 404

    # Refresh under airplane mode opens no socket (the figures already prove the online path).
    activate_kill_switch()
    try:
        ref = client.post("/api/stats/subscriptions/refresh").json()
        assert ref["refreshed"] == 0 and ref["stored"] == 0  # offline -> nothing fetched
    finally:
        clear_kill_switch()


def test_fetch_validates_source_and_required_fields(client):
    clear_kill_switch()
    assert client.post("/api/stats/figures/fetch", json={"source": "nope"}).status_code == 422
    # worldbank needs an indicator
    assert client.post("/api/stats/figures/fetch", json={"source": "worldbank"}).status_code == 422
    # eurostat needs a dataset
    assert client.post("/api/stats/figures/fetch", json={"source": "eurostat"}).status_code == 422


def test_triangulate_endpoint_side_by_side(client, monkeypatch):
    clear_kill_switch()
    import src.stats.fetch as statfetch

    # Two producers report the SAME series_id "X" for FRA 2021, different units: the
    # worldbank figure is fetched (USD), the eurostat figure (EUR) is stored directly below.
    wb = [{"page": 1, "pages": 1, "per_page": 1, "total": 1},
          [{"indicator": {"id": "X"}, "countryiso3code": "FRA", "date": "2021", "value": 100.0, "unit": "USD"}]]
    monkeypatch.setattr(statfetch, "_default_getter", lambda url: _FakeResp(wb))
    client.post("/api/stats/figures/fetch", json={"source": "worldbank", "indicator": "X", "country": "FR"})
    # Store the eurostat figure under agency "eurostat" but with the worldbank parser
    # shape by routing through the worldbank fetch with agency overridden in the store.
    # Simpler: directly store via the store helper to keep the test about triangulation.
    from src.database.session import session_scope
    from src.stats.sdmx import StatFigure
    from src.stats.store import store_figures
    with session_scope() as db:
        store_figures(db, [StatFigure(
            agency="eurostat", series_id="X", ref_area="FRA", time_period="2021",
            value=90.0, unit="EUR", methodology_ref=None, adjustment=None,
            base_year=None, extracted_at="2026-06-17T00:00:00Z")])

    tri = client.get("/api/stats/triangulate", params={"series_id": "X", "ref_area": "FRA"}).json()
    assert tri["count"] == 1
    cell = tri["cells"][0]
    assert cell["n_producers"] == 2
    assert cell["comparability"]["comparable"] is False  # USD vs EUR
    assert "never averaged" in tri["caveat"].lower()


def test_registered_sources_view_filters(client):
    # Register the curated agencies as disabled statistics sources, then read them back.
    client.post("/api/stats/sources/ingest")
    body = client.get("/api/stats/sources").json()
    assert body["count"] >= 1
    assert all(s["enabled"] is False for s in body["sources"])  # disabled by design
    # No score is surfaced.
    for s in body["sources"]:
        assert "reliability_score" not in s and not any("score" in k for k in s)
    # A region filter narrows the directory.
    africa = client.get("/api/stats/sources", params={"region": "africa"}).json()
    assert africa["count"] <= body["count"]
