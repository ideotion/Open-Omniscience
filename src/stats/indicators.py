"""Curated per-country indicator catalog for the Governments tab (field test 2026-06-22).

A small, stable set of the most commonly-used country indicators — GDP, population,
life expectancy, labour, public finance + a few well-known indices — each mapped to its
World Bank series code. The Governments tab displays these per country and on the map;
the figures themselves are fetched LIVE through the existing official-statistics path
(``src/stats/fetch.fetch_worldbank``), stored as vintaged ``StatFigure`` rows, and shown
offline thereafter. NO values live here — only the code↔label↔unit mapping.

These are well-known, long-stable World Bank indicator codes, but they are NOT verifiable
without the network (the sandbox blocks the WB API). A WRONG code fails LOUDLY — its
fetch returns an empty series, surfaced as "no data", never a fabricated figure (the same
honesty stance as the markets/EIA feeds). VERIFY on a networked box when convenient.

Honesty notes carried to the UI: every figure is a STANCED producer's published value
(World Bank, here), never a credibility score; a missing value is a published GAP, not
zero; public-finance series (deficit/debt) have PATCHY country coverage by nature.
"""

from __future__ import annotations

# When this catalog of CODES was last curated (not an external freshness artifact — the
# DATA is vintaged per fetch via StatFigure.extracted_at — so deliberately NOT an
# *_AS_OF constant, which would couple it to the external-artifact registry).
CATALOG_REVISED = "2026-06"

# id = the World Bank series code; category groups them in the UI; unit is for the
# smart formatter; "agency" is always World Bank for this curated set.
INDICATOR_CATALOG: list[dict] = [
    # Economy
    {"id": "NY.GDP.MKTP.CD", "label": "GDP (current US$)", "unit": "USD", "category": "economy"},
    {"id": "NY.GDP.PCAP.CD", "label": "GDP per capita (current US$)", "unit": "USD", "category": "economy"},
    {"id": "NY.GDP.MKTP.KD.ZG", "label": "GDP growth (annual %)", "unit": "%", "category": "economy"},
    {"id": "FP.CPI.TOTL.ZG", "label": "Inflation, consumer prices (annual %)", "unit": "%", "category": "economy"},
    # Demography
    {"id": "SP.POP.TOTL", "label": "Population, total", "unit": "people", "category": "demography"},
    {"id": "SP.POP.GROW", "label": "Population growth (annual %)", "unit": "%", "category": "demography"},
    # Health
    {"id": "SP.DYN.LE00.IN", "label": "Life expectancy at birth (years)", "unit": "years", "category": "health"},
    # Labour
    {"id": "SL.UEM.TOTL.ZS", "label": "Unemployment (% of labour force, ILO modelled)", "unit": "%", "category": "labour"},
    {"id": "SL.TLF.TOTL.IN", "label": "Labour force, total", "unit": "people", "category": "labour"},
    # Public finance (patchy coverage by nature — stated to the user)
    {"id": "GC.NLD.TOTL.GD.ZS", "label": "Government net lending/borrowing (% of GDP)", "unit": "%", "category": "public finance"},
    {"id": "GC.DOD.TOTL.GD.ZS", "label": "Central government debt (% of GDP)", "unit": "%", "category": "public finance"},
    # Inequality (patchy coverage)
    {"id": "SI.POV.GINI", "label": "Gini index", "unit": "index", "category": "inequality"},
]

# WB agency key (matches src/stats/fetch.fetch_worldbank's agency="worldbank").
AGENCY = "worldbank"

_BY_ID = {ind["id"]: ind for ind in INDICATOR_CATALOG}


def indicator_ids() -> list[str]:
    """The curated World Bank series codes, in catalog order."""
    return [ind["id"] for ind in INDICATOR_CATALOG]


def indicator_meta(code: str) -> dict | None:
    """The {id,label,unit,category} for one code, or None if it is not curated."""
    return _BY_ID.get((code or "").strip())


def is_curated(code: str) -> bool:
    return (code or "").strip() in _BY_ID
