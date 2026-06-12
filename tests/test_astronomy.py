"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

T11 — the agenda astronomy layer: Meeus ch.49 lunar phases, verified against
the book's own worked example (the gold reference) and published almanac
full-moon dates. Honest accuracy fields travel with every result.
"""

from __future__ import annotations

from math import floor

from src.events.astronomy import _jde_phase, phases_for_year


def test_meeus_worked_example_49a_new_moon_feb_1977():
    """Meeus, example 49.a: the new moon of 1977 February — JDE 2443192.65118.
    The book computes this exact value with the same series; we require
    agreement to 3e-4 day (~26 s)."""
    k = floor((1977.13 - 2000) * 12.3685)  # = -283 per the book
    assert k == -283
    jde = _jde_phase(float(k))
    assert abs(jde - 2443192.65118) < 0.0003, f"got {jde!r}"


def test_full_moons_2024_match_published_almanac_dates():
    """Published almanac full-moon dates (UTC), 2024 — computed dates must
    land within the same UTC day ±1 (the series is minutes-accurate; ±1 day
    guards timezone-of-publication edges, honestly)."""
    expected = {1: 25, 2: 24, 3: 25, 4: 23, 5: 23, 6: 22, 7: 21, 8: 19, 9: 18, 10: 17, 11: 15, 12: 15}
    got = phases_for_year(2024)["full_moons"]
    by_month = {}
    for fm in got:
        y, m, d = (int(x) for x in fm["date"].split("-"))
        by_month.setdefault(m, d)
    for month, day in expected.items():
        assert month in by_month, f"no full moon computed in 2024-{month:02d}"
        assert abs(by_month[month] - day) <= 1, (
            f"2024-{month:02d}: computed day {by_month[month]}, almanac {day}"
        )


def test_phase_listing_carries_method_and_accuracy():
    out = phases_for_year(2026)
    assert "Meeus" in out["method"]
    assert "ΔT" in out["accuracy"] or "TD" in out["accuracy"]
    assert 11 <= len(out["full_moons"]) <= 14
    assert all(f["phase"] == "full" for f in out["full_moons"])
    # Chronological and within the year.
    dates = [f["date"] for f in out["full_moons"]]
    assert dates == sorted(dates) and all(d.startswith("2026") for d in dates)


def test_meeus_worked_example_27a_june_solstice_1962():
    """Meeus, example 27.a: the June solstice of 1962 — JDE 2437837.39245.
    Agreement to 1e-4 day (~9 s) validates the polynomial + the 24-term table."""
    from src.events.astronomy import _jde_season

    jde = _jde_season(1962, "june_solstice")
    assert abs(jde - 2437837.39245) < 0.0001, f"got {jde!r}"


def test_seasons_2024_match_published_dates():
    """Published 2024 season dates (UTC): Mar 20, Jun 20, Sep 22, Dec 21."""
    from src.events.astronomy import seasons_for_year

    out = seasons_for_year(2024)
    got = {s["event"]: s["date"] for s in out["seasons"]}
    assert got["march_equinox"] == "2024-03-20"
    assert got["june_solstice"] == "2024-06-20"
    assert got["september_equinox"] == "2024-09-22"
    assert got["december_solstice"] == "2024-12-21"
    assert "hemispheres" in out["naming"], "hemisphere honesty must travel with the data"


def test_climate_endpoint_carries_provenance_and_verification_flag():
    import os
    os.environ.setdefault("OO_DB_PLAINTEXT", "1")
    os.environ.setdefault("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        body = c.get("/api/events/climate").json()
        assert body["source"].startswith("NOAA CPC")
        assert "pending" in body["verification_status"], (
            "drafted data must stay flagged until the clearnet check"
        )
        assert body["count"] >= 20
        ep9798 = next(e for e in body["el_nino_episodes"] if e["start"] == "1997-04")
        assert ep9798["intensity"] == "very strong"
        assert ep9798["length_months"] == 14
        astro = c.get("/api/events/astronomy?year=2026").json()
        assert len(astro["seasons"]) == 4
        assert "hemispheres" in astro["seasons_naming"]
