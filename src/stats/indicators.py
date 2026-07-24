"""Curated per-country indicator catalog for the Governments tab (field test 2026-06-22).

A set of commonly-used country indicators — economy, demography, health, labour,
education, energy/environment, connectivity, military, and public finance — each
mapped to its World Bank series code. The Governments tab displays these per country
and on the map; the figures themselves are fetched LIVE through the existing
official-statistics path (``src/stats/fetch.fetch_worldbank``), stored as vintaged
``StatFigure`` rows, and shown offline thereafter. NO values live here — only the
code↔label↔unit mapping.

2026-07-24 field-feedback Session A §2 (ruled: "as many items as possible"): the
original 12-code catalog is extended to several dozen. Every ADDED code was
SEARCH-VERIFIED this session (the sandbox blocks direct calls to api.worldbank.org
and data.worldbank.org — both 403 through curl and WebFetch — so verification used
WebSearch against data.worldbank.org's own indicator pages, the established
precedent for this exact constraint; see the Ollama-catalog-refresh entry in
docs/ledger/SHIPPED_LOG.md). Each still carries the same honesty floor as the
original set: a WRONG code fails LOUDLY (its fetch returns an empty series,
surfaced as "no data", never a fabricated figure — the same stance as the
markets/EIA feeds); re-verify live on a networked box when convenient.

Honesty notes carried to the UI: every figure is a STANCED producer's published value
(World Bank, here), never a credibility score; a missing value is a published GAP, not
zero; several series (public-finance, inequality, military, maternal mortality) have
PATCHY country coverage by nature — stated to the user, never silently backfilled.
"""

from __future__ import annotations

# When this catalog of CODES was last curated (not an external freshness artifact — the
# DATA is vintaged per fetch via StatFigure.extracted_at — so deliberately NOT an
# *_AS_OF constant, which would couple it to the external-artifact registry).
CATALOG_REVISED = "2026-07"

# id = the World Bank series code; category groups them in the UI; unit is for the
# smart formatter; "agency" is always World Bank for this curated set.
INDICATOR_CATALOG: list[dict] = [
    # Economy
    {"id": "NY.GDP.MKTP.CD", "label": "GDP (current US$)", "unit": "USD", "category": "economy"},
    {"id": "NY.GDP.PCAP.CD", "label": "GDP per capita (current US$)", "unit": "USD", "category": "economy"},
    {"id": "NY.GDP.MKTP.KD.ZG", "label": "GDP growth (annual %)", "unit": "%", "category": "economy"},
    {"id": "NY.GDP.MKTP.PP.CD", "label": "GDP, PPP (current international $)", "unit": "intl$", "category": "economy"},
    {"id": "NY.GDP.PCAP.PP.CD", "label": "GDP per capita, PPP (current international $)", "unit": "intl$", "category": "economy"},
    {"id": "NE.TRD.GNFS.ZS", "label": "Trade (% of GDP)", "unit": "%", "category": "economy"},
    {"id": "BX.KLT.DINV.WD.GD.ZS", "label": "Foreign direct investment, net inflows (% of GDP)", "unit": "%", "category": "economy"},
    # Prices
    {"id": "FP.CPI.TOTL.ZG", "label": "Inflation, consumer prices (annual %)", "unit": "%", "category": "prices"},
    # Demography
    {"id": "SP.POP.TOTL", "label": "Population, total", "unit": "people", "category": "demography"},
    {"id": "SP.POP.GROW", "label": "Population growth (annual %)", "unit": "%", "category": "demography"},
    {"id": "SP.URB.TOTL.IN.ZS", "label": "Urban population (% of total population)", "unit": "%", "category": "demography"},
    {"id": "SP.DYN.TFRT.IN", "label": "Fertility rate, total (births per woman)", "unit": "births/woman", "category": "demography"},
    # Health
    {"id": "SP.DYN.LE00.IN", "label": "Life expectancy at birth (years)", "unit": "years", "category": "health"},
    {"id": "SH.DYN.MORT", "label": "Mortality rate, under-5 (per 1,000 live births)", "unit": "per 1,000", "category": "health"},
    {"id": "SH.STA.MMRT", "label": "Maternal mortality ratio (modelled estimate, per 100,000 live births)", "unit": "per 100,000", "category": "health"},
    {"id": "SH.MED.PHYS.ZS", "label": "Physicians (per 1,000 people)", "unit": "per 1,000", "category": "health"},
    {"id": "SH.XPD.CHEX.GD.ZS", "label": "Current health expenditure (% of GDP)", "unit": "%", "category": "health"},
    # Labour
    {"id": "SL.UEM.TOTL.ZS", "label": "Unemployment (% of labour force, ILO modelled)", "unit": "%", "category": "labour"},
    {"id": "SL.TLF.TOTL.IN", "label": "Labour force, total", "unit": "people", "category": "labour"},
    {"id": "SL.TLF.CACT.ZS", "label": "Labour force participation rate (% of population 15+, modelled ILO)", "unit": "%", "category": "labour"},
    # Education
    {"id": "SE.ADT.LITR.ZS", "label": "Literacy rate, adult total (% of people ages 15+)", "unit": "%", "category": "education"},
    {"id": "SE.XPD.TOTL.GD.ZS", "label": "Government expenditure on education, total (% of GDP)", "unit": "%", "category": "education"},
    {"id": "SE.PRM.ENRR", "label": "School enrollment, primary (% gross)", "unit": "%", "category": "education"},
    {"id": "SE.SEC.ENRR", "label": "School enrollment, secondary (% gross)", "unit": "%", "category": "education"},
    # Energy & environment
    {"id": "EG.ELC.ACCS.ZS", "label": "Access to electricity (% of population)", "unit": "%", "category": "energy & environment"},
    {"id": "EG.FEC.RNEW.ZS", "label": "Renewable energy consumption (% of total final energy consumption)", "unit": "%", "category": "energy & environment"},
    {"id": "EN.ATM.CO2E.PC", "label": "CO2 emissions (metric tons per capita)", "unit": "t/capita", "category": "energy & environment"},
    {"id": "AG.LND.FRST.ZS", "label": "Forest area (% of land area)", "unit": "%", "category": "energy & environment"},
    # Connectivity
    {"id": "IT.NET.USER.ZS", "label": "Individuals using the Internet (% of population)", "unit": "%", "category": "connectivity"},
    {"id": "IT.CEL.SETS.P2", "label": "Mobile cellular subscriptions (per 100 people)", "unit": "per 100", "category": "connectivity"},
    # Military
    {"id": "MS.MIL.XPND.GD.ZS", "label": "Military expenditure (% of GDP)", "unit": "%", "category": "military"},
    # Public finance (patchy coverage by nature — stated to the user)
    {"id": "GC.NLD.TOTL.GD.ZS", "label": "Government net lending/borrowing (% of GDP)", "unit": "%", "category": "public finance"},
    {"id": "GC.DOD.TOTL.GD.ZS", "label": "Central government debt (% of GDP)", "unit": "%", "category": "public finance"},
    {"id": "GC.TAX.TOTL.GD.ZS", "label": "Tax revenue (% of GDP)", "unit": "%", "category": "public finance"},
    {"id": "GC.REV.XGRT.GD.ZS", "label": "Revenue, excluding grants (% of GDP)", "unit": "%", "category": "public finance"},
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
