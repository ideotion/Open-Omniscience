"""P1: the month alternation is narrowed to the names the text contains.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_MONTH_ALT`` is 555 multilingual month names in ten ``re.I`` patterns over a 60,000
character window, and CPython's ``re`` tries every branch at every word boundary — 81%
of all date-regex time. ``_extract`` now rebuilds those patterns over the months the
document actually contains.

The whole value of that rests on ONE claim: **the narrowed patterns find exactly the
dates the full ones did.** So the load-bearing test here is a DIFFERENTIAL, not a
fixture — ``months_present`` is forced to report every name, which reconstructs the
pre-P1 alternation, and the two runs must agree candidate-for-candidate and
span-for-span. A fixture would only ever prove the cases someone thought of.

The rest pin the two ways a false negative could get in (the names a token pass cannot
see; case) and the two things a later edit is most likely to break silently (a new
pattern compiled with ``re.compile`` instead of ``_month_re``, and the identity test
that used to discriminate the no-year pair).
"""

from __future__ import annotations

from datetime import date

import pytest

from src.timemap import dateextract as de
from src.timemap.dateextract import (
    _MONTH_NAMES,
    _MONTH_TEMPLATES,
    _SCAN_MONTHS,
    _TOKEN_MONTHS,
    extract_dates,
    extract_dates_with_spans,
    months_present,
)

TODAY = date(2026, 6, 9)
ANCHOR = date(2026, 3, 4)

# One text per shape the month-carrying patterns implement, across scripts and
# calendars. Small on purpose: the differential's job is coverage of the CODE PATHS,
# and the exhaustive 555-name sweep lives in the property test at the bottom.
CORPUS = [
    "on 11 September 2001 the report landed",
    "September 11, 2001 was the date",
    "the 3rd of June 2026 filing",
    "published March 2001 in the journal",
    "the march of 2024 protesters gathered",
    "between 11 and 13 June 2026 talks ran",
    "June 11-13, 2026 the summit met",
    "11-13 juin 2026 le sommet",
    "11. Dezember 2026 laut Bericht",
    "2024. május 5. a jelentes szerint",
    "2024. június szerint",
    "June 11 with no year at all",
    "11 juin with no year at all",
    "11 سبتمبر/أيلول 2001 dual-named",
    "June 11-July 13, 2026 cross-month",
    "aged 5-7. Juni 2026 note",
    "11-го сентября 2001 sources said",
    "১১ই সেপ্টেম্বর ২০০১ প্রতিবেদন",
    "कल 11 सितंबर 2001 को",
    "2001-09-11 and 令和6年6月11日 and 2024年5月11日",
    "Marta 30 godina kasnije",  # homograph: a name + number, never a date
    "no dates here at all, only prose about the market",
    "",
]
LANGS = ("en", "fr", "de", "hu", "ru", "ar", "bn", "hi", "sr", "tr", "el", "ja", None)


def _run(text, language):
    return extract_dates_with_spans(
        text, language=language, anchor=ANCHOR, today=TODAY, limit=8
    )


# --------------------------------------------------------------------------- #
# The differential: narrowed output == un-narrowed output
# --------------------------------------------------------------------------- #

def test_narrowing_changes_no_date_and_no_claimed_span(monkeypatch):
    """Forcing every name back into the alternation must change nothing.

    This is the pre-P1 behaviour reconstructed in-process: with ``months_present``
    reporting all 555, ``_narrowed`` rebuilds the full alternation, so any difference
    is the narrowing itself.
    """
    baseline = {}
    monkeypatch.setattr(de, "months_present", lambda _text: frozenset(_MONTH_NAMES))
    de._narrowed.cache_clear()
    for text in CORPUS:
        for lang in LANGS:
            baseline[(text, lang)] = _run(text, lang)

    monkeypatch.undo()
    de._narrowed.cache_clear()
    for text in CORPUS:
        for lang in LANGS:
            assert _run(text, lang) == baseline[(text, lang)], (text, lang)

    # Anti-vacuity: the differential is worthless if the baseline found nothing.
    assert sum(len(cands) for cands, _ in baseline.values()) > 100


def test_the_differential_can_fail(monkeypatch):
    """The check above must be able to go red — prove it with a broken narrowing.

    A scan that reports nothing retires every month pattern, so every named-month date
    disappears. If this test does not see that, the differential is inert.
    """
    monkeypatch.setattr(de, "months_present", lambda _text: frozenset())
    de._narrowed.cache_clear()
    got = [c for text in CORPUS for c, _ in [_run(text, "en")] for c in c]
    monkeypatch.undo()
    de._narrowed.cache_clear()
    full = [c for text in CORPUS for c, _ in [_run(text, "en")] for c in c]
    assert len(got) < len(full)


# --------------------------------------------------------------------------- #
# The presence scan: the two ways a false negative could get in
# --------------------------------------------------------------------------- #

def test_the_substring_pass_finds_names_a_token_pass_cannot():
    """51 Indic + 4 two-word Arabic names are not one word-run; they need the scan.

    Deleting the substring pass loses 986 of 11,973 candidates in the full differential
    — this is the unit-level statement of the same fact.
    """
    # The two passes PARTITION the table: every name is reachable by exactly one of
    # them, so no name can fall between the tokeniser and the substring scan.
    assert _TOKEN_MONTHS.isdisjoint(_SCAN_MONTHS)
    assert _TOKEN_MONTHS | set(_SCAN_MONTHS) == _MONTH_NAMES
    assert len(_SCAN_MONTHS) == 55
    assert "كانون الثاني" in _SCAN_MONTHS  # two words
    assert "सितंबर" in _SCAN_MONTHS  # Devanagari combining marks
    assert months_present("تقرير 11 كانون الثاني 2001") >= {"كانون الثاني"}
    assert months_present("रिपोर्ट 11 सितंबर 2001") >= {"सितंबर"}
    # ...and they really are dates, not just names the scan happened to see.
    assert extract_dates("11 كانون الثاني 2001", today=TODAY, language="ar")
    assert extract_dates("11 सितंबर 2001", today=TODAY, language="hi")


