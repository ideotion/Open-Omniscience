"""
Tests for the country conversion layer + the de-US-centring guards (0.09 KEY POINT).

One conversion layer (src/catalog/countries.py): lowercase ISO-2 in storage, full
names at display. These tests pin the contract, the shipped catalogs' canonical
form (so mixed encodings can never creep back in), the regional balance report,
and the data-migration value plan.
"""

import importlib.util
import sys
from pathlib import Path

from src.catalog.countries import (
    CONTINENT_OF,
    COUNTRY_NAMES,
    ISO_3166_1_ALPHA2,
    continent_of,
    country_display_name,
    normalize_country,
)
from src.catalog.coverage import coverage_report, regional_report

_ROOT = Path(__file__).resolve().parents[1]


# --- the conversion contract ------------------------------------------------- #


def test_normalize_accepts_codes_names_slugs_and_shorthand():
    # any-case codes
    assert normalize_country("us") == "us"
    assert normalize_country("US") == "us"
    assert normalize_country(" Fr ") == "fr"
    # full names + catalog slugs
    assert normalize_country("United States") == "us"
    assert normalize_country("united-states") == "us"
    assert normalize_country("bosnia-and-herzegovina") == "ba"
    assert normalize_country("côte d'ivoire") == "ci"
    assert normalize_country("ivory-coast") == "ci"
    # common shorthand + renamed countries
    assert normalize_country("UK") == "gb"
    assert normalize_country("USA") == "us"
    assert normalize_country("turkey") == "tr"  # ISO name is Türkiye
    assert normalize_country("czechia") == "cz"
    assert normalize_country("burma") == "mm"
    # specials the catalogs legitimately use
    assert normalize_country("EU") == "eu"
    assert normalize_country("INT") == "int"
    assert normalize_country("kosovo") == "xk"
    # never guesses
    assert normalize_country("junkvalue") is None
    assert normalize_country("") is None
    assert normalize_country(None) is None


def test_display_names_prefer_common_forms_and_degrade_loudly():
    assert country_display_name("us") == "United States"
    assert country_display_name("RU") == "Russia"  # not "Russian Federation"
    assert country_display_name("kp") == "North Korea"
    assert country_display_name("eu") == "European Union"
    # unrecognised values come back AS-IS (visible, never masked)
    assert country_display_name("zz-legacy") == "zz-legacy"
    assert country_display_name(None) is None


def test_reference_data_is_complete():
    # every officially-assigned code has a display name and a continent
    assert set(COUNTRY_NAMES) == set(ISO_3166_1_ALPHA2)
    assert set(CONTINENT_OF) >= ISO_3166_1_ALPHA2
    assert continent_of("fr") == "Europe"
    assert continent_of("Brazil") == "South America"
    assert continent_of("eu") is None  # supranational: no continent claimed


# --- the shipped catalogs stay canonical (regression guard) ------------------ #


def test_shipped_catalogs_use_canonical_country_codes():
    """Every country value in the source catalogs is exactly the canonical form.

    This is the guard against the 0.0.8 live-test finding (mixed 'US' /
    'united-states' encodings): a new catalog entry with a name, slug or
    uppercase code fails here with a precise message.
    """
    import yaml

    offenders = []
    for fname in (
        "sources.yml",
        "markets_sources.yml",
        "sources_spectrum.yml",
        "legal_sources.yml",
        "world_news_sources.yml",  # generator output, present only after a build
    ):
        path = _ROOT / "configs" / fname
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in ("sources", "documents"):
            for entry in data.get(key) or []:
                c = entry.get("country")
                if c is None:
                    continue
                if not isinstance(c, str) or normalize_country(c) != c:
                    offenders.append(f"{fname}: {entry.get('name')!r} country={c!r}")
    assert not offenders, (
        "non-canonical country values (store lowercase ISO-2; "
        f"see src/catalog/countries.py): {offenders[:10]}"
    )


# --- regional balance report (the acceptance metric) ------------------------- #


def test_regional_report_arithmetic_and_targets():
    counts = {"fr": 3, "de": 2, "ng": 1, "br": 4, "eu": 2, "zz": 9}
    targets = {
        "regions": {"Europe": {"min_sources": 4, "min_countries": 3}},
        "concentration": {"max_country_share_pct": 50},
    }
    rep = regional_report(counts, targets=targets, total_sources=30)

    europe = next(r for r in rep["regions"] if r["region"] == "Europe")
    assert europe["sources"] == 5 and europe["countries_covered"] == 2
    assert europe["sources_met"] is True  # 5 >= 4
    assert europe["countries_met"] is False  # 2 < 3
    africa = next(r for r in rep["regions"] if r["region"] == "Africa")
    assert africa["sources"] == 1 and africa["sources_met"] is None  # no target -> no claim

    # specials counted apart; junk codes in no region; located = ISO-only
    assert rep["special_sources"] == 2
    assert rep["located_sources"] == 10
    assert rep["top_country"]["code"] == "br" and rep["top_country"]["share_pct"] == 40.0
    assert rep["located_share_pct"] == round(100 * 10 / 30, 1)


def test_coverage_report_separates_specials_from_junk():
    rep = coverage_report({"fr": 1, "eu": 2, "zz": 3})
    assert rep["special_codes"] == ["eu"]
    assert rep["extra_codes"] == ["zz"]


# --- the data migration's value plan ------------------------------------------ #


def _load_migration():
    path = (
        _ROOT / "migrations" / "versions" / "a3b4c5d6e7f8_normalize_country_codes.py"
    )
    spec = importlib.util.spec_from_file_location("mig_country", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mig_country"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_migration_plans_canonicalisation_and_leaves_junk_alone():
    mig = _load_migration()
    plan = mig._plan_updates(["US", "united-states", "fr", "germany", None, "", "??"])
    assert plan == {"US": "us", "united-states": "us", "germany": "de"}
    # 'fr' already canonical -> absent; junk '??' absent (left visible in the DB)


# --- the seed path normalises on the way in ----------------------------------- #


def test_seed_kwargs_canonicalise_and_fall_back_to_cctld():
    from src.ingest.seed_sources import _to_source_kwargs

    # slug from the old catalog style -> canonical code
    kw = _to_source_kwargs({"name": "X", "domain": "x.example", "country": "united-states"})
    assert kw["country"] == "us"
    # unrecognisable value is dropped, reliable ccTLD answers instead
    kw = _to_source_kwargs({"name": "Y", "domain": "y.bbc.co.uk", "country": "atlantis"})
    assert kw.get("country") == "gb"
    # nothing known -> no country at all (NOT a fabricated default)
    kw = _to_source_kwargs({"name": "Z", "domain": "z.example", "country": "atlantis"})
    assert "country" not in kw
