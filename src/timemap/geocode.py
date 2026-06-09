"""Best-effort, honest geocoding for signals that name a place but no coordinate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The events agenda knows a *country* (and sometimes a *region*/city name) but not a
lat/lon. To place such a signal we reuse the shipped city gazetteer
(:mod:`src.catalog.cities`) — never an invented coordinate:

  * an explicit city name (disambiguated by country)  -> precision ``"city"``
  * otherwise the most-populous known city of the country, as a stand-in point,
    flagged precision ``"country"`` so the UI can show it as approximate.

If neither is known, we return ``None`` and the signal gets no pin — absence is
honest. Pure apart from reading the gazetteer file once.
"""

from __future__ import annotations

from functools import lru_cache

from src.catalog.cities import build_index, load_cities, lookup


@lru_cache(maxsize=1)
def _index() -> dict:
    return build_index(load_cities())


@lru_cache(maxsize=1)
def _country_point() -> dict:
    """ISO country code -> its most-populous gazetteer city (a stand-in centroid)."""
    best: dict[str, object] = {}
    for c in load_cities():
        if not c.country:
            continue
        cur = best.get(c.country)
        if cur is None or (c.population or 0) > (cur.population or 0):  # type: ignore[union-attr]
            best[c.country] = c
    return best


def geocode(country: str | None = None, place: str | None = None) -> dict | None:
    """Resolve a (country, place) pair to ``{lat, lon, geocode}`` or None.

    ``geocode`` records the precision actually achieved: ``"city"`` (a named
    place we matched) or ``"country"`` (a country-level stand-in point).
    """
    cc = (country or "").strip().lower() or None
    if place:
        hit = lookup(_index(), place, cc)
        # Accept the city match only when it is unambiguous: either no country was
        # given, or the matched city is actually IN that country. Otherwise lookup's
        # name-only fallback can return a same-named city elsewhere (a US "Paris"
        # resolving to Paris, France) — we must not pin that and call it precise.
        if hit and (cc is None or (hit.country or None) == cc):
            return {"lat": hit.lat, "lon": hit.lon, "geocode": "city",
                    "place": hit.name}
    if cc:
        rep = _country_point().get(cc)
        if rep is not None:
            return {"lat": rep.lat, "lon": rep.lon, "geocode": "country",
                    "place": rep.name}
    return None