@pytest.mark.parametrize("cased", ["September", "SEPTEMBER", "september", "SePtEmBeR"])
def test_the_scan_is_case_insensitive_like_the_patterns(cased):
    assert "september" in months_present(f"filed {cased} 11, 2001")
    assert extract_dates(f"filed {cased} 11, 2001", today=TODAY, language="en")


def test_the_scan_is_exactly_as_case_strict_as_month_of():
    """The invariant that makes ``lower()`` sufficient, over every name and casing.

    ``re.I`` is more permissive than ``str.lower()`` — it matches "MAYIS" against the
    table's Turkish "mayıs" while "MAYIS".lower() is "mayis". That is not a lost date,
    because every month-carrying loop resolves its match through ``_month_of``, which
    lowers the SAME token with the SAME method and skips on a miss. So a name this scan
    cannot key is a name the old path refused too.

    If ``_month_of`` ever changes its normalisation (casefold, NFKC, a Turkish-aware
    fold), this test is what says the scan must change with it.
    """
    langs = sorted({lang for v in de._MONTH_LANG_OVERRIDES.values() for lang in v} | {"en", "tr", "el", ""})
    casings = (str, str.upper, str.title, str.capitalize, str.swapcase)
    violations = []
    for name in sorted(_MONTH_NAMES):
        for cas in casings:
            variant = cas(name)
            if name in months_present(f"the report of 11 {variant} 2001 said so"):
                continue  # kept: the narrowing cannot lose it
            if any(de._month_of(variant, lang) is not None for lang in langs):
                violations.append((name, variant))
    assert violations == []
    # Anti-vacuity: a name absent from a text really is reported missing, and really
    # would resolve — otherwise the loop above proves nothing.
    assert "abril" not in months_present("prose with no month names in it")
    assert de._month_of("abril", "es") is not None


# --------------------------------------------------------------------------- #
# Shape guards: what a later edit is most likely to break silently
# --------------------------------------------------------------------------- #

def test_every_month_carrying_pattern_is_registered_for_narrowing():
    """A new pattern built with ``re.compile`` + ``_MONTH_ALT`` would keep the full
    555-branch cost and never be narrowed — silently, since it would still be correct.
    Compiled patterns are the source of truth here, not a hand-kept list."""
    import re

    carriers = {
        name for name, val in vars(de).items()
        if isinstance(val, re.Pattern) and de._MONTH_ALT in val.pattern
    }
    registered = {
        name for name, val in vars(de).items()
        if isinstance(val, re.Pattern) and val in _MONTH_TEMPLATES
    }
    assert carriers == registered, f"not narrowable: {sorted(carriers - registered)}"
    assert len(registered) == 10


def test_a_narrowed_pattern_keeps_the_longest_first_ordering():
    """'sept' must still beat 'sep' — ordering, not membership.

    Asserted on BEHAVIOUR, not on the pattern source: a source-order assertion passes
    just as happily on an alternation that never had 'sep' in it, and the reason the
    order matters is that ``re`` takes the first alternative that matches, which is a
    fact about the match and not about the string.
    """
    narrowed = de._narrowed(de._MDY_RE, frozenset({"sep", "sept", "may"}))
    assert narrowed is not None
    m = narrowed.search("Sept 11, 2001")
    assert m is not None and m.group(1).lower() == "sept", "shorter alternative won"
    # ...and end to end, through the real path.
    assert extract_dates("Sept 11, 2001", today=TODAY, language="en")[0]["date"] == "2001-09-11"


def test_no_month_in_the_text_retires_the_pattern_entirely():
    assert de._narrowed(de._MDY_RE, frozenset()) is None
    # ...and the loops tolerate that rather than raising.
    assert extract_dates("the market moved on 2001-09-11", today=TODAY) == [
        {"date": "2001-09-11", "precision": "day", "text": "the market moved on 2001-09-11"}
    ]


def test_the_homograph_guard_survives_the_rebuilt_patterns():
    """The no-year loop used ``rx is _MD_NOYEAR_RE`` to know which member it was on.

    Under P1 those are patterns rebuilt for this document, so they are never the
    module-level object and the identity test would silently stop firing — letting
    "Marta 30 godina" fabricate 30 March. The loop carries the fact explicitly instead;
    this is the regression that would follow from putting the identity test back.
    """
    assert extract_dates("Marta 30 godina kasnije", today=TODAY, anchor=ANCHOR, language="sr") == []
    # The mirror: the day-first order for the same homograph IS a date, so the guard
    # is narrow rather than a blanket refusal.
    assert extract_dates("30. marta 2024.", today=TODAY, language="sr")


def test_the_scan_runs_on_the_truncated_text_only():
    """A name occurring only past ``_MAX_SCAN`` must not widen the alternation — and,
    more importantly, must not appear to be extractable when it is out of the window."""
    pad = "the committee met and the officials confirmed the policy again " * 1200
    assert len(pad) > de._MAX_SCAN
    beyond = pad[: de._MAX_SCAN + 500] + " 11 September 2001 "
    assert extract_dates(beyond, today=TODAY, language="en") == []


def test_the_narrowing_cache_is_bounded():
    """An unbounded cache keyed on a set drawn from corpus text is a slow leak on the
    collector's hot path."""
    assert de._narrowed.cache_info().maxsize == 256
