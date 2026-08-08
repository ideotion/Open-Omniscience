"""Statistical AGGREGATE codes — the non-country rows a statistics producer publishes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A World Bank response for ``country/all`` does not contain only countries. Roughly a
quarter of its rows are AGGREGATES — "High income", "Sub-Saharan Africa", "World" (78 of
295, live count 2026-08-07). ``XD`` reaching the Governments country dropdown as though
it were a nation is exactly this (field feedback 2026-08-07, item 8): the figures were
never cross-assigned, they were a real aggregate mislabelled as a country.

**An earlier version of this paragraph said aggregates carry an EMPTY ``countryiso3code``.
That is false**, and it was checked on 2026-08-07: an aggregate observation carries its
OWN alpha-3 there (``{"country":{"id":"ZH"},"countryiso3code":"AFE",...}``). Nothing in an
indicator response distinguishes a country from an aggregate at all — the only
discriminator lives in ``/v2/country``, in ``region.value == "Aggregates"``. Any ingest
that infers aggregate-ness from an empty code is classifying every aggregate as a country.
This app does not, and the reason is worth stating because it was luck of design rather
than knowledge: the guard below keys on ISO RECOGNITION, not on that field, so the false
premise never reached it. All 78 live aggregate codes were re-run through it and none
resolves to a country.

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

VERIFICATION STATUS: **read off a live response on 2026-08-07** —
``/v2/country?format=json&per_page=400``, ``page_meta.total`` 295, of which 78 carry
``region.value == "Aggregates"`` and 217 are real economies. The table is now the
complete set rather than the subset an offline pass could assert. What the earlier
documentation-only version got wrong is worth keeping, because each error was invisible:

* ``FCS`` / ``F1`` "Fragile and conflict affected situations" **does not exist** on this
  endpoint and has been removed. It was a fabricated row: plausible, well-known, and
  absent from the response. The four fragility aggregates that DO exist (``DSF`` ``FXS``
  ``DNS`` ``NXS``) are all IDA-restricted, which the old FCS was not, so none of them is
  a substitute for it.
* ``MEA`` / ``ZQ`` is no longer "Middle East & North Africa". It reads **"Middle East,
  North Africa, Afghanistan & Pakistan"**, and Afghanistan and Pakistan now carry
  ``region.id == "MEA"`` rather than ``SAS``. That is a country-set change wearing a
  rename: any series pairing a pre-change SAS or MEA figure with a post-change one is
  comparing different populations silently. The same rename propagates to ``MNA`` and to
  the derived ``BMN`` / ``DMN`` / ``TMN``. Malta is also in ``MEA``, not ``ECS``.
* The demographic-dividend codes are ``V1``..``V4`` in **stage** order (Pre, Early, Late,
  Post) — not alphabetical by alpha-3. Any mapping derived by sorting is wrong for all four.

THREE TRAPS the live response exposed, each of which fails silently:

* Namibia's ``iso2Code`` is the string ``"NA"``, and aggregates carry ``region.iso2code
  == "NA"`` as their sentinel. A YAML/JSON layer with default null handling turns Namibia
  into ``null``. Discriminate on ``region.value``, never on a bare ``NA``.
* Two names carry a **trailing space** inside the JSON (``"Latin America & Caribbean "``,
  ``"Sub-Saharan Africa "``). Anything keyed on name silently misses. This table stores
  them trimmed, which is safe only because nothing keys on the name.
* ``INX`` / ``XY`` "Not classified" is an aggregate here but is **not a place**. It is in
  the table so a code resolves to a label, and excluded from ``place_aggregates()`` so it
  never reaches a region picker.

CORRECTION to a claim this module previously made: the World Bank **does** publish a
continental-Africa aggregate, ``AFR`` / ``A9`` "Africa". The narrower statement is the
true one and is what matters for the lens: the seven *regions* still have no Africa,
because Sub-Saharan Africa excludes the five North African economies — so a region-lens
Africa figure does not exist even though an Africa aggregate does. ``AFR`` has NOT been
confirmed to carry data for any indicator; an aggregate can exist in the code list and
return no rows.
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
    "region",
    "income",
    "organisation",
    "lending",
    "small-states",
    "situation",
    "demographic",
    "unclassified",
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
    # --- the whole world -------------------------------------------------------------
    Aggregate("WLD", "1W", "World", "world", True),
    # --- regions -- the producer's OWN, and NOT continents (see the note above) ------
    # Africa is real and was missing entirely from the offline table -- but it is NOT on
    # the shortlist, because it has not been confirmed to carry data for any indicator.
    # Promoting an untested aggregate into the DEFAULT view risks an empty headline row,
    # and "the World Bank publishes no Africa figure" and "this one returns nothing" are
    # indistinguishable to a reader. Promote it once one fetch shows non-null values.
    Aggregate("AFR", "A9", "Africa", "region", False),
    Aggregate("EAS", "Z4", "East Asia & Pacific", "region", True),
    Aggregate("ECS", "Z7", "Europe & Central Asia", "region", True),
    Aggregate("LCN", "ZJ", "Latin America & Caribbean", "region", True),
    Aggregate("MEA", "ZQ", "Middle East, North Africa, Afghanistan & Pakistan", "region", True),
    Aggregate("NAC", "XU", "North America", "region", True),
    Aggregate("SAS", "8S", "South Asia", "region", True),
    Aggregate("SSF", "ZG", "Sub-Saharan Africa", "region", True),
    Aggregate("AFE", "ZH", "Africa Eastern and Southern", "region", False),
    Aggregate("AFW", "ZI", "Africa Western and Central", "region", False),
    Aggregate("NAF", "M2", "North Africa", "region", False),
    Aggregate("MDE", "M1", "Middle East (developing only)", "region", False),
    Aggregate("EAP", "4E", "East Asia & Pacific (excluding high income)", "region", False),
    Aggregate("ECA", "7E", "Europe & Central Asia (excluding high income)", "region", False),
    Aggregate("LAC", "XJ", "Latin America & Caribbean (excluding high income)", "region", False),
    Aggregate("MNA", "XQ", "Middle East, North Africa, Afghanistan & Pakistan (excluding high income)", "region", False),
    Aggregate("SSA", "ZF", "Sub-Saharan Africa (excluding high income)", "region", False),
    Aggregate("SXZ", "A4", "Sub-Saharan Africa excluding South Africa", "region", False),
    Aggregate("XZN", "A5", "Sub-Saharan Africa excluding South Africa and Nigeria", "region", False),
    Aggregate("NRS", "6X", "Non-resource rich Sub-Saharan Africa countries", "region", False),
    Aggregate("RRS", "R6", "Resource rich Sub-Saharan Africa countries", "region", False),
    # --- income groups ---------------------------------------------------------------
    Aggregate("HIC", "XD", "High income", "income", True),
    Aggregate("UMC", "XT", "Upper middle income", "income", True),
    Aggregate("LMC", "XN", "Lower middle income", "income", True),
    Aggregate("LIC", "XM", "Low income", "income", True),
    Aggregate("MIC", "XP", "Middle income", "income", False),
    Aggregate("LMY", "XO", "Low & middle income", "income", False),
    Aggregate("BHI", "B1", "IBRD countries classified as high income", "income", False),
    # --- organisations / unions ------------------------------------------------------
    Aggregate("EUU", "EU", "European Union", "organisation", True),
    Aggregate("EMU", "XC", "Euro area", "organisation", True),
    Aggregate("OED", "OE", "OECD members", "organisation", True),
    Aggregate("ARB", "1A", "Arab World", "organisation", True),
    Aggregate("CEB", "B8", "Central Europe and the Baltics", "organisation", False),
    # --- World Bank / IFC lending categories and their region cross-tabs -------------
    Aggregate("IDA", "XG", "IDA total", "lending", False),
    Aggregate("IDX", "XI", "IDA only", "lending", False),
    Aggregate("IDB", "XH", "IDA blend", "lending", False),
    Aggregate("IBD", "XF", "IBRD only", "lending", False),
    Aggregate("IBB", "ZB", "IBRD, including blend", "lending", False),
    Aggregate("IBT", "ZT", "IDA & IBRD total", "lending", False),
    Aggregate("BEA", "B4", "East Asia & Pacific (IBRD-only countries)", "lending", False),
    Aggregate("BEC", "B7", "Europe & Central Asia (IBRD-only countries)", "lending", False),
    Aggregate("BLA", "B2", "Latin America & the Caribbean (IBRD-only countries)", "lending", False),
    Aggregate("BMN", "B3", "Middle East, North Africa, Afghanistan & Pakistan (IBRD only)", "lending", False),
    Aggregate("BSS", "B6", "Sub-Saharan Africa (IBRD-only countries)", "lending", False),
    Aggregate("DEA", "D4", "East Asia & Pacific (IDA-eligible countries)", "lending", False),
    Aggregate("DEC", "D7", "Europe & Central Asia (IDA-eligible countries)", "lending", False),
    Aggregate("DLA", "D2", "Latin America & the Caribbean (IDA-eligible countries)", "lending", False),
    Aggregate("DMN", "D3", "Middle East, North Africa, Afghanistan & Pakistan (IDA total)", "lending", False),
    Aggregate("DSA", "D5", "South Asia (IDA-eligible countries)", "lending", False),
    Aggregate("DSS", "D6", "Sub-Saharan Africa (IDA-eligible countries)", "lending", False),
    Aggregate("TEA", "T4", "East Asia & Pacific (IDA & IBRD countries)", "lending", False),
    Aggregate("TEC", "T7", "Europe & Central Asia (IDA & IBRD countries)", "lending", False),
    Aggregate("TLA", "T2", "Latin America & the Caribbean (IDA & IBRD countries)", "lending", False),
    Aggregate("TMN", "T3", "Middle East, North Africa, Afghanistan & Pakistan (IDA & IBRD)", "lending", False),
    Aggregate("TSA", "T5", "South Asia (IDA & IBRD)", "lending", False),
    Aggregate("TSS", "T6", "Sub-Saharan Africa (IDA & IBRD countries)", "lending", False),
    Aggregate("CAA", "C9", "Sub-Saharan Africa (IFC classification)", "lending", False),
    Aggregate("CEA", "C4", "East Asia and the Pacific (IFC classification)", "lending", False),
    Aggregate("CEU", "C5", "Europe and Central Asia (IFC classification)", "lending", False),
    Aggregate("CLA", "C6", "Latin America and the Caribbean (IFC classification)", "lending", False),
    Aggregate("CME", "C7", "Middle East and North Africa (IFC classification)", "lending", False),
    Aggregate("CSA", "C8", "South Asia (IFC classification)", "lending", False),
    # --- small states ----------------------------------------------------------------
    Aggregate("SST", "S1", "Small states", "small-states", False),
    Aggregate("PSS", "S2", "Pacific island small states", "small-states", False),
    Aggregate("CSS", "S3", "Caribbean small states", "small-states", False),
    Aggregate("OSS", "S4", "Other small states", "small-states", False),
    # --- debt, development status and fragility --------------------------------------
    Aggregate("HPC", "XE", "Heavily indebted poor countries (HIPC)", "situation", False),
    Aggregate("LDC", "XL", "Least developed countries: UN classification", "situation", False),
    Aggregate("DSF", "F6", "IDA countries in Sub-Saharan Africa classified as fragile situations", "situation", False),
    Aggregate("FXS", "6F", "IDA countries classified as fragile situations, excluding Sub-Saharan Africa", "situation", False),
    Aggregate("DNS", "N6", "IDA countries in Sub-Saharan Africa not classified as fragile situations", "situation", False),
    Aggregate("NXS", "6N", "IDA countries not classified as fragile situations, excluding Sub-Saharan Africa", "situation", False),
    # --- demographic-dividend stages -- V1..V4 run in STAGE order, not alphabetically ---
    Aggregate("PRE", "V1", "Pre-demographic dividend", "demographic", False),
    Aggregate("EAR", "V2", "Early-demographic dividend", "demographic", False),
    Aggregate("LTE", "V3", "Late-demographic dividend", "demographic", False),
    Aggregate("PST", "V4", "Post-demographic dividend", "demographic", False),
    # --- not a place -----------------------------------------------------------------
    Aggregate("INX", "XY", "Not classified", "unclassified", False),
)


#: Groups whose members are not PLACES. Kept in the table so a code still resolves to a
#: label, and filtered out of anything that offers the user a region to look at.
NON_PLACE_GROUPS: frozenset[str] = frozenset({"unclassified"})


def aggregate_entries() -> tuple[Aggregate, ...]:
    """Every published aggregate, in table order (grouped, not ranked)."""
    return _AGGREGATES


def place_aggregates() -> tuple[Aggregate, ...]:
    """The aggregates that denote somewhere — what a region picker may offer.

    Excludes ``INX`` "Not classified", which is a residual bucket for economies the Bank
    has not assigned. Shipping the aggregate list wholesale puts it in a dropdown beside
    "World" and "Europe & Central Asia", where it reads as a place.
    """
    return tuple(a for a in _AGGREGATES if a.group not in NON_PLACE_GROUPS)


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
