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
