"""Statistical aggregates vs countries (field feedback 2026-08-07, item 8 / slice A2).

``XD`` — the World Bank's "High income" aggregate — reached the Governments country
dropdown as though it were a nation. The figures behind it were never cross-assigned;
a real aggregate was mislabelled.

The brief's mandated skeptic lens here is THE FABRICATED-GAP TWIN: the over-eager version
of this fix silently deletes countries and looks conservative while doing it. So every
exclusion below is paired with an inclusion, and the country side is tested against the
awkward cases (recent territories, Kosovo) rather than against France.
"""

from __future__ import annotations

import pytest

from src.catalog.aggregates import (
    place_aggregates,
    GROUPS,
    aggregate_entries,
    aggregate_name,
    aggregate_of,
    is_statistical_aggregate,
)
from src.catalog.countries import classify_ref_area, to_iso2, to_iso3

# Codes the field investigation actually saw. This is a RECORD of what was observed, not
# the coverage claim: the complete live set of 78 is checked by
# test_every_live_aggregate_code_is_refused_by_the_country_guard below.
AGGREGATE_CODES_2 = ["XD", "XC", "XT", "XM", "XN", "XO", "XP", "EU", "OE", "1W",
                     "Z4", "Z7", "ZG", "ZJ", "ZQ", "8S", "B8", "S1", "S2", "S3", "S4"]
AGGREGATE_CODES_3 = ["HIC", "EMU", "UMC", "LIC", "LMC", "LMY", "MIC", "EUU", "OED",
                     "WLD", "EAS", "ECS", "SSF", "LCN", "MEA", "SAS", "CEB"]

# NOT aggregates. `FCS`/`F1` are absent from /v2/country -- see
# test_the_fabricated_FCS_row_stays_gone. They are still guarded, because whatever they
# are they must never resolve as a country, but they are kept OUT of the lists above:
# a code sitting in a list named AGGREGATE_CODES_* reads as evidence that the World Bank
# publishes it, which is the exact belief that put the fabricated row in the table.
RETIRED_CODES_STILL_NEVER_COUNTRIES = ["F1", "FCS"]


# --------------------------------------------------------------------------- #
# Aggregates are excluded from country surfaces
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code", AGGREGATE_CODES_2)
def test_two_letter_aggregate_codes_are_not_countries(code):
    assert to_iso2(code) is None, f"{code} is a World Bank aggregate, not a nation"
    assert to_iso3(code) is None


@pytest.mark.parametrize("code", AGGREGATE_CODES_3)
def test_three_letter_aggregate_codes_are_not_countries(code):
    assert to_iso2(code) is None
    assert to_iso3(code) is None, f"{code} echoed straight through before this fix"


@pytest.mark.parametrize("code", RETIRED_CODES_STILL_NEVER_COUNTRIES)
def test_a_code_we_once_wrongly_shipped_still_never_resolves_as_a_country(code):
    """Same protection, without the claim that the code is published anywhere."""
    assert to_iso2(code) is None
    assert to_iso3(code) is None


def test_the_field_specimen_is_excluded():
    """The exact code from the maintainer's PDF."""
    assert to_iso2("XD") is None
    assert classify_ref_area("XD") == "aggregate"
    assert aggregate_name("XD") == "High income"


# --------------------------------------------------------------------------- #
# The twin: real countries must still pass
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "iso3,iso2",
    [
        ("FRA", "fr"), ("USA", "us"), ("CHN", "cn"), ("ZAF", "za"),
        # The awkward ones. Every territory the World Bank reports separately must
        # survive, or this fix trades a fabricated country for a deleted one.
        ("CUW", "cw"),   # Curacao
        ("SXM", "sx"),   # Sint Maarten
        ("SSD", "ss"),   # South Sudan
        ("XKX", "xk"),   # Kosovo — user-assigned, not in ISO 3166-1
    ],
)
def test_real_countries_and_territories_still_resolve(iso3, iso2):
    assert to_iso2(iso3) == iso2
    assert classify_ref_area(iso3) == "country"


