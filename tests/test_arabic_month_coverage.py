"""Arabic month coverage — the Maghrebi and multi-word Levantine calendars.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two independent 2026-09-05 research passes surfaced the Maghrebi gap without knowing of
each other. Measured against the tree before the fix, the extractor read **1 of 8**
Maghrebi month names (مارس only, shared with the Gulf set) and **6 of 12** Levantine ones,
against a legal-source catalog that covers dz, tn, lb, sy and iq.

THE HALF THAT MATTERS MOST HERE IS THE NEGATIVE SPACE. Of the six Levantine names the
extractor did not read, only four were gaps: نيسان and آب are WITHHELD DELIBERATELY, with
measured fabrication evidence recorded beside them in ``dateextract.py`` ("سيارة نيسان
2023" is a Nissan model year; آب is ordinary fa/ur prose, "water"). The design doc for
this work lists them as missing coverage, which is exactly how a later session "fixes"
them and silently reintroduces invented dates — so the refusals are pinned here as
BEHAVIOUR, with their reason, rather than left as an absence somebody can read as an
oversight. The same applies to ماي, refused in this change for the same class of reason.

A month only ever fires next to a day or a year, so bare prose is safe; that is what makes
مارس ("practised") admissible and what the fabrication vectors above defeat.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.timemap.dateextract import extract_dates

_TODAY = date(2026, 1, 1)


def _extract(month_name: str, *, language: str | None = "ar", year: int = 2024) -> list[str]:
    """The dates the extractor claims for a plain ar dateline '15 <month> <year>'."""
    text = f"صدر التقرير في 15 {month_name} {year}."
    return [d["date"] for d in extract_dates(text, today=_TODAY, language=language)]


# --------------------------------------------------------------------------- #
# Maghrebi (ar-DZ / ar-TN): French-derived names, 1/8 before this change
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("name", "month"),
    [("جانفي", 1), ("فيفري", 2), ("مارس", 3), ("أفريل", 4), ("افريل", 4),
     ("جويلية", 7), ("أوت", 8)],
)
def test_maghrebi_month_names_resolve(name: str, month: str) -> None:
    assert f"2024-{month:02d}-15" in _extract(name), (
        f"{name} is an ar-DZ/ar-TN month name and must resolve"
    )


def test_the_maghrebi_june_resolves_only_under_an_arabic_hint() -> None:
    """جوان is June in Maghrebi Arabic AND a very common Persian word ("young").

    Exactly the تموز case, so it takes the same treatment: it resolves under an ar hint
    and is SKIPPED with no hint, never guessed. Without the gate, Persian prose carrying a
    year fabricates June rows — the failure that put تموز in the override map.
    """
    assert "2024-06-15" in _extract("جوان", language="ar")
    for language in ("fa", "ur", "en", None):
        assert _extract("جوان", language=language) == [], (
            f"جوان resolved under language={language!r} — the ar gate is not holding, and "
            f"Persian 'young' beside a year would fabricate a June date"
        )


def test_the_maghrebi_may_is_withheld_and_that_is_deliberate() -> None:
    """ماي is May in ar-DZ/ar-TN and colloquial WATER across the Gulf, Iraq and the Levant.

    The collision is WITHIN Arabic, so the language gate that saves جوان cannot help, and
    the corpus probe that cleared the six ungated Levantine names could not be run in the
    session that added the rest. It is refused on the آب precedent: a missing dateline is
    a visible gap, an invented date is not.

    If you are adding it, run that probe first and record the evidence in
    ``dateextract.py`` beside the entry — do not simply delete this test.
    """
    assert _extract("ماي") == [], "ماي is withheld — see the docstring before changing this"


def test_both_spellings_of_august_agree_on_the_month() -> None:
    """أوت (hamza, Maghrebi) and اوت (no hamza) are the same French loan, août.

    Written to pin a hamza DISTINCTION, and the tree refuted it: اوت was already in the
    table as PERSIAN August, so the two spellings agree at 8 and neither needs a gate.
    Kept, pointing the other way, because that agreement is the reason أوت could be added
    ungated — if a later edit ever gave one spelling a different month, an ar/fa corpus
    would read the same dateline as two different dates and nothing else would say so.
    """
    assert "2024-08-15" in _extract("أوت")
    assert "2024-08-15" in _extract("اوت")
    assert "2024-08-15" in _extract("اوت", language="fa")


# --------------------------------------------------------------------------- #
# Levantine: 6/12 before this change, 10/12 after
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("name", "month"),
    [("كانون الثاني", 1), ("شباط", 2), ("آذار", 3), ("أيار", 5), ("حزيران", 6),
     ("تموز", 7), ("أيلول", 9), ("تشرين الأول", 10), ("تشرين الثاني", 11),
     ("كانون الأول", 12)],
)
def test_levantine_month_names_resolve(name: str, month: int) -> None:
    assert f"2024-{month:02d}-15" in _extract(name), (
        f"{name} is a Levantine month name and must resolve under an ar hint"
    )


def test_multi_word_month_names_need_no_pattern_change() -> None:
    """The claim that motivated this: 'multi-word Levantine names are out of scope'.

    That was a statement about the MATCHER, and it was false — ``_MONTH_ALT`` is a plain
    alternation and every surrounding pattern wraps it in ``\\s+``, so a two-word
    alternative matches with nothing else changed. Pinned as behaviour because it is the
    premise the four additions rest on: if a future refactor makes multi-word entries
    unmatchable, a third of the Levantine year goes silently unread again.
    """
    for name in ("كانون الثاني", "تشرين الأول", "تشرين الثاني", "كانون الأول"):
        assert _extract(name), f"{name} stopped matching — multi-word month support regressed"


@pytest.mark.parametrize("name", ["نيسان", "آب"])
def test_the_two_withheld_levantine_names_stay_withheld(name: str) -> None:
    """نيسان (April) and آب (August) are refused on MEASURED fabrication evidence.

    نيسان is the Nissan marque — "سيارة نيسان 2023" is a model year, not April 2023 — and
    آب is ordinary Persian/Urdu prose ("water"). Both would fire, because a month needs
    only an adjacent number. The design doc for the 2026-09-05 keyword work lists them
    among the extractor's missing forms; they are not missing, they are declined, and this
    test is what stops that reading turning into a commit.
    """
    assert _extract(name) == [], (
        f"{name} now resolves — it is a documented fabrication vector, not a coverage gap; "
        f"see the comment beside the Levantine block in dateextract.py"
    )


def test_the_two_calendars_agree_where_they_share_a_name() -> None:
    """مارس is March in BOTH the Gulf and Maghrebi sets — one entry, one meaning.

    A guard against a future addition that re-lists a shared name under a second month by
    accident: the alternation would silently keep whichever the dict wrote last.
    """
    assert "2024-03-15" in _extract("مارس")
    assert "2024-03-15" not in _extract("جانفي")


def test_a_bare_month_name_in_prose_still_claims_nothing() -> None:
    """The property that makes ungated names safe: a month fires only beside a day/year.

    مارس also means "practised" and كانون alone is a brazier; neither may produce a date on
    its own, or every ungated addition above becomes a fabrication surface.
    """
    assert extract_dates("هو يمارس الرياضة", today=_TODAY, language="ar") == []
    assert extract_dates("جانفي فيفري جويلية", today=_TODAY, language="ar") == []
