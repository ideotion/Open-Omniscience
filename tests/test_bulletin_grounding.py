"""
Grounding — the check that decides whether a model-written sentence may be kept.

The tests that matter here come in pairs. For every check, one case proves it
FIRES on an invention, and one proves it ABSTAINS where it cannot read — because
an over-eager check manufactures failures out of ordinary prose, and a fabricated
FAIL is exactly as dishonest as a fabricated pass.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.bulletin.grounding import (
    CASE_LANGUAGES,
    capitalised_runs,
    check_sentence,
    normalise_number,
    numbers_in,
    run_grounding_selftest,
)

_EV = (
    "This week the corpus holds 1,240 articles from 37 sources. "
    "The European Commission published a statement; Storm Fiona made landfall."
)


def _check(sentence, evidence=_EV, language="en"):
    return check_sentence(sentence, evidence, language=language)


# -- numbers: fires, and abstains ------------------------------------------- #


def test_an_invented_figure_is_caught():
    out = _check("Coverage reached 9,912 articles.")
    assert out["supported"] is False
    assert out["checks"]["numbers"]["missing"] == ["9912"]


def test_a_real_figure_passes_whatever_the_grouping_style():
    for written in ("1,240", "1240", "1 240"):
        assert _check(f"The corpus holds {written} articles.")["supported"] is True


def test_a_decimal_can_never_satisfy_a_claim_about_its_digits():
    """6.1 and 61 are different numbers. Normalising the separator away would let
    a magnitude claim be "supported" by an unrelated count."""
    out = check_sentence("Magnitude 6.1 was recorded.", "a magnitude of 61", language="en")
    assert out["supported"] is False


def test_a_sentence_with_no_figure_abstains_rather_than_passing():
    out = _check("Coverage grew across the week.")
    assert out["checks"]["numbers"]["applied"] is False
    assert out["checks"]["numbers"]["passed"] is None, "nothing to check is not a pass"


def test_a_percentage_is_checked_on_its_number_not_its_symbol():
    assert check_sentence("Some 37% of sources.", _EV, language="en")["supported"] is True
    assert check_sentence("Some 99% of sources.", _EV, language="en")["supported"] is False


# -- names: fires, and abstains --------------------------------------------- #


def test_an_invented_name_is_caught():
    out = _check("The Bavarian Assembly responded.")
    assert out["supported"] is False
    assert "Bavarian Assembly" in out["checks"]["names"]["missing"]


def test_a_real_name_passes():
    assert _check("Reporting cited the European Commission.")["supported"] is True


def test_case_and_accents_are_forgiven():
    """A model writing "ukraine" where the evidence says "Ukraine" has invented
    nothing; failing it would be a fabricated failure."""
    out = check_sentence("Coverage mentioned Ukraine.", "reports from ukraine", language="en")
    assert out["supported"] is True


def test_german_skips_the_name_check_instead_of_flagging_every_noun():
    """German capitalises every noun, so the check would flag ordinary prose."""
    out = check_sentence("Die Kommission nannte Zahlen.", "etwas anderes", language="de")
    assert out["checks"]["names"]["applied"] is False
    assert out["checks"]["names"]["passed"] is None
    assert "no entity signal" in out["checks"]["names"]["reason"]


def test_a_caseless_script_skips_the_name_check():
    for lang in ("zh", "ja", "ar", "th", "he"):
        out = check_sentence("报道提到了政策。", "别的内容", language=lang)
        assert out["checks"]["names"]["applied"] is False, lang


def test_the_skip_reason_refuses_to_read_as_cleared():
    out = check_sentence("Etwas.", "anderes", language="de")
    assert "NOT thereby cleared" in out["checks"]["names"]["reason"]


def test_german_still_has_its_numbers_checked():
    """Skipping the name check must not skip the language-agnostic one."""
    out = check_sentence("Es waren 9912 Artikel.", _EV, language="de")
    assert out["checks"]["numbers"]["applied"] is True
    assert out["supported"] is False


def test_an_unstated_language_abstains_from_the_name_check():
    out = check_sentence("The Bavarian Assembly met.", _EV, language=None)
    assert out["checks"]["names"]["applied"] is False


def test_a_sentence_initial_capital_is_grammar_not_a_name():
    assert capitalised_runs("Coverage grew sharply.") == []
    assert "Coverage" not in _check("Coverage grew sharply.").get("unsupported", [])


# -- the verdict ------------------------------------------------------------ #


def test_a_sentence_where_nothing_applied_reports_which_checks_ran():
    """"Nothing objected" and "verified" must not render the same, so the caller
    is handed the list of checks that actually ran."""
    out = check_sentence("成长。", "别的", language="zh")
    assert out["checks_applied"] == []
    assert out["supported"] is True
    assert "not the same as verified" in out["caveat"]


def test_one_failing_check_fails_the_sentence_even_if_the_other_passed():
    out = _check("The European Commission counted 9,912 articles.")
    assert out["checks"]["names"]["passed"] is True
    assert out["checks"]["numbers"]["passed"] is False
    assert out["supported"] is False


def test_the_caveat_states_what_the_check_cannot_do():
    """A validator quietly believed to do more than it does is worse than none."""
    out = _check("Coverage grew.")
    assert "does NOT catch" in out["caveat"]
    assert "arranged into a false claim" in out["caveat"]


def test_no_score_shaped_field_in_the_verdict():
    flat = json.dumps(_check("The corpus holds 1240 articles.")).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat


# -- the primitives --------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "want"),
    [("1,240", "1240"), ("1 240", "1240"), ("1.240", "1240"), ("6.1", "6.1"), ("6,1", "6.1"),
     ("37", "37"), ("1,234,567", "1234567")],
)
def test_number_normalisation(raw, want):
    assert normalise_number(raw) == want


def test_numbers_are_returned_in_order_without_duplicates():
    assert numbers_in("5 then 12 then 5 again") == ["5", "12"]


def test_german_is_deliberately_absent_from_the_case_languages():
    assert "de" not in CASE_LANGUAGES
    assert "en" in CASE_LANGUAGES and "fr" in CASE_LANGUAGES


def test_selftest_passes_and_the_loop_can_read_its_verdict():
    out = run_grounding_selftest()
    assert out["failed_count"] == 0, [c for c in out["cases"] if not c["passed"]]
    assert isinstance(out["passed"], bool)

    from src.monitoring.recursive_loop import LOOP_SELFTESTS, _selftest_passed

    assert _selftest_passed(out) is True
    assert any(
        mod == "src.bulletin.grounding" and fn == "run_grounding_selftest"
        for _, mod, fn in LOOP_SELFTESTS
    )