@pytest.mark.parametrize("code", ["fr", "us", "cw", "sx", "ss", "xk", "bq", "mf"])
def test_alpha_two_countries_pass_through(code):
    assert to_iso2(code) == code
    assert classify_ref_area(code) == "country"


def test_round_trip_still_holds():
    assert to_iso2("FRA") == "fr" and to_iso3("fr") == "FRA"
    assert to_iso2("us") == "us" and to_iso3("USA") == "USA"


def test_no_curated_aggregate_shadows_a_real_country():
    """A registry typo that collided with an ISO code would delete that country.

    The structural guard cannot catch this — the aggregate table is consulted FIRST, so a
    bad row here wins. `eu` is the deliberate exception and is asserted by name.
    """
    from src.catalog.countries import ISO_3166_1_ALPHA2

    for entry in aggregate_entries():
        if entry.iso2:
            code = entry.iso2.lower()
            assert code not in ISO_3166_1_ALPHA2, (
                f"{entry.iso3}/{entry.iso2} collides with the ISO country {code}"
            )
    assert to_iso2("EU") is None, "EU is a special code AND a WB aggregate; here it is the aggregate"


# --------------------------------------------------------------------------- #
# The third state
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code", ["ZZ", "QQQ", "9Q", "", "  ", None, "not-a-code"])
def test_unrecognised_codes_are_unknown_not_countries(code):
    """'We do not recognise this' is its own answer.

    Collapsing it into "country" puts junk on a map; collapsing it into "aggregate"
    invents a classification.

    This case used to be parametrised on `4E`, chosen because it was a real aggregate
    the offline table could not verify. The 2026-08-07 live fetch resolved it (EAP,
    "East Asia & Pacific (excluding high income)"), so it is now a recognised aggregate
    and no longer an example of anything. `9Q` replaces it: absent from all 78 rows of
    the response, and therefore genuinely unrecognised.
    """
    assert classify_ref_area(code) == "unknown"
    assert to_iso2(code) is None


def test_an_unlisted_aggregate_still_never_pollutes_country_surfaces():
    """The load-bearing property: the guard is structural, not the table.

    An aggregate invented tomorrow, absent from the table, must still be excluded from
    countries — otherwise the fix decays the moment the World Bank publishes a new one.
    """
    assert not is_statistical_aggregate("V9")
    assert to_iso2("V9") is None
    assert aggregate_name("V9") is None


# --------------------------------------------------------------------------- #
# The table itself
# --------------------------------------------------------------------------- #


def test_the_table_is_internally_consistent():
    seen_iso3: set[str] = set()
    seen_iso2: set[str] = set()
    for entry in aggregate_entries():
        assert entry.iso3.isupper() and len(entry.iso3) == 3, entry
        assert entry.iso3 not in seen_iso3, f"duplicate iso3 {entry.iso3}"
        seen_iso3.add(entry.iso3)
        if entry.iso2:
            assert entry.iso2.isupper() and len(entry.iso2) == 2, entry
            assert entry.iso2 not in seen_iso2, f"duplicate iso2 {entry.iso2}"
            seen_iso2.add(entry.iso2)
        assert entry.name.strip(), f"{entry.iso3} needs a display name"
        assert entry.group in GROUPS, f"{entry.iso3} has an unknown group {entry.group!r}"


def test_the_shortlist_is_the_ruled_one():
    """Ruling 32: World, the four income groups, the seven WB regions, EU, Euro area,
    OECD, Arab World — with everything else behind 'show all'."""
    short = {e.iso3 for e in aggregate_entries() if e.shortlist}
    assert short == {
        "WLD",
        "HIC", "UMC", "LMC", "LIC",
        "EAS", "ECS", "LCN", "MEA", "NAC", "SAS", "SSF",
        "EUU", "EMU", "OED", "ARB",
    }
    assert len([e for e in aggregate_entries() if not e.shortlist]) > 0, "'show all' needs a tail"


