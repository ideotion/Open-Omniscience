"""
City coordinate gazetteer (name -> lat/lon/country), for the Insights map.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A small sample ships so the map renders out of the box; the full gazetteer is
generated from Wikidata (CC0) by scripts/build_city_gazetteer.py into
configs/cities.yml (preferred when present). Lookups are disambiguated by the
source's country (Paris/FR vs Paris/US), falling back to the most-populous match.
The SPARQL parser is pure and unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_CONF = Path(__file__).resolve().parents[2] / "configs"
GAZETTEER_PATH = _CONF / "cities.yml"  # generated (full)
SAMPLE_PATH = _CONF / "cities.sample.yml"  # shipped (small fallback)

# Wikidata P625 coordinate literal, e.g. "Point(2.3522 48.8566)" (lon lat).
_POINT_RE = re.compile(r"Point\(\s*([-\d.]+)\s+([-\d.]+)\s*\)")


@dataclass
class City:
    name: str
    lat: float
    lon: float
    country: str | None = None
    population: int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "country": self.country,
            "population": self.population,
        }


def load_cities(path: Path | None = None) -> list[City]:
    """Load the gazetteer (generated file if present, else the shipped sample)."""
    p = path or (GAZETTEER_PATH if GAZETTEER_PATH.exists() else SAMPLE_PATH)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text("utf-8")) or {}
    out: list[City] = []
    for c in data.get("cities", []):
        if not isinstance(c, dict) or c.get("name") is None:
            continue
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            City(
                name=str(c["name"]),
                lat=lat,
                lon=lon,
                country=(str(c.get("country", "")).lower() or None),
                population=c.get("population"),
            )
        )
    return out


def build_index(cities: list[City]) -> dict:
    """Index for lookup: by (name, country) and by name (best = most populous)."""
    by_pair: dict[tuple[str, str | None], City] = {}
    by_name: dict[str, City] = {}
    for c in cities:
        nl = c.name.lower()
        by_pair[(nl, c.country)] = c
        cur = by_name.get(nl)
        if cur is None or (c.population or 0) > (cur.population or 0):
            by_name[nl] = c
    return {"pair": by_pair, "name": by_name}


@lru_cache(maxsize=1)
def cached_index() -> dict:
    """The default gazetteer's lookup index, parsed ONCE per process.

    ``build_index(load_cities())`` re-reads and re-parses the whole YAML on every
    call, and :func:`src.timemap.locextract.extract_locations` was calling it
    PER ARTICLE. Measured 2026-07-30 on a gazetteer the size
    ``scripts/build_city_gazetteer.py`` actually produces from Wikidata (50,000
    cities, 5.2 MB): ``load_cities`` alone takes 17.0 SECONDS, so a 500,000-article
    import spent something like 2,300 core-hours re-parsing the same file. Even
    with the tiny shipped 21-city sample it was ~6 ms per article, 6% of
    ``extract_locations``.

    No new staleness class: ``locextract._patterns()`` and ``geocode._index()``
    already cache exactly this data for the process lifetime, so the gazetteer was
    ALREADY assumed immutable while the app runs -- it is generated offline by a
    script, never written at runtime. If anything this removes an inconsistency,
    since the cached patterns and the freshly-parsed index could previously come
    from two different versions of the file.

    Callers that supply their OWN city list keep using :func:`build_index`
    directly; this is only the default-gazetteer path."""
    return build_index(load_cities())


def lookup(index: dict, name: str, country: str | None = None) -> City | None:
    """Find a city by name, disambiguated by country when available."""
    nl = (name or "").strip().lower()
    if not nl:
        return None
    if country:
        hit = index["pair"].get((nl, country.strip().lower()))
        if hit:
            return hit
    return index["name"].get(nl)


def parse_cities_sparql(payload: dict) -> list[City]:
    """Parse a WDQS response with ?cityLabel ?coord ?cc ?population into cities."""
    bindings = (payload or {}).get("results", {}).get("bindings", [])
    out: list[City] = []
    for b in bindings:
        name = (b.get("cityLabel") or {}).get("value")
        coord = (b.get("coord") or {}).get("value")
        if not name or not coord:
            continue
        m = _POINT_RE.search(coord)
        if not m:
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        cc = (b.get("cc") or {}).get("value")
        pop_raw = (b.get("population") or {}).get("value")
        try:
            pop = int(float(pop_raw)) if pop_raw else None
        except (TypeError, ValueError):
            pop = None
        out.append(
            City(name=name, lat=lat, lon=lon, country=(cc.lower() if cc else None), population=pop)
        )
    return out
