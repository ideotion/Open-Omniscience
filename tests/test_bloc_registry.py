"""Membership is time-varying, and an unpopulated group says so instead of being absent.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07, ruling 45. The defect this guards against does not look like a
defect: a bloc figure computed with today's roster over a 1995 series is a plausible
number, correctly formatted, and wrong. So the tests drive the resolution across an
accession and a departure rather than checking that a roster "looks right".

The other half is the empty tables. It would be easy to read them as unfinished work and
"helpfully" fill them in from memory; these tests pin that an empty group must report a
REASON, so a future session hits the reasoning before the keyboard.
"""

from __future__ import annotations

from src.catalog.blocs import (
    BLOC_REGISTRY_AS_OF,
    Group,
    Membership,
    group_names,
    groups_of_kind,
    members_as_of,
    resolve_group,
)
from src.catalog.countries import CONTINENT_OF

# --------------------------------------------------------------------------- #
#  Continents — the lens that is real today
# --------------------------------------------------------------------------- #


def test_the_continent_lens_is_populated_from_the_shipped_table():
    africa = members_as_of("africa")
    assert africa["populated"] is True
    assert africa["kind"] == "continent"
    expected = sorted(a for a, c in CONTINENT_OF.items() if c == "Africa")
    assert africa["members"] == expected
    assert len(africa["members"]) > 50


def test_every_continent_resolves_and_none_is_empty():
    for g in groups_of_kind("continent"):
        out = members_as_of(g.key)
        assert out["populated"] is True, g.key
        assert out["members"], g.key


def test_the_transnational_bucket_is_not_offered_as_a_continent():
    """`CONTINENT_OF` maps the `int`/`eu` special codes to a "Global" bucket so the
    regional-balance report has an honest home for them. It is not a continent, and
    aggregating GDP over it would be meaningless."""
    assert "global" not in group_names()
    for g in groups_of_kind("continent"):
        assert "int" not in [m.area for m in g.members]
        assert "eu" not in [m.area for m in g.members]


def test_a_continent_carries_no_dates_and_says_why():
    out = members_as_of("europe", "1995")
    assert out["dates_apply"] is False
    assert out["undated_members"] == []  # no accession exists to be undated ABOUT
    assert "does not change" in out["notes"]


# --------------------------------------------------------------------------- #
#  Time-varying resolution — the property the whole registry exists for
# --------------------------------------------------------------------------- #


def _bloc(*members: Membership) -> Group:
    return Group(key="t", label="T", kind="bloc", members=tuple(members))


def test_a_member_is_absent_before_it_joined():
    from src.catalog import blocs

    g = _bloc(Membership("br", joined="2009-06-16"), Membership("fi", joined="2023-04-04"))
    blocs._GROUPS["t"] = g
    try:
        assert members_as_of("t", "2010")["members"] == ["br"]
        assert members_as_of("t", "2023")["members"] == ["br", "fi"]
        assert members_as_of("t", "2008")["members"] == []
    finally:
        del blocs._GROUPS["t"]


def test_a_member_is_absent_from_the_year_it_left():
    """The UK is in the EU for 2019 and out for 2020 — the exact shape that makes a
    stale roster invisible in a long series."""
    from src.catalog import blocs

    blocs._GROUPS["t"] = _bloc(Membership("gb", joined="1973-01-01", left="2020-01-31"))
    try:
        assert members_as_of("t", "2019")["members"] == ["gb"]
        assert members_as_of("t", "2020")["members"] == []
    finally:
        del blocs._GROUPS["t"]


def test_suspension_is_a_third_state_and_is_reported_separately():
    """Neither `joined` nor `left` expresses it, and choosing one for the caller would be
    a false claim about a real situation."""
    from src.catalog import blocs

    blocs._GROUPS["t"] = _bloc(
        Membership("ml", joined="1963-05-25", suspended_from="2021-06-01"),
        Membership("gh", joined="1963-05-25"),
    )
    try:
        out = members_as_of("t", "2022")
        assert out["members"] == ["gh", "ml"], "a suspended member is still a member"
        assert out["suspended"] == ["ml"]
        before = members_as_of("t", "2019")
        assert before["suspended"] == [], "not suspended before the suspension date"
    finally:
        del blocs._GROUPS["t"]


def test_a_member_with_no_sourced_accession_date_is_flagged_not_hidden():
    """Ruling 45: record `joined=None` and state the gap. It still resolves as a member —
    dropping it would be a worse fabrication than carrying it — but its presence in a
    historical year is asserted, not evidenced, and the payload says so."""
    from src.catalog import blocs

    blocs._GROUPS["t"] = _bloc(Membership("xx"), Membership("br", joined="2009-06-16"))
    try:
        out = members_as_of("t", "2015")
        assert out["members"] == ["br", "xx"]
        assert out["undated_members"] == ["xx"]
    finally:
        del blocs._GROUPS["t"]


def test_no_period_resolves_to_today_and_says_that_is_wrong_for_a_series():
    out = members_as_of("africa")
    assert out["resolved_year"] is None
    assert "wrong roster for a historical series" in out["caveat"]


def test_a_period_with_a_quarter_still_resolves_its_year():
    from src.catalog import blocs

    blocs._GROUPS["t"] = _bloc(Membership("se", joined="2024-03-07"))
    try:
        assert members_as_of("t", "2024-Q3")["members"] == ["se"]
        assert members_as_of("t", "2023-Q3")["members"] == []
    finally:
        del blocs._GROUPS["t"]


# --------------------------------------------------------------------------- #
#  The empty tables — honest gaps, not absences
# --------------------------------------------------------------------------- #


def test_a_known_bloc_reports_that_it_exists_and_why_it_is_empty():
    """'BRICS exists and we cannot yet compute it' is a different and more useful answer
    than 'no such group'."""
    out = members_as_of("brics")
    assert out["known"] is True
    assert out["populated"] is False
    assert out["members"] == []
    assert "guessing a date" in out["reason"]


def test_every_unpopulated_group_carries_a_reason():
    for g in (*groups_of_kind("bloc"), *groups_of_kind("wb_region")):
        assert g.unpopulated_reason, g.key
        assert members_as_of(g.key)["populated"] is False


def test_world_bank_regions_are_not_offered_as_a_rename_of_continents():
    """Sub-Saharan Africa excludes the five North African economies, so substituting the
    continent lens would silently answer a different question."""
    reason = resolve_group("wb-sub-saharan-africa").unpopulated_reason
    assert "NOT continents" in reason
    assert "North African" in reason


def test_an_unknown_group_is_not_silently_empty():
    out = members_as_of("atlantis")
    assert out["known"] is False
    assert "No group named" in out["reason"]


def test_every_payload_states_the_registry_vintage():
    for key in ("africa", "brics", "wb-south-asia", "atlantis"):
        assert members_as_of(key)["as_of"] == BLOC_REGISTRY_AS_OF
