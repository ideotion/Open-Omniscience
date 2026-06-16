"""
Bundled, dated catalog of OSM region extracts (for the offline-map download manager).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A curated, neutral list of Geofabrik-style ``.osm.pbf`` region extracts the offline
mapping subsystem (Group M) can download and manage like the Wikipedia dumps: each
region's code (Geofabrik path), display name, continent, and an approximate COMPRESSED
size so the picker is informative WITHOUT a network probe (zero-network boot / airplane
mode stay intact — UI invariant #14). The exact size is always read from the mirror at
download time.

HONESTY CONTRACT (mirrors src.wiki.dump_sizes.DUMP_SIZES_AS_OF + the model catalog):
region sizes drift each cycle. ``OSM_SIZES_AS_OF`` is shown wherever the estimates
appear (the caveat reads "estimate · reviewed {date} · exact on download"), and a
repo-invariant freshness test (tests/test_osm_regions.py) FAILS once it is older than
the window — forcing a re-review against https://download.geofabrik.de or a knowing
date bump. Values are deliberately rounded and never presented as a mirror's exact size.

Top-level continent extracts only at this first slice (the stable, always-available
Geofabrik regions); country-level sub-extracts are a curated follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass

# Review vintage of the size estimates below (when last compiled/checked), NOT a
# claim about a specific mirror snapshot. Format "YYYY-MM" (freshness-tested).
OSM_SIZES_AS_OF = "2026-06"

_GB = 1024**3
_MB = 1024**2


@dataclass(frozen=True)
class OsmRegion:
    code: str  # Geofabrik region path, e.g. "europe", "north-america"
    name: str  # display name
    continent: str  # grouping (a continent, or "Planet" for the whole file)
    approx_bytes: int  # approximate compressed .osm.pbf size (rounded estimate)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "continent": self.continent,
            "size_estimate_bytes": self.approx_bytes,
        }


# Approximate COMPRESSED .osm.pbf sizes, rounded — order-of-magnitude estimates only
# (the caveat says so). The whole "planet" file plus the always-available continent
# extracts; sorted largest-first by the catalog accessor.
_REGIONS: tuple[OsmRegion, ...] = (
    OsmRegion("planet", "Whole planet", "Planet", round(72 * _GB)),
    OsmRegion("europe", "Europe", "Europe", round(28 * _GB)),
    OsmRegion("north-america", "North America", "North America", round(14 * _GB)),
    OsmRegion("asia", "Asia", "Asia", round(13 * _GB)),
    OsmRegion("africa", "Africa", "Africa", round(5 * _GB)),
    OsmRegion("south-america", "South America", "South America", round(3 * _GB)),
    OsmRegion("australia-oceania", "Australia & Oceania", "Oceania", round(1.3 * _GB)),
    OsmRegion("central-america", "Central America", "Central America", round(600 * _MB)),
    OsmRegion("antarctica", "Antarctica", "Antarctica", round(30 * _MB)),
)

_BY_CODE = {r.code: r for r in _REGIONS}
# Geofabrik region codes are lowercase letters joined by single hyphens — validated
# so a code can never escape into a path/URL it shouldn't (defense in depth).
import re as _re  # noqa: E402

_CODE_RE = _re.compile(r"^[a-z]+(-[a-z]+)*$")


def list_regions() -> list[OsmRegion]:
    """Catalog, largest estimate first (the heaviest downloads surface first)."""
    return sorted(_REGIONS, key=lambda r: -r.approx_bytes)


def get_region(code: str) -> OsmRegion | None:
    return _BY_CODE.get((code or "").strip().lower())


def is_valid_code(code: str) -> bool:
    """True for a syntactically valid Geofabrik region code (path-safe)."""
    c = (code or "").strip().lower()
    return bool(c) and len(c) <= 64 and bool(_CODE_RE.match(c))


def estimate_bytes(code: str) -> int | None:
    r = get_region(code)
    return r.approx_bytes if r else None
