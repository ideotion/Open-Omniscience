"""Statistical AGGREGATE codes — the non-country rows a statistics producer publishes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A World Bank response for ``country/all`` does not contain only countries. Roughly a
fifth of its rows are AGGREGATES — "High income", "Sub-Saharan Africa", "World" — which
carry an empty ``countryiso3code`` and so fall back to a 2-letter code in ``ref_area``.
``XD`` reaching the Governments country dropdown as though it were a nation is exactly
this (field feedback 2026-08-07, item 8): the figures were never cross-assigned, they
were a real aggregate mislabelled as a country.

WHAT GUARDS WHAT — read this before extending the table below.

The CLASSIFICATION guard is STRUCTURAL and does not live here: ``countries.to_iso2``
admits a 2-letter code only when it is a recognised ISO-3166 country (or one of the
project's four special codes). Measured against the shipped alpha-2 set: every real
territory the World Bank reports separately — ``cw`` ``sx`` ``mf`` ``bq`` ``ss`` — is an
ISO country, and every aggregate code — ``xd`` ``xc`` ``z4`` ``1w`` ``b8`` ``f1`` ``s1``
``oe`` ``8s`` … — is not. So an aggregate the World Bank invents TOMORROW is excluded
from country surfaces automatically, with no edit here.

This table is therefore DISPLAY METADATA, not the guard. Its only job is to turn a code
into a name and to populate the aggregate view. An aggregate missing from it still never
pollutes a country surface; it simply shows as its raw code, labelled unrecognised. That
asymmetry is deliberate and it decides how to extend the table: **omit an entry you are
unsure of.** A missing row degrades honestly; a wrong name is a fabrication.

The one exception the structural guard cannot make on its own is ``EU``, which is both a
legitimate project special code (EUR-Lex, EPO) and a World Bank aggregate. In a
statistics ``ref_area`` it is the aggregate, so it is listed here and the guard defers to
this table first.

VERIFICATION STATUS (honest, and load-bearing): api.worldbank.org is egress-blocked from
this sandbox, so these codes are stated from documentation knowledge, NOT read off a live
response. Entries whose alpha-2 could not be asserted with confidence carry ``iso2=None``
rather than a guess, and several aggregates the World Bank publishes are deliberately
ABSENT for the same reason (the demographic-dividend and least-developed groupings, whose
alpha-2 codes could not be told apart from the IDA/IBRD lending block's with confidence).
Verifying the full list against ``/v2/country?format=json`` — where ``region.value ==
"Aggregates"`` marks them — is on the operator to-do list.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

# When this table of CODES was last curated. Registered in configs/external_artifacts.yml
# (id: worldbank-aggregate-codes) because the vocabulary is the World Bank's, not ours.
WB_AGGREGATES_AS_OF = "2026-08"

# Grouping drives the aggregate view's sections. Not a ranking — a vocabulary.
GROUPS: tuple[str, ...] = (
    "world",
    "income",
    "region",
    "organisation",
    "lending",
    "small-states",
    "situation",
)


@dataclass(frozen=True)
class Aggregate:
    """One published aggregate. ``iso2`` is None where the alpha-2 form is unverified."""

    iso3: str
    iso2: str | None
    name: str
    group: str
    shortlist: bool


# The curated table. `shortlist=True` marks the default view (ruling 32: a curated
# shortlist, with "show all" behind one control) — World, the four income groups, the
# seven World Bank regions, plus EU, Euro area, OECD and the Arab World.
_AGGREGATES: tuple[Aggregate, ...] = (
    # --- the whole world ----------------------------------------------------------
    Aggregate("WLD", "1W", "World", "world", True),
    # --- income groups ------------------------------------------------------------
    Aggregate("HIC", "XD", "High income", "income", True),
    Aggregate("UMC", "XT", "Upper middle income", "income", True),
    Aggregate("LMC", "XN", "Lower middle income", "income", True),
    Aggregate("LIC", "XM", "Low income", "income", True),
    Aggregate("MIC", "XP", "Middle income", "income", False),
    Aggregate("LMY", "XO", "Low & middle income", "income", False),
    # --- the seven World Bank regions ---------------------------------------------
    # NOTE these are the producer's OWN regions and are NOT continents. "Sub-Saharan
    # Africa" excludes Egypt, Libya, Tunisia, Algeria and Morocco, which sit in "Middle
    # East & North Africa" — so this lens has no continental-Africa figure at all. That
    # is why the Governments tab offers continents as a second, separately-labelled lens.
    Aggregate("EAS", "Z4", "East Asia & Pacific", "region", True),
    Aggregate("ECS", "Z7", "Europe & Central Asia", "region", True),
    Aggregate("LCN", "ZJ", "Latin America & Caribbean", "region", True),
    Aggregate("MEA", "ZQ", "Middle East & North Africa", "region", True),
    Aggregate("NAC", "XU", "North America", "region", True),
    Aggregate("SAS", "8S", "South Asia", "region", True),
    Aggregate("SSF", "ZG", "Sub-Saharan Africa", "region", True),
    Aggregate("AFE", "ZH", "Africa Eastern and Southern", "region", False),
    Aggregate("AFW", "ZI", "Africa Western and Central", "region", False),
    # --- organisations / unions ---------------------------------------------------
    Aggregate("EUU", "EU", "European Union", "organisation", True),
    Aggregate("EMU", "XC", "Euro area", "organisation", True),
    Aggregate("OED", "OE", "OECD members", "organisation", True),
    Aggregate("ARB", "1A", "Arab World", "organisation", True),
    Aggregate("CEB", "B8", "Central Europe and the Baltics", "organisation", False),
    # --- World Bank lending categories --------------------------------------------
    Aggregate("IDA", "XG", "IDA total", "lending", False),
    Aggregate("IDX", "XI", "IDA only", "lending", False),
    Aggregate("IDB", "XH", "IDA blend", "lending", False),
    Aggregate("IBD", "XF", "IBRD only", "lending", False),
    Aggregate("HPC", "XE", "Heavily indebted poor countries (HIPC)", "lending", False),
    # --- small states -------------------------------------------------------------
    Aggregate("SST", "S1", "Small states", "small-states", False),
    Aggregate("PSS", "S2", "Pacific island small states", "small-states", False),
    Aggregate("CSS", "S3", "Caribbean small states", "small-states", False),
    Aggregate("OSS", "S4", "Other small states", "small-states", False),
    # --- situations ---------------------------------------------------------------
    Aggregate("FCS", "F1", "Fragile and conflict affected situations", "situation", False),
)


def aggregate_entries() -> tuple[Aggregate, ...]:
    """Every curated aggregate, in table order (grouped, not ranked)."""
    return _AGGREGATES


@lru_cache(maxsize=1)
def _by_code() -> dict[str, Aggregate]:
    """Lowercased alpha-2 AND alpha-3 -> entry. Built once."""
    index: dict[str, Aggregate] = {}
    for entry in _AGGREGATES:
        index[entry.iso3.lower()] = entry
        if entry.iso2:
            index[entry.iso2.lower()] = entry
    return index


def is_statistical_aggregate(code: str | None) -> bool:
    """True when ``code`` is a KNOWN published aggregate rather than a country.

    False for an unknown code — which is not the same claim as "this is a country".
    Use :func:`src.catalog.countries.classify_ref_area` when the three-way distinction
    matters, because conflating "we do not recognise this" with "this is a country" is
    how a junk code becomes a nation on a map.
    """
    return (code or "").strip().lower() in _by_code()


def aggregate_name(code: str | None) -> str | None:
    """Display name for a known aggregate; ``None`` when it is not one of ours."""
    entry = _by_code().get((code or "").strip().lower())
    return entry.name if entry else None


def aggregate_of(code: str | None) -> Aggregate | None:
    """The full entry for a known aggregate, or ``None``."""
    return _by_code().get((code or "").strip().lower())
