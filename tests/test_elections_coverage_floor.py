"""The elections coverage floor — the ruled denominator, and the honesty of its arithmetic.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-07-14 (V1_PATHWAY §4.5(1)). The floor is a DENOMINATOR, so both
directions of error are expensive and both are pinned here: a country wrongly ABSENT lets
the vertical claim coverage it does not have, and a country wrongly PRESENT manufactures a
permanent red the calendar can never clear.

The load-bearing property is the PARTITION. ``covered``, ``only_passed_projection``,
``present_but_dateless`` and ``missing`` must together account for every floor country
exactly once — otherwise a country can be quietly counted twice (inflating coverage) or
fall through every bucket (disappearing from the worklist), and neither shows up in any
single count.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from src.civic.coverage_floor import (
    FLOOR_PATH,
    LANGUAGE_COUNTRIES_AS_OF,
    VALID_BASES,
    floor_countries,
    floor_coverage,
    load_floor,
)

TODAY = date(2026, 9, 7)
_ROOT = Path(__file__).resolve().parents[1]

#: The twelve UI locales the floor is defined over.
_UI_LANGS = {"ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"}


# ------------------------------------------------------------------------- the mapping


def test_the_floor_is_defined_over_exactly_the_twelve_ui_languages():
    """The floor's whole meaning is "if a user can read the app in their language, their
    country is in it" — so a thirteenth language, or a missing one, silently changes what
    the vertical owes."""
    assert set(load_floor()["languages"]) == _UI_LANGS


def test_every_country_code_is_a_real_iso_3166_1_country():
    """Reported, never dropped: a typo that silently vanished would SHRINK the floor, and a
    smaller floor is easier to clear — the failure direction that flatters us."""
    assert load_floor()["invalid"] == []


def test_an_unknown_code_is_reported_rather_than_silently_dropped(monkeypatch):
    """The negative-space twin of the test above: it passes today because the data is
    clean, which says nothing about whether the CHECK works. This drives a bad code
    through the real parse and asserts it is NAMED.

    `monkeypatch` rather than a reload: reloading the module mid-suite would hand every
    other importer a stale module object, which is cross-test pollution dressed as cleanup.
    """
    from src.civic import coverage_floor as cf

    raw = cf._raw()
    langs = {k: dict(v) for k, v in raw["languages"].items()}
    langs["en"] = {**langs["en"], "countries": [{"cc": "zz", "basis": "official"}]}
    monkeypatch.setattr(cf, "_raw", lambda: {**raw, "languages": langs})

    out = cf.load_floor.__wrapped__()  # the real body, past its cache
    assert any(i["cc"] == "zz" for i in out["invalid"]), "a bad code vanished silently"
    assert "zz" not in out["countries"]
    assert out["invalid"][0]["language"] == "en"


def test_every_row_declares_a_basis_from_the_stated_vocabulary():
    for lang, block in load_floor()["languages"].items():
        for row in block["countries"]:
            assert row["basis"] in VALID_BASES, f"{lang}/{row['cc']}: {row['basis']!r}"


def test_every_language_names_the_source_its_rows_rest_on():
    for lang, block in load_floor()["languages"].items():
        assert block["source"].strip(), f"{lang}: no source stated"


def test_the_as_of_constant_and_the_yaml_agree():
    """Two spellings of one fact drift apart the moment only one is bumped — and the
    registry pins the CONSTANT while every payload publishes the YAML's value, so a drift
    would make the freshness report describe a different vintage than the data."""
    raw = yaml.safe_load(FLOOR_PATH.read_text(encoding="utf-8"))
    assert raw["as_of"] == LANGUAGE_COUNTRIES_AS_OF


def test_the_mapping_is_registered_as_an_external_artifact():
    """CLAUDE.md's external-artifact protocol: a dated artifact ships WITH its registry
    entry or the guard fails. Asserted here too so the failure names this file."""
    from src.maintenance import registry as R

    ids = {a["id"] for a in R.summary()["artifacts"]}
    assert "language-countries-floor" in ids


def test_the_unverified_status_travels_into_every_payload():
    """The mapping was drafted, not verified. A coverage share computed over an unverified
    denominator that does not SAY so reads as settled — the fabricated-confidence failure."""
    for payload in (load_floor(), floor_coverage(TODAY)):
        assert "pending" in payload["verification_status"].lower()


def test_contested_rows_are_flagged_rather_than_quietly_kept_or_quietly_dropped():
    """A language's legal standing is where a confident list is most likely to be wrong;
    carrying the doubt is the point, so at least the known-hard cases must be marked."""
    contested = {c["cc"] for c in load_floor()["contested"]}
    # Mexico designates no official language; Mali and Niger reclassified French.
    assert {"mx", "ml", "ne"} <= contested
    assert all(c["note"].strip() for c in load_floor()["contested"]), "a flag with no reason"


# ------------------------------------------------------------------------ the arithmetic


def test_the_four_states_partition_the_floor_exactly():
    """THE load-bearing property.

    Double-counting inflates coverage; a country in none of the four vanishes from the
    worklist. Neither is visible in any single count, so the partition is asserted as an
    identity rather than inferred from the numbers looking plausible.
    """
    c = floor_coverage(TODAY)
    buckets = [
        set(c["covered"]),
        set(c["only_passed_projection"]),
        {d["cc"] for d in c["present_but_dateless"]},
        set(c["missing"]),
    ]
    union: set[str] = set()
    for b in buckets:
        assert not (union & b), f"a country is in two states at once: {union & b}"
        union |= b
    assert union == floor_countries()
    assert sum(len(b) for b in buckets) == c["floor_countries"]


def test_the_published_counts_match_the_published_lists():
    """A count and its list are two spellings of one measurement; a renderer that shows the
    count while the list is truncated is the recorded anti-capping defect."""
    c = floor_coverage(TODAY)
    assert c["covered_n"] == len(c["covered"])
    assert c["missing_n"] == len(c["missing"])
    assert c["present_but_dateless_n"] == len(c["present_but_dateless"])
    assert c["only_passed_projection_n"] == len(c["only_passed_projection"])
    assert c["floor_countries"] == len(floor_countries())


def test_a_dateless_entry_is_never_counted_as_coverage():
    """An election entry that states no date and carries no sourced rule tells a reader
    nothing; letting it clear the floor would make the bar meaningless."""
    c = floor_coverage(TODAY)
    dateless = {d["cc"] for d in c["present_but_dateless"]}
    assert dateless, "the fixture must actually contain a dateless entry, or this is vacuous"
    assert not (dateless & set(c["covered"]))
    # and each one names WHICH fields it lacks, so it is a worklist rather than a complaint
    assert all(d["missing_fields"] for d in c["present_but_dateless"])


def test_coverage_outside_the_floor_is_reported_apart_never_folded_in():
    """The floor is a MINIMUM. A calendar entry for a country outside it is legitimate, and
    adding it to `covered_n` would let a country the floor never asked for flatter the
    share."""
    c = floor_coverage(TODAY)
    assert not (set(c["covered_outside_floor"]) & floor_countries())
    # the shipped catalog really does carry some (Latvia, Sweden), so this is not vacuous
    assert c["covered_outside_floor"]


def test_a_country_with_both_a_dated_and_a_dateless_entry_counts_as_covered(monkeypatch):
    """The dated entry answers the reader, so the country is covered — but only a fixture
    holding BOTH shapes can tell that rule from "any dateless entry disqualifies"."""
    from src.civic import coverage_floor as cf

    cc = sorted(floor_countries())[0]
    monkeypatch.setattr(
        cf, "load_floor", lambda: {**load_floor(), "countries": [cc]}
    )
    monkeypatch.setattr(
        "src.events.catalog.load_events",
        lambda: [
            {"calendar": "elections", "country": cc, "confirmed": True, "month": 5, "day": 4},
            {"calendar": "elections", "country": cc, "confirmed": False},
        ],
    )
    c = cf.floor_coverage(TODAY)
    assert c["covered"] == [cc]
    assert c["present_but_dateless"] == []


def test_a_country_whose_only_entry_is_a_passed_projection_is_not_counted_as_covered(monkeypatch):
    """The weakest possible coverage. The ruling makes a passed projection a LEAD, so it is
    kept and reported — but folding it into `covered` would let the floor be cleared by
    dates that have already gone by."""
    from src.civic import coverage_floor as cf

    cc = sorted(floor_countries())[0]
    monkeypatch.setattr(cf, "load_floor", lambda: {**load_floor(), "countries": [cc]})
    monkeypatch.setattr(
        "src.events.catalog.load_events",
        lambda: [{
            "calendar": "elections", "country": cc,
            "interval_years": 5, "last_held": "2002-04-10",
            "recurrence_rule_source": "Constitution art. 7",
        }],
    )
    c = cf.floor_coverage(TODAY)
    assert c["only_passed_projection"] == [cc]
    assert c["covered"] == []
    assert c["missing"] == []  # it is not missing either — it is its own state


def test_an_upcoming_projection_DOES_count_as_coverage(monkeypatch):
    """The negative twin of the test above: a rule tuned to exclude stale projections must
    not exclude live ones, or the projected tier could never contribute to the floor at
    all and the whole third tier would be decorative."""
    from src.civic import coverage_floor as cf

    cc = sorted(floor_countries())[0]
    monkeypatch.setattr(cf, "load_floor", lambda: {**load_floor(), "countries": [cc]})
    monkeypatch.setattr(
        "src.events.catalog.load_events",
        lambda: [{
            "calendar": "elections", "country": cc,
            "interval_years": 5, "last_held": "2024-04-10",
            "recurrence_rule_source": "Constitution art. 7",
        }],
    )
    c = cf.floor_coverage(TODAY)
    assert c["covered"] == [cc]
    assert c["only_passed_projection"] == []


def test_the_method_sentence_names_the_arithmetic_it_actually_did():
    """A published method that describes a different computation is a fabricated caveat —
    the mismatch is invisible in review precisely because the sentence reads correctly."""
    m = floor_coverage(TODAY)["method"]
    for phrase in ("twelve UI languages", "scheduled", "window", "projection", "never as coverage"):
        assert phrase in m, f"the method sentence omits {phrase!r}"


# ------------------------------------------------------------------------ no score, ever


def test_the_payload_carries_no_score_shaped_field():
    """The project-wide no-score rule, walked over the real payload's KEYS.

    `"degraded"` contains `"grade"`, so the substring convention is deliberately strict;
    walking our own keys before pushing is the recorded habit.
    """
    banned = ("score", "rating", "ranking", "grade")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(floor_coverage(TODAY))


def test_the_diagnostic_endpoint_serves_the_real_measurement():
    """Behavioural: a shape assertion cannot tell a working member from one handed nothing,
    because every block here degrades to the same key set. Asserts a VALUE only the real
    path can produce."""
    from src.api.diagnostics import elections_coverage_floor

    payload = elections_coverage_floor()
    assert payload["floor_countries"] == len(floor_countries())
    assert payload["as_of"] == LANGUAGE_COUNTRIES_AS_OF


def test_the_endpoint_is_a_member_of_the_all_diagnostics_bundle():
    """Every GET on the diagnostics router is a bundle member or a documented exemption —
    the 2026-07-17 ratchet. Named here so the failure points at this slice."""
    from src.api import diagnostics as diag

    assert diag._DIAG_COVERAGE_MAP["/elections-floor"] == "elections-floor.json"


@pytest.mark.parametrize("path", [FLOOR_PATH])
def test_the_config_states_its_verification_status_at_the_top(path):
    """The climate_events.yml precedent: the as-of date and the pending flag travel with
    the file, so nothing in it is presented as verified."""
    head = path.read_text(encoding="utf-8")[:4000]
    assert re.search(r"VERIFICATION STATUS", head)
    assert "clearnet check pending" in head
