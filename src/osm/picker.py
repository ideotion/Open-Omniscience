"""The OSM lane's country picker: what it suggests, what each country costs (S05-04 S3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULINGS (Q807 = a, Q806 = b, Q824 = a, Q828 = a). The lane is OFF until the operator picks
countries. The wizard SUGGESTS the countries of the interface language, read from
``configs/language_countries.yml`` -- never from the IP address, which this module never sees
and nothing here could ask for. Extracts stay continent-level, so a country costs its
CONTINENT's download; the per-country daily change cost is shown before the choice, with the
cadence and the re-baseline rule stated (applying the changes is 0.6's, S06-01).

NOTHING HERE TOUCHES THE NETWORK. Choosing a country writes one setting. The download is the
existing ``/api/geo/downloads`` job, started by the Settings button through the ONE online
consent (``ensureOnline``); under the kill switch the job is refused before a socket opens and
reads "paused — airplane mode", by name.

TWO FIGURES ARE ESTIMATES, AND SAY SO:

* the extract size is ``src/geo/osm_regions.py``'s dated, rounded catalogue figure (the mirror's
  exact size is read when the download starts);
* the daily change file is NOT in any catalogue this repo holds. It is derived here, openly:
  the planet's daily change file (:data:`PLANET_DAILY_DIFF_BYTES`, FROM MEMORY, rounded) scaled
  by the extract's share of the planet's size. Editing activity is not proportional to file
  size, so :data:`DIFF_METHOD` and :data:`DIFF_CAVEAT` travel with every figure, and the
  operator's first 0.6 apply is what measures it.

WHICH EXTRACT HOLDS A COUNTRY. The continent from ``src/catalog/countries.py``, mapped to its
Geofabrik region, with the exceptions Geofabrik makes (FROM MEMORY -- confirm against
https://download.geofabrik.de before relying on one): Central America and the Caribbean are
their own region; Cyprus, Georgia and Turkey sit in Europe; Russia is its own region, which the
catalogue does not list, so Russia has no extract here and says so rather than being mapped to
a continent that does not hold it. A cut from the wrong extract fails loudly anyway: the ingest
finds no ``admin_level=2`` relation for the country and records the failure.
"""

from __future__ import annotations

import re
from typing import Any

#: When the diff estimate below was last reviewed (freshness-tested through the registry).
OSM_DIFF_ESTIMATE_AS_OF = "2026-09"

#: The whole planet's daily change file, compressed, rounded. FROM MEMORY: the operator's
#: first daily apply (0.6) measures the real figure for the extract it reads.
PLANET_DAILY_DIFF_BYTES = 150 * 1024**2

#: Geofabrik keeps each extract's daily change files for about three months (the brief's
#: SEARCH-VERIFIED fact); a gap longer than that means downloading the extract again.
DIFF_RETENTION_DAYS = 90

DIFF_METHOD = (
    "Estimated: the planet's daily change file (about 150 MB, rounded, from memory) scaled by "
    "this extract's share of the planet's size. Countries in the same extract share one change "
    "file."
)
DIFF_CAVEAT = (
    "Editing activity is not proportional to file size, so this is an order of magnitude, not a "
    "measurement. The first daily update measures the real figure."
)
CADENCE = (
    "One change file a day per extract. Applying it arrives in 0.6; until then the extract is "
    "read as downloaded. If the changes are not applied for longer than about three months "
    "(what the mirror keeps), the extract is downloaded again instead (a re-baseline)."
)
SUGGESTION_BASIS = (
    "Suggested from the interface language (the countries where it is an official or major "
    "language). Never from your IP address."
)
OFF = "Off: no country chosen. Nothing is downloaded or read until you choose one."

#: Continent (as ``src/catalog/countries.py`` names it) -> the Geofabrik region code.
_REGION_OF_CONTINENT: dict[str, str] = {
    "Africa": "africa",
    "Asia": "asia",
    "Europe": "europe",
    "North America": "north-america",
    "South America": "south-america",
    "Oceania": "australia-oceania",
    "Antarctica": "antarctica",
}

#: Countries Geofabrik files under another region than their continent (FROM MEMORY).
_REGION_OVERRIDES: dict[str, str] = {
    **dict.fromkeys(["bz", "cr", "sv", "gt", "hn", "ni", "pa", "cu", "ht", "do", "jm", "bs", "bb", "ag", "dm", "gd", "kn", "lc", "vc", "tt"], "central-america"),
    "cy": "europe",
    "ge": "europe",
    "tr": "europe",
}

