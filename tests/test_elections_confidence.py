"""The three ruled election date-confidence tiers, and the three refusals that hold them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-07-14 (V1_PATHWAY §4.5). The tiers themselves are the easy half;
what these tests exist for is the REFUSALS, because each of them is one small, plausible
edit away from turning the module into a date fabricator:

  * refusal 1 — no sourced rule + last-held ⇒ no projected entry (a gap, never a guess);
  * refusal 2 — a projection yields a YEAR, never a day;
  * refusal 3 — a passed projection is never silently re-projected to the next cycle.

Every test below names which refusal it holds. The negative-space twin is present for each
positive claim: an over-eager refusal that deleted real dates would read as conservative
and pass every test written only for the fabrication direction.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.civic.elections import (
    CAVEAT_PASSED,
    CAVEAT_PROJECTED,
    CAVEAT_SCHEDULED,
    CAVEAT_WINDOW,
    PROJECTED,
    SCHEDULED,
    TIERS,
    WINDOW,
    annotate,
    date_confidence,
    missing_projection_fields,
    projectable,
    projection,
)

TODAY = date(2026, 9, 7)
_LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"


def _election(**over) -> dict:
    """A minimal election entry; `over` supplies the field under test."""
    base = {"calendar": "elections", "title": "Somewhere — General election", "country": "xx"}
    base.update(over)
    return base


def _projectable(**over) -> dict:
    """A fully-sourced projectable entry; `over` REPLACES a default rather than colliding
    with it, so a test can vary exactly one of the three required fields."""
    fields = {
        "interval_years": 5,
        "last_held": "2022-04-10",
        "recurrence_rule_source": "Constitution art. 7",
    }
    fields.update(over)
    return _election(**fields)


# --------------------------------------------------------------------------- the tiers


def test_a_confirmed_entry_with_a_concrete_day_is_scheduled():
    assert date_confidence(_election(confirmed=True, month=11, day=3)) == SCHEDULED


def test_confirmed_without_a_day_is_a_window_not_a_schedule():
    """`confirmed: true` alone is not a date.

    An entry confirmed to fall in October is a window; reading `confirmed` as sufficient
    would promote a month-precision fact into "the electoral authority has set this day".
    """
    assert date_confidence(_election(confirmed=True, month=10, day=None)) == WINDOW


def test_a_stated_month_without_a_fixed_day_is_the_window_tier():
    assert date_confidence(_election(confirmed=False, month=4, day=None)) == WINDOW


def test_a_sourced_window_year_is_also_the_window_tier():
    """A law that fixes a YEAR but not a month is still a bounded window, one notch coarser."""
    assert date_confidence(_election(confirmed=False, window_year=2029)) == WINDOW


def test_a_fully_sourced_entry_with_no_stated_date_is_projected():
    assert date_confidence(_projectable()) == PROJECTED


def test_the_tier_vocabulary_does_not_apply_off_the_elections_calendar():
    """A trade summit is not a scheduled election — applying the vocabulary would be a
    category error, and would also silently widen what a surface filtering on the tier
    believes it is showing."""
    summit = {"calendar": "tech", "confirmed": True, "month": 1, "day": 7}
    assert date_confidence(summit) is None
    assert annotate(summit, TODAY) == summit  # byte-identical, so nothing else can shift


def test_the_tier_constants_are_exactly_the_three_ruled_ones():
    assert TIERS == (SCHEDULED, WINDOW, PROJECTED)


# ------------------------------------------------------------- refusal 1: no rule, no guess


@pytest.mark.parametrize("drop", ["interval_years", "last_held", "recurrence_rule_source"])
def test_refusal_1_dropping_ANY_required_field_kills_the_projection(drop):
    """Each field is individually load-bearing.

    Parametrised rather than written once because a fixture missing all three cannot tell
    a rule that needs all three from one that needs any one of them.
    """
    ev = _projectable()
    ev.pop(drop)
    assert projectable(ev) is False
    assert projection(ev, TODAY) is None
    assert date_confidence(ev) is None  # the GAP, not a lesser tier
    assert drop in missing_projection_fields(ev)


def test_refusal_1_cadence_prose_is_never_read_as_an_interval():
    """`cadence` is free text and is deliberately not consulted.

    "every 5 years" is exactly the string a future reader would be tempted to parse, and
    parsing it would manufacture the sourced rule the ruling requires. An entry carrying
    ONLY cadence must stay a gap.
    """
    ev = _election(cadence="every 5 years", last_held="2022-04-10",
                   recurrence_rule_source="Constitution art. 7")
    assert projectable(ev) is False
    assert date_confidence(ev) is None


@pytest.mark.parametrize("bad", [4.9, True, "5", "five", 0, -5, None])
def test_refusal_1_a_non_int_or_non_positive_interval_is_absent_not_coerced(bad):
    """`int(4.9)` is 4 and `int(True)` is 1 — both would arrive looking like a real
    sourced interval. The parse refuses instead of coercing."""
    assert projectable(_projectable(interval_years=bad)) is False


@pytest.mark.parametrize("bad", ["2022-13-40", "not-a-date", "", 20220410, None])
def test_refusal_1_an_unparseable_last_held_is_absent_not_guessed(bad):
    assert projectable(_projectable(last_held=bad)) is False


def test_refusal_1_a_blank_source_string_does_not_count_as_a_source():
    assert projectable(_projectable(recurrence_rule_source="   ")) is False


def test_refusal_1_negative_twin_a_fully_sourced_entry_still_projects():
    """The over-eager direction: a refusal that deleted real projections would pass every
    test above while quietly emptying the tier."""
    proj = projection(_projectable(), TODAY)
    assert proj is not None
    assert proj["year"] == 2027
    assert proj["status"] == "upcoming"


def test_a_yaml_native_date_object_is_accepted_as_last_held():
    """An unquoted `last_held: 2022-04-10` reaches us as a real `date`; a quoted one as a
    str. Both are legitimate spellings and refusing the first would make the config's
    quoting style decide whether a country is covered."""
    assert projectable(_projectable(last_held=date(2022, 4, 10))) is True


# ------------------------------------------------- refusal 2: a year, never a fabricated day


def test_refusal_2_a_projection_never_carries_a_day():
    """`last_held + N years` would print 2027-04-10 — a day precision no recurrence rule
    can support."""
    proj = projection(_projectable(), TODAY)
    assert proj is not None
    assert "day" not in proj
    assert proj["year"] == 2027


def test_refusal_2_the_month_comes_from_the_catalog_never_from_last_held():
    """`last_held` is in April; with no stated month the projection must NOT claim April.

    A rule that says "every 5 years" says nothing about which month the next one falls in,
    and inheriting the previous election's month is the most natural way to invent one.
    """
    assert projection(_projectable(), TODAY)["month"] is None
    stated = projection(_projectable(month=10), TODAY)
    assert stated["month"] == 10  # only because the catalog said so


def test_the_basis_sentence_reproduces_the_arithmetic_it_publishes():
    """A published method must describe the computation it actually did — the recorded
    "an equation that shows its work must show the work it did" lesson."""
    proj = projection(_projectable(), TODAY)
    assert "2022-04-10" in proj["basis"]
    assert "every 5 years" in proj["basis"]
    assert "Constitution art. 7" in proj["basis"]
    assert proj["last_held"] == "2022-04-10"
    assert proj["interval_years"] == 5
    # the printed terms must actually yield the printed result
    assert date.fromisoformat(proj["last_held"]).year + proj["interval_years"] == proj["year"]


def test_a_one_year_interval_is_not_pluralised():
    assert "every 1 year per" in projection(_projectable(interval_years=1), TODAY)["basis"]


# --------------------------------------------- refusal 3: never silently re-project a cycle


def test_refusal_3_a_long_passed_projection_is_NOT_rolled_forward():
    """THE test this module exists for.

    A single `while year < today.year: year += interval` would turn a 2007 projection into
    2027 and read as helpful. The projected year must stay exactly last_held + interval,
    however far in the past that lands, and the entry must say its status is unknown.
    """
    ev = _projectable(last_held="2002-04-10", interval_years=5)
    proj = projection(ev, TODAY)
    assert proj["year"] == 2007, "a passed projection was advanced to a later cycle"
    assert proj["status"] == "passed"
    assert proj["caveat"] == CAVEAT_PASSED


def test_refusal_3_the_passed_caveat_says_status_unknown_and_points_at_the_source():
    """The ruling's own words: a passed projected date is an investigative lead, so the
    caveat must not read as an ordinary "date to be confirmed"."""
    assert "status unknown" in CAVEAT_PASSED.lower()
    assert "official source" in CAVEAT_PASSED.lower()
    assert CAVEAT_PASSED != CAVEAT_PROJECTED


def test_refusal_3_negative_twin_a_future_projection_is_not_marked_passed():
    """The mirror failure: a refusal calibrated to catch stale projections must not
    condemn live ones. A fabricated "passed" is as dishonest as a fabricated date."""
    proj = projection(_projectable(last_held="2024-04-10", interval_years=5), TODAY)
    assert proj["year"] == 2029
    assert proj["status"] == "upcoming"
    assert proj["caveat"] == CAVEAT_PROJECTED


def test_a_year_only_projection_is_not_passed_until_the_whole_year_is_behind_us():
    """"Some time in 2026" has not passed on 2026-09-07 — only a month makes it decidable
    within the year."""
    ev = _projectable(last_held="2021-01-01", interval_years=5)  # -> 2026, no month
    assert projection(ev, TODAY)["status"] == "upcoming"
    # with a stated month that has gone by, it IS decidable and it has passed
    assert projection(_projectable(last_held="2021-01-01", interval_years=5, month=3),
                      TODAY)["status"] == "passed"
    # ... and a later month in the same year has not
    assert projection(_projectable(last_held="2021-01-01", interval_years=5, month=12),
                      TODAY)["status"] == "upcoming"


# -------------------------------------------------------------------------- the annotation


def test_annotate_is_additive_and_carries_a_visible_caveat_per_tier():
    for ev, want in (
        (_election(confirmed=True, month=11, day=3), CAVEAT_SCHEDULED),
        (_election(confirmed=False, month=4), CAVEAT_WINDOW),
        (_projectable(), CAVEAT_PROJECTED),
    ):
        out = annotate(ev, TODAY)
        assert out["date_caveat"] == want
        assert all(out[k] == v for k, v in ev.items()), "annotate must be purely additive"


def test_a_tierless_election_gets_no_caveat_because_there_is_no_date_to_caveat():
    out = annotate(_election(confirmed=False), TODAY)
    assert out["date_confidence"] is None
    assert out["date_caveat"] is None
    assert "projection" not in out


def test_only_a_projected_entry_carries_a_projection_block():
    assert "projection" not in annotate(_election(confirmed=True, month=11, day=3), TODAY)
    assert "projection" in annotate(_projectable(), TODAY)


def test_the_shipped_catalog_reaches_the_agenda_with_tiers_and_nothing_else_changes():
    """Behavioural wiring check: a helper that is never called is a dead end, and a source
    grep for the import cannot tell wired from merely imported."""
    from src.events.catalog import agenda

    rows = agenda(calendar="elections", today=TODAY)
    assert rows, "the shipped elections calendar is empty"
    assert all("date_confidence" in r for r in rows)
    assert {r["date_confidence"] for r in rows} <= set(TIERS) | {None}
    # every other calendar is untouched by the wiring
    for other in agenda(calendar="tech", today=TODAY):
        assert "date_confidence" not in other


# ------------------------------------------------------------------------------- the i18n


def test_every_caveat_is_translated_in_all_twelve_locales():
    """The informed-consent non-negotiable: every caveat string ships ×12.

    Asserts a real translation, not mere presence — an entry echoing the English back is
    the shape a half-done translation pass leaves behind, and it would satisfy the key
    check while leaving eleven locales in English.
    """
    caveats = [CAVEAT_SCHEDULED, CAVEAT_WINDOW, CAVEAT_PROJECTED, CAVEAT_PASSED]
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for c in caveats:
            assert c in data, f"{path.name}: missing caveat key {c[:40]!r}"
            assert data[c].strip(), f"{path.name}: empty translation for {c[:40]!r}"
            if path.stem != "en":
                assert data[c] != c, f"{path.name}: {c[:40]!r} is an untranslated English echo"