def test_lookup_accepts_either_code_form_and_any_case():
    for probe in ("HIC", "hic", "XD", "xd", " xd "):
        entry = aggregate_of(probe)
        assert entry is not None and entry.iso3 == "HIC", probe


def test_no_score_shaped_field_on_an_aggregate():
    """The no-composite-score convention reaches new payload shapes too."""
    banned = ("score", "rank", "rating", "grade", "quality")
    for entry in aggregate_entries():
        for field in entry.__dataclass_fields__:
            assert not any(b in field.lower() for b in banned), field


# --------------------------------------------------------------------------- #
# Verified against the live response, 2026-08-07
# --------------------------------------------------------------------------- #


def test_the_table_is_the_complete_live_set():
    """78 aggregates, read off /v2/country on 2026-08-07 (295 total, 217 economies).

    Pinned as a COUNT so a future partial edit is visible: the previous table held 31
    rows asserted from documentation, and its gaps were invisible precisely because a
    missing aggregate degrades quietly to a raw code.
    """
    assert len(aggregate_entries()) == 78


def test_the_fabricated_FCS_row_stays_gone():
    """`FCS` / `F1` "Fragile and conflict affected situations" is not on this endpoint.

    It shipped once: plausible, widely cited, and absent from the response. The four
    fragility aggregates that DO exist are all IDA-restricted, which FCS was not, so none
    is a substitute — this guards against someone "restoring" it from memory.
    """
    assert aggregate_of("FCS") is None
    assert aggregate_of("F1") is None
    for real in ("DSF", "FXS", "DNS", "NXS"):
        assert aggregate_of(real) is not None, real


def test_the_MEA_rename_is_carried_because_it_changed_the_country_set():
    """Not cosmetic: Afghanistan and Pakistan moved SAS -> MEA, so the old name labels a
    different population than the code now returns."""
    mea = aggregate_of("MEA")
    assert mea.name == "Middle East, North Africa, Afghanistan & Pakistan"
    assert "Afghanistan" in mea.name and "Pakistan" in mea.name


def test_the_demographic_dividend_codes_run_in_stage_order_not_alphabetically():
    """V1..V4 are Pre, Early, Late, Post. Sorting the alpha-3s (EAR, LTE, PRE, PST) and
    zipping against V1..V4 gets all four wrong, which is how they were omitted before."""
    assert [aggregate_of(c).iso2 for c in ("PRE", "EAR", "LTE", "PST")] == ["V1", "V2", "V3", "V4"]


def test_not_classified_is_in_the_table_but_is_not_a_place():
    """`INX` resolves to a label so a code is never orphaned, and is kept out of anything
    that offers the user somewhere to look at."""
    assert aggregate_of("INX") is not None
    assert "INX" not in {a.iso3 for a in place_aggregates()}
    assert len(place_aggregates()) == len(aggregate_entries()) - 1


def test_no_stored_name_carries_the_APIs_trailing_whitespace():
    """Two names come back with a trailing space. Storing them trimmed is safe only
    because nothing keys on the name; this pins the trim so a re-import cannot leak it."""
    for entry in aggregate_entries():
        assert entry.name == entry.name.strip(), repr(entry.name)


def test_every_live_aggregate_code_is_refused_by_the_country_guard():
    """The load-bearing property, now checked against the REAL set rather than a sample.

    This is the guard that made the false `countryiso3code` premise harmless, so it is
    worth re-proving over all 78 rather than over the handful an offline pass could name.
    """
    for entry in aggregate_entries():
        assert to_iso2(entry.iso3) is None, f"{entry.iso3} resolves as a country"
        if entry.iso3 != "EUU":  # EU is a real project special code; the table wins
            assert to_iso2(entry.iso2) is None, f"{entry.iso2} resolves as a country"