#: Countries no catalogued extract holds, with the reason shown in place of a size.
_NO_EXTRACT: dict[str, str] = {
    "ru": "Russia is published as its own extract, which this catalogue does not list yet.",
}

_CC_RE = re.compile(r"^[a-z]{2}$")


class PickerError(ValueError):
    """A selection that names something other than a known country."""


def extract_for(cc: str) -> tuple[str | None, str | None]:
    """``(region code, None)`` for the extract holding ``cc``, or ``(None, reason)``."""
    from src.catalog.countries import continent_of

    cc = (cc or "").strip().lower()
    if cc in _NO_EXTRACT:
        return None, _NO_EXTRACT[cc]
    if cc in _REGION_OVERRIDES:
        return _REGION_OVERRIDES[cc], None
    region = _REGION_OF_CONTINENT.get(continent_of(cc) or "")
    if region is None:
        return None, "No continent extract is known for this code."
    return region, None


def daily_diff_estimate(region_code: str) -> int | None:
    """The estimated daily change file for one extract (see :data:`DIFF_METHOD`)."""
    from src.geo.osm_regions import estimate_bytes

    planet = estimate_bytes("planet")
    size = estimate_bytes(region_code)
    if not planet or not size:
        return None
    return round(PLANET_DAILY_DIFF_BYTES * size / planet)


def _row(cc: str, basis: str | None = None) -> dict[str, Any]:
    from src.catalog.countries import country_display_name, to_iso3
    from src.geo.osm_regions import get_region

    code, reason = extract_for(cc)
    region = get_region(code) if code else None
    row: dict[str, Any] = {
        "cc": cc,
        "alpha3": (to_iso3(cc) or "").upper() or None,
        "name": country_display_name(cc) or cc.upper(),
        "extract": region.to_dict() if region else None,
        "extract_reason": reason,
        "diff_daily_estimate_bytes": daily_diff_estimate(code) if code else None,
    }
    if basis:
        row["basis"] = basis
    return row


def suggestions(lang: str) -> list[dict[str, Any]]:
    """The interface language's countries, in the file's order (official first by construction)."""
    from src.civic.coverage_floor import load_floor

    block = (load_floor().get("languages") or {}).get((lang or "").strip().lower()) or {}
    rows = block.get("countries") or []
    return [_row(r["cc"], r.get("basis")) for r in rows]


def selected() -> list[str]:
    """The chosen countries (lowercase alpha-2). Empty = the lane is off."""
    from src.config.app_settings import load_settings

    return list(load_settings().osm_countries or [])


def save_selection(codes: list[str]) -> list[str]:
    """Replace the selection. Writes one local setting; opens nothing."""
    from src.catalog.countries import ISO_3166_1_ALPHA2
    from src.config.app_settings import save_settings

    if not isinstance(codes, list):
        raise PickerError("countries must be a list of ISO 3166-1 alpha-2 codes")
    clean: list[str] = []
    for c in codes:
        cc = str(c or "").strip().lower()
        if not _CC_RE.match(cc) or cc not in ISO_3166_1_ALPHA2:
            raise PickerError(f"not an ISO 3166-1 alpha-2 country code: {c!r}")
        if cc not in clean:
            clean.append(cc)
    return list(save_settings({"osm_countries": clean}).osm_countries)


def picker_state(lang: str) -> dict[str, Any]:
    """Everything the Settings picker draws. Reads local files only."""
    from src.catalog.countries import ISO_3166_1_ALPHA2
    from src.geo.osm_regions import OSM_SIZES_AS_OF

    chosen = selected()
    everyone = sorted((_row(cc) for cc in ISO_3166_1_ALPHA2), key=lambda r: r["name"].casefold())
    return {
        "enabled": bool(chosen),
        "off": None if chosen else OFF,
        "lang": (lang or "").strip().lower(),
        "suggestion_basis": SUGGESTION_BASIS,
        "suggested": suggestions(lang),
        "selected": [_row(cc) for cc in chosen],
        "countries": [{"cc": r["cc"], "name": r["name"], "alpha3": r["alpha3"]} for r in everyone],
        "size_as_of": OSM_SIZES_AS_OF,
        "diff": {
            "method": DIFF_METHOD,
            "caveat": DIFF_CAVEAT,
            "cadence": CADENCE,
            "retention_days": DIFF_RETENTION_DAYS,
            "as_of": OSM_DIFF_ESTIMATE_AS_OF,
            "apply": "0.6",
        },
    }
