"""
The official-statistics producer directory (Group N, slice 1): a curated, global,
descriptive catalog — controversial sources, no figures, no scores, no network.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.catalog.normalize import registrable_domain
from src.stats.agencies import continents_covered, get_agency, list_agencies


def test_catalog_is_global_and_well_formed():
    agencies = list_agencies()
    assert len(agencies) >= 20
    codes = [a.code for a in agencies]
    assert len(codes) == len(set(codes))  # unique
    for a in agencies:
        assert a.code and a.name and a.acronym and a.home_url
        assert a.scope in ("national", "international")
        # National producers carry a country; IGOs do not.
        assert (a.country is None) == (a.scope == "international")
    # Deliberately global (the ruling): BRICS + Africa + IGOs all present.
    by_code = {a.code for a in agencies}
    assert {"cn-nbs", "in-mospi", "br-ibge", "ru-rosstat", "za-statssa"} <= by_code  # BRICS
    assert {"ng-nbs", "ke-knbs", "eg-capmas"} <= by_code  # more of Africa
    assert {"worldbank", "imf", "eurostat", "unstats"} <= by_code  # IGOs
    # National coverage reaches every inhabited continent.
    nat = continents_covered()
    assert {"Africa", "Asia", "Europe", "North America", "South America", "Oceania"} <= nat


def test_a_news_url_stays_on_the_agencys_own_domain():
    """``news_url`` is the crawl START URL for that agency's Source row.

    ``crawl_source`` derives its same-domain bound FROM the start URL, so a news_url
    on a different registrable domain would silently redirect the entire crawl to
    another site while storing everything it found under this producer's name — a
    provenance corruption, not a mere mis-config. Pinned here so the operator's
    networked research pass (which fills these URLs in) cannot introduce one, and so
    a plain-http entry cannot downgrade the transport either.

    Every agency ships news_url=None today (the sandbox has no egress to verify a
    real one, and a fabricated endpoint is forbidden) — this guard exists for the
    moment they are filled.
    """
    for a in list_agencies():
        news = (a.news_url or "").strip()
        if not news:
            continue  # honest gap: awaiting research, never a guessed URL
        assert news.startswith("https://"), f"{a.code}: news_url must be https"
        assert registrable_domain(news) == registrable_domain(a.home_url), (
            f"{a.code}: news_url {news!r} leaves the producer's own domain"
        )


def test_no_agency_carries_a_controversial_verdict_no_score():
    """Maintainer ruling 2026-06-19 #50: drop the per-source "controversial" verdict
    (a label is itself a verdict). The directory stays descriptive — no verdict field,
    no score; the stanced nature is a descriptive caveat on the response, not a label."""
    for a in list_agencies():
        d = a.to_dict()
        assert "controversial" not in d  # no verdict label (#50)
        assert "score" not in d and "rank" not in d  # directory, not a verdict
    assert get_agency("FR-INSEE").acronym == "INSEE"  # case-insensitive lookup
    assert get_agency("nope") is None


def test_agencies_endpoint():
    from src.api.main import app

    with TestClient(app) as client:
        r = client.get("/api/stats/agencies")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == len(data["agencies"]) >= 20
    # The stanced nature stays as a descriptive caveat — not a per-source label.
    assert data["caveat"] and "stanced" in data["caveat"].lower()
    assert all("controversial" not in x for x in data["agencies"])  # no verdict (#50)
    assert "Africa" in data["continents_covered"] and "Asia" in data["continents_covered"]
    # International producers sort first (deterministic grouping).
    assert data["agencies"][0]["scope"] == "international"
