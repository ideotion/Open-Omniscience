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

AGGREGATION METADATA (2026-08-07, ruling 47's design rail). Three fields decide what a
bloc- or continent-level figure may honestly do with a series, and all three are
DECLARED here rather than inferred from ``unit``. A string heuristic on the unit reads
fine today and breaks silently the day someone adds a unit spelling — and its failure
mode is a published statistic that was never computable:

``extensive``
    May the members' values be SUMMED? True only where the quantity is a count of
    something the members hold separately (population, GDP, GDP-PPP, labour force).
    Summing an intensive value — any %, rate, ratio, index or per-capita figure — is a
    fabricated statistic, so the engine REFUSES it rather than offering it greyed out.

``denominator``
    What the value is *per*. This is what makes a weighted mean EXACT rather than
    approximate: for a per-capita series, ``Σ(value × population) / Σ(population)`` is
    algebraically the true aggregate, because the reconstructed numerator is the real
    numerator. Weight by anything else and the answer is an approximation, which the
    engine says out loud. ``None`` means the denominator is not one we hold a series
    for (live births, land area, the school-age population), so every weighted mean
    over it is approximate by construction.

``no_aggregate``
    A stated reason why NO cross-area figure is honest. Only the Gini index carries
    one: the inequality of a merged population is not any average of its parts'
    inequalities — pooling adds the between-country spread, which a mean of Ginis
    discards entirely, so the figure is not merely imprecise but biased low in a
    direction a reader cannot see. Refusing beats publishing it with a caveat.
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
    {"id": "SE.SEC.ENRR", "label": "School enrollment, secondary (% gross)", "unit": "%", "category": "education",
     "note": "GROSS enrollment counts every enrolled pupil against the official school-age "
             "population, so repeaters and over-age pupils are included and the figure can "
             "legitimately exceed 100%. It is not an error and not a share of children."},
    # Energy & environment
    {"id": "EG.ELC.ACCS.ZS", "label": "Access to electricity (% of population)", "unit": "%", "category": "energy & environment"},
    {"id": "EG.FEC.RNEW.ZS", "label": "Renewable energy consumption (% of total final energy consumption)", "unit": "%", "category": "energy & environment"},
    # ⚠ AT RISK, and deliberately NOT swapped (2026-08-13 internet session, SEARCH-ONLY).
    # The Bank now publishes a separate per-capita CO2 series — "Carbon dioxide (CO2)
    # emissions excluding LULUCF per capita (t CO2e/capita)", EN.GHG.CO2.PC.CE.AR5, sourced
    # from EDGAR (JRC) and the IEA — while this code's metadata glossary entry still
    # describes the older CDIAC-to-1990-then-CAIT construction. The code still RESOLVES, so
    # this is not a clean 404; it is the "returns rows but the series is frozen" case, which
    # reads exactly like a country that stopped reporting. Two similar identifiers where one
    # is stale is precisely where a swap is worse than a gap, so the fix is to FETCH BOTH and
    # compare the returned series before changing anything here.
    {"id": "EN.ATM.CO2E.PC", "label": "CO2 emissions (metric tons per capita)", "unit": "t/capita", "category": "energy & environment"},
    {"id": "AG.LND.FRST.ZS", "label": "Forest area (% of land area)", "unit": "%", "category": "energy & environment"},
    # Connectivity
    {"id": "IT.NET.USER.ZS", "label": "Individuals using the Internet (% of population)", "unit": "%", "category": "connectivity"},
    {"id": "IT.CEL.SETS.P2", "label": "Mobile cellular subscriptions (per 100 people)", "unit": "per 100", "category": "connectivity",
     "note": "Counts SUBSCRIPTIONS, not people. One person with a work and a personal SIM is "
             "two, so a value above 100 is normal in high-income economies and does not mean "
             "more than one phone per inhabitant."},
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

# The three weight series we actually hold, so a `denominator` naming one of them makes
# the corresponding weighted mean EXACT rather than approximate. Any other denominator
# (live births, land area, the school-age population, a price basket) is written as None:
# we cannot reconstruct that numerator, so every weighted mean over it is approximate and
# the engine says so.
WEIGHT_SERIES: dict[str, str] = {
    "population": "SP.POP.TOTL",
    "gdp": "NY.GDP.MKTP.CD",
    "labour_force": "SL.TLF.TOTL.IN",
}

_GINI_NO_AGGREGATE = (
    "The Gini index of a merged population is not an average of its parts' Gini "
    "indices. Pooling countries adds the inequality BETWEEN them, which any mean over "
    "per-country values discards, so a bloc figure computed that way is biased low by "
    "an amount the reader cannot see or bound. The honest bloc Gini needs the pooled "
    "micro-data, which this app does not hold."
)

#: id -> (extensive, denominator, no_aggregate). Declared, never inferred from `unit`.
#: `indicator_aggregation` RAISES for an id that is missing here, so adding an indicator
#: without deciding this is loud at runtime and not only in the test.
AGGREGATION: dict[str, tuple[bool, str | None, str | None]] = {
    # Economy — the levels are the summable ones.
    "NY.GDP.MKTP.CD": (True, None, None),
    "NY.GDP.PCAP.CD": (False, "population", None),
    # A growth RATE's true aggregate needs PRIOR-year GDP as the weight; we hold the
    # current level only, so weighting by it is an approximation, not the identity.
    "NY.GDP.MKTP.KD.ZG": (False, None, None),
    "NY.GDP.MKTP.PP.CD": (True, None, None),
    "NY.GDP.PCAP.PP.CD": (False, "population", None),
    "NE.TRD.GNFS.ZS": (False, "gdp", None),
    "BX.KLT.DINV.WD.GD.ZS": (False, "gdp", None),
    # Prices — no denominator series reconstructs a consumer price basket.
    "FP.CPI.TOTL.ZG": (False, None, None),
    # Demography
    "SP.POP.TOTL": (True, None, None),
    "SP.POP.GROW": (False, None, None),  # prior-year population, same as GDP growth
    "SP.URB.TOTL.IN.ZS": (False, "population", None),
    "SP.DYN.TFRT.IN": (False, None, None),  # per woman of childbearing age
    # Health
    # Life expectancy is a life-table construct, not a per-person average, so a
    # population-weighted mean is the conventional approximation and NOT an identity.
    "SP.DYN.LE00.IN": (False, None, None),
    "SH.DYN.MORT": (False, None, None),  # per live birth
    "SH.STA.MMRT": (False, None, None),  # per live birth
    "SH.MED.PHYS.ZS": (False, "population", None),
    "SH.XPD.CHEX.GD.ZS": (False, "gdp", None),
    # Labour — unemployment is per LABOUR FORCE, and we hold that series, so its
    # labour-force-weighted mean is exact where a population-weighted one would not be.
    "SL.UEM.TOTL.ZS": (False, "labour_force", None),
    "SL.TLF.TOTL.IN": (True, None, None),
    "SL.TLF.CACT.ZS": (False, None, None),  # per population 15+, not total population
    # Education
    "SE.ADT.LITR.ZS": (False, None, None),  # per population 15+
    "SE.XPD.TOTL.GD.ZS": (False, "gdp", None),
    "SE.PRM.ENRR": (False, None, None),  # per official school-age population
    "SE.SEC.ENRR": (False, None, None),
    # Energy & environment
    "EG.ELC.ACCS.ZS": (False, "population", None),
    "EG.FEC.RNEW.ZS": (False, None, None),  # per total final energy consumption
    "EN.ATM.CO2E.PC": (False, "population", None),
    "AG.LND.FRST.ZS": (False, None, None),  # per land area
    # Connectivity
    "IT.NET.USER.ZS": (False, "population", None),
    "IT.CEL.SETS.P2": (False, "population", None),
    # Military
    "MS.MIL.XPND.GD.ZS": (False, "gdp", None),
    # Public finance
    "GC.NLD.TOTL.GD.ZS": (False, "gdp", None),
    "GC.DOD.TOTL.GD.ZS": (False, "gdp", None),
    "GC.TAX.TOTL.GD.ZS": (False, "gdp", None),
    "GC.REV.XGRT.GD.ZS": (False, "gdp", None),
    # Inequality — the one series no cross-country aggregate can honestly produce.
    "SI.POV.GINI": (False, None, _GINI_NO_AGGREGATE),
}

_BY_ID = {ind["id"]: ind for ind in INDICATOR_CATALOG}


def indicator_ids() -> list[str]:
    """The curated World Bank series codes, in catalog order."""
    return [ind["id"] for ind in INDICATOR_CATALOG]


def indicator_meta(code: str) -> dict | None:
    """The {id,label,unit,category} for one code, or None if it is not curated."""
    return _BY_ID.get((code or "").strip())


def is_curated(code: str) -> bool:
    return (code or "").strip() in _BY_ID


def indicator_aggregation(code: str) -> dict:
    """How this series may be aggregated across areas — see the module docstring.

    Raises ``KeyError`` for a curated code with no declaration. That is deliberate: a
    silent default would decide, for whatever someone forgot to think about, either that
    a percentage may be summed or that a real total may not be — and both of those reach
    a reader as a published figure.
    """
    key = (code or "").strip()
    try:
        extensive, denominator, no_aggregate = AGGREGATION[key]
    except KeyError:
        raise KeyError(
            f"{key!r} has no aggregation declaration in src/stats/indicators.AGGREGATION. "
            "Decide extensive / denominator / no_aggregate for it rather than defaulting."
        ) from None
    return {
        "extensive": extensive,
        "denominator": denominator,
        "no_aggregate": no_aggregate,
        # The series whose values weight this indicator EXACTLY, when we hold one.
        "weight_series": WEIGHT_SERIES.get(denominator) if denominator else None,
    }
