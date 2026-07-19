"""Place canonicalization by country code (Leads-calibration S4.2 / convergence-amendment C2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the 2026-07-18 field export acceptance: "Allemagne"/"Deutschland" (row 9) and
"United States"/"America"/"Usa" (row 8) collapse to one identity + a canonical display
name; a city keeps its own identity, scoped under its country.
"""

from __future__ import annotations

from src.analytics.place_identity import place_identity


def test_country_level_surface_strings_collapse_to_one_identity():
    a = place_identity("Allemagne", "de", "country")
    b = place_identity("Deutschland", "de", "country")
    assert a[0] == b[0] == "country:de"
    assert a[1] == b[1] == "Germany"


def test_usa_america_collapse_and_display_canonically():
    for name in ("United States", "America", "Usa"):
        key, display = place_identity(name, "us", "country")
        assert key == "country:us"
        assert display == "United States"


def test_uk_displays_canonically_not_titlecased_acronym():
    key, display = place_identity("Uk", "gb", "country")
    assert key == "country:gb"
    assert display == "United Kingdom"  # never the raw "Uk" from "uk".title()


def test_city_level_places_keep_their_own_identity_scoped_by_country():
    paris_fr = place_identity("Paris", "fr", "city")
    washington_us = place_identity("Washington", "us", "city")
    assert paris_fr[0] != washington_us[0]
    assert paris_fr[0] == "place:fr:paris"
    assert paris_fr[1] == "Paris"
    # the same city name in two different countries never collides
    paris_us = place_identity("Paris", "us", "city")
    assert paris_fr[0] != paris_us[0]


def test_unresolvable_country_falls_back_to_the_free_text_name():
    key, display = place_identity("Freedonia", None, "country")
    assert key == "place::freedonia"  # never a fabricated country code
    assert display == "Freedonia"
