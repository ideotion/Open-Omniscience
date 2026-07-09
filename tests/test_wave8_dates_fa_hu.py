"""Date-extraction wave 8 — the two worst recall gaps: Persian (fa) and Hungarian (hu).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field test 2026-07-08 (Item 8 / F4): overall date recall was 62.1 %, but Persian sat at
0 % (Iranian datelines use the Solar-Hijri / Jalali calendar with Persian month NAMES,
long omitted because a blind month-number mapping would fabricate) and Hungarian at 22 %.

This pins, honesty-first:
  * HUNGARIAN — the year-first period-separated format ("2024. június 11."), the
    year-first named MONTH-only form ("2024. június" -> month precision), and the spaced
    numeric form ("2024. 06. 11."); plus the guard that the year-first-month-only read is
    hu-GATED (a stray "in 2024. March …" sentence boundary in English never fabricates);
  * PERSIAN — exact Jalali->Gregorian CONVERSION (golden anchors + leap-year validity),
    named datelines, numeric Jalali (which fixes a live fabrication: "۱۴۰۳/۰۳/۱۱" used to
    store 1403-03-11 CE), Gregorian dates written with Persian digits, the Arabic-yeh
    spelling variant, and the fa GATE (a Jalali name outside a fa article is SKIPPED, never
    guessed; the homograph months تیر/مهر/دی never fabricate from prose);
  * LOCKSTEP — the datediag recall probe reports zero actionable gap on a fa Jalali date,
    and a gated token outside its language is not a phantom gap.

Pure/unit — no DB, no network. The conversion arithmetic is proven exact against an
independent library (jdatetime) over 150 years and by full round-trip; here we pin the
documented golden anchors + the leap-year edges directly.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.timemap import datediag
from src.timemap.dateextract import (
    _FA_JY_MAX,
    _FA_JY_MIN,
    _jalali_month_length,
    _jalali_valid,
    extract_dates,
)

# Late anchor/today so every converted date (incl. 1404/2025 & near-future) is in-window.
TODAY = date(2027, 1, 1)
ANCHOR = date(2024, 6, 10)


def _dates(text, lang=None, anchor=ANCHOR):
    return [(c["date"], c["precision"])
            for c in extract_dates(text, today=TODAY, anchor=anchor, language=lang)]


# --------------------------------------------------------------------------- #
# Jalali -> Gregorian conversion — golden anchors (exact) + leap-year validity #
# --------------------------------------------------------------------------- #

# Verified 2026-07-08 against the independent jdatetime library over 54,707 days
# (0 mismatches) and a full round-trip over Jalali years 1200–1500 (0 failures).
GOLDEN = {
    (1403, 1, 1): date(2024, 3, 20),    # Nowruz 1403 (the task's golden anchor)
    (1404, 1, 1): date(2025, 3, 21),    # Nowruz 1404 — one day later BECAUSE 1403 is leap
    (1400, 1, 1): date(2021, 3, 21),    # Nowruz 1400
    (1399, 1, 1): date(2020, 3, 20),    # Nowruz 1399 (1399 leap)
    (1403, 1, 15): date(2024, 4, 3),    # 15 Farvardin 1403 (docstring example)
    (1403, 3, 11): date(2024, 5, 31),   # 11 Khordad 1403 (the task example ۱۱ خرداد ۱۴۰۳)
    (1357, 11, 22): date(1979, 2, 11),  # 22 Bahman 1357 — the Islamic Revolution
    (1399, 12, 30): date(2021, 3, 20),  # last day of leap year 1399 (Esfand 30)
    (1403, 12, 30): date(2025, 3, 20),  # last day of leap year 1403 (Esfand 30)
    (1394, 12, 29): date(2016, 3, 19),  # 29 Esfand 1394 (non-leap end)
}


@pytest.mark.parametrize("jymd,expected", list(GOLDEN.items()))
def test_jalali_to_gregorian_golden(jymd, expected):
    jy, jm, jd = jymd
    assert _jalali_valid(jy, jm, jd, TODAY) == expected


def test_jalali_leap_year_esfand_validity():
    # 1403 IS a leap year -> Esfand has 30 days; 1402 is NOT -> 29. The impossible day
    # is REJECTED (skip-never-guess), never silently rolled over into the next month.
    assert _jalali_month_length(1403, 12) == 30
    assert _jalali_month_length(1402, 12) == 29
    assert _jalali_valid(1403, 12, 30, TODAY) == date(2025, 3, 20)  # valid leap day
    assert _jalali_valid(1402, 12, 30, TODAY) is None               # 30 Esfand in non-leap
    assert _jalali_valid(1403, 12, 31, TODAY) is None               # no 31st in Esfand
    assert _jalali_valid(1403, 7, 31, TODAY) is None                # Mehr has 30 days
    assert _jalali_valid(1403, 1, 32, TODAY) is None                # impossible day
    assert _jalali_valid(1403, 13, 1, TODAY) is None                # impossible month


# --------------------------------------------------------------------------- #
# Persian named + numeric Jalali dates through the extractor (fa-gated)        #
# --------------------------------------------------------------------------- #

def test_persian_named_jalali_dateline_extracts_correct_gregorian():
    assert _dates("۱۱ خرداد ۱۴۰۳", "fa") == [("2024-05-31", "day")]
    assert _dates("۱ فروردین ۱۴۰۳ نوروز بود.", "fa") == [("2024-03-20", "day")]
    assert _dates("۲۲ بهمن ۱۳۵۷ پیروزی انقلاب.", "fa") == [("1979-02-11", "day")]
    # A weekday prefix (شنبه) does not block the date; the year is present so it is exact.
    assert _dates("گزارش شنبه ۱۱ خرداد ۱۴۰۳ منتشر شد.", "fa") == [("2024-05-31", "day")]


def test_persian_jalali_month_year_is_month_precision():
    assert _dates("خرداد ۱۴۰۳", "fa") == [("2024-05-21", "month")]
    # Arabic-yeh spelling (ي U+064A) of ارديبهشت resolves without a normalisation pass.
    assert _dates("ارديبهشت ۱۴۰۳", "fa") == [("2024-04-20", "month")]


def test_persian_numeric_jalali_is_converted_not_fabricated():
    # THE FIX for a live fabrication: "۱۴۰۳/۰۳/۱۱" used to store 1403-03-11 CE (a medieval
    # date — 1403 passes the CE window). It now converts as Jalali to the correct Gregorian.
    assert _dates("تاریخ ۱۴۰۳/۰۳/۱۱ ثبت شد.", "fa") == [("2024-05-31", "day")]
    assert ("1403-03-11", "day") not in _dates("۱۴۰۳/۰۳/۱۱", "fa")
    # dash separator too (Persian ISO-style)
    assert _dates("۱۴۰۳-۰۳-۱۱", "fa") == [("2024-05-31", "day")]


def test_persian_gregorian_dates_still_resolve():
    # A Gregorian date written with Persian digits stays Gregorian (year out of the Jalali
    # range falls through to the ordinary numeric/ISO paths), and the Gregorian month names.
    assert _dates("۲۰۲۴/۰۶/۱۱", "fa") == [("2024-06-11", "day")]
    assert _dates("۲۰۲۴-۰۶-۱۱", "fa") == [("2024-06-11", "day")]
    assert _dates("۱۱ ژوئن ۲۰۲۴", "fa") == [("2024-06-11", "day")]


def test_fa_jalali_range_boundaries_route_numeric_correctly():
    # A numeric year inside the Jalali news range is Jalali; a Gregorian-range year is not.
    assert _FA_JY_MIN <= 1403 <= _FA_JY_MAX
    assert not (_FA_JY_MIN <= 2024 <= _FA_JY_MAX)


# --------------------------------------------------------------------------- #
# fa GATE + homograph safety — a Jalali token outside fa is skipped, never guessed
# --------------------------------------------------------------------------- #

def test_jalali_name_outside_fa_is_skipped_not_guessed():
    # The same Persian dateline in a NON-fa article yields nothing (the fa gate holds) —
    # the extractor never invents a date from another language's homographs.
    assert _dates("۱۱ خرداد ۱۴۰۳", "ar") == []
    assert _dates("۱۱ خرداد ۱۴۰۳", "en") == []
    assert _dates("۱۱ خرداد ۱۴۰۳", None) == []


def test_persian_homograph_months_need_an_adjacent_date():
    # تیر (arrow), مهر (affection/seal), دی — ordinary Persian words. With NO adjacent
    # day/year they must never fabricate a date, even inside a fa article.
    assert _dates("تیر به هدف خورد.", "fa") == []          # "the arrow hit the target"
    assert _dates("مهر و محبت فراوان بود.", "fa") == []    # "much affection and love"
    # A Jalali month + an absurd (Gregorian) year is rejected by the window check.
    assert _dates("خرداد ۲۰۲۴", "fa") == []               # Jalali year 2024 -> out of window


def test_persian_may_stays_withheld():
    # Persian "May" is مه / می — ultra-common words; withheld as a fabrication vector
    # (unchanged by this wave). A day+year next to them must NOT extract May.
    assert _dates("۵ مه ۲۰۲۴", "fa") == []
    assert _dates("۵ می ۲۰۲۴", "fa") == []


# --------------------------------------------------------------------------- #
# Hungarian — year-first named + spaced numeric                               #
# --------------------------------------------------------------------------- #

def test_hungarian_year_first_day_format():
    assert _dates("2024. június 11.", "hu") == [("2024-06-11", "day")]
    assert _dates("2024. június 11-én tartották.", "hu") == [("2024-06-11", "day")]
    assert _dates("1848. március 15.", "hu") == [("1848-03-15", "day")]
    # November/December share the English spelling and resolve too.
    assert _dates("2024. november 5.", "hu") == [("2024-11-05", "day")]


def test_hungarian_year_first_month_only():
    assert _dates("2024. június", "hu") == [("2024-06-01", "month")]
    assert _dates("A választás 2024. november hónapban lesz.", "hu") == [("2024-11-01", "month")]
    # A day present yields the day form (month-only never double-counts).
    assert _dates("2024. június 11.", "hu") == [("2024-06-11", "day")]


def test_hungarian_spaced_numeric():
    assert _dates("2024. 06. 11.", "hu") == [("2024-06-11", "day")]
    assert _dates("2024.06.11.", "hu") == [("2024-06-11", "day")]  # unspaced still works


def test_spaced_numeric_is_hu_gated():
    # The SPACED year-first numeric is hu-gated: in other languages "2024. N. N." is more
    # often a hierarchical list/version item than a date, so it must not fabricate one.
    assert _dates("Version 2024. 12. 31.", "de") == []
    assert _dates("see item 2024. 1. 5. below", "en") == []
    # The UNSPACED year-first numeric stays global (unchanged behaviour).
    assert _dates("2024.06.11", "en") == [("2024-06-11", "day")]


def test_hungarian_month_only_is_hu_gated():
    # The year-first-month-only read is hu-gated: an English sentence boundary
    # "…in 2024. March was cold" must NOT fabricate March 2024.
    assert _dates("It happened in 2024. March was cold.", "en") == []
    assert _dates("Released in 2020. December brought snow.", "en") == []
    # And the same shape is not read as a month in a non-hu language.
    assert _dates("2024. június", "en") == []


# --------------------------------------------------------------------------- #
# datediag LOCKSTEP — the probe mirrors the extractor's fa gate exactly        #
# --------------------------------------------------------------------------- #

def test_datediag_lockstep_fa_jalali_no_actionable_gap():
    text = "گزارش روز شنبه ۱۱ خرداد ۱۴۰۳ منتشر شد و در خرداد ۱۴۰۳ ادامه یافت."
    r = datediag.analyze_article(text, language="fa", anchor=ANCHOR, today=TODAY)
    assert r["n_extracted"] == 2                     # the day date + the month reference
    assert r["actionable_gap"] == 0                  # probe and extractor agree
    assert r["probe_by_kind"].get("month_name") == 2


def test_datediag_lockstep_numeric_fa_no_actionable_gap():
    r = datediag.analyze_article("ثبت در ۱۴۰۳/۰۳/۱۱ انجام شد.",
                                 language="fa", anchor=ANCHOR, today=TODAY)
    assert r["actionable_gap"] == 0
    assert ("2024-05-31", "day") in [(d["date"], d["precision"]) for d in r["extracted"]]


def test_datediag_lockstep_gated_token_outside_fa_is_not_a_phantom_gap():
    # The SAME Persian text in a non-fa article: the extractor skips it (fa-gated) AND the
    # fa-gated probe skips it, so there is no phantom, permanent per-language gap.
    text = "۱۱ خرداد ۱۴۰۳"
    r = datediag.analyze_article(text, language="ar", anchor=ANCHOR, today=TODAY)
    assert r["n_extracted"] == 0
    assert r["actionable_gap"] == 0
    # The probe flags the Jalali name only inside fa.
    assert any(h["kind"] == "month_name" for h in datediag.recall_probe(text, language="fa"))
    assert all(h["kind"] != "month_name" for h in datediag.recall_probe(text, language="ar"))


def test_persian_and_hungarian_are_in_month_vocab_langs():
    # Both languages are declared as having month vocabulary, so a low coverage reads as a
    # real gap rather than "no vocabulary" (the diagnostics honesty contract).
    assert "fa" in datediag.MONTH_VOCAB_LANGS
    assert "hu" in datediag.MONTH_VOCAB_LANGS


# --------------------------------------------------------------------------- #
# Fabrication regressions — adversarial-audit repros, 2026-07-09 (post-merge   #
# fix-forward of PR #590). Each of these once STORED a wrong date; the fix is  #
# a word/ZWNJ lookbehind on _FA_MY_RE + claim-on-ROUTE in the fa numeric       #
# router + a fa guard on day-first numerics with a Jalali-range year. The      #
# non-negotiable under test: SKIPPED, never guessed — an empty result is the   #
# only honest answer for every one of these inputs.                            #
# --------------------------------------------------------------------------- #


def test_fa_month_name_word_tail_never_fabricates():
    # دی (Dey) is the tail of common words: عادی "ordinary" / اقتصادی "economic".
    # A bare Jalali year after such a word used to store Dey 1403 (2024-12-21).
    assert _dates("سال عادی ۱۴۰۳ بود.", "fa") == []
    assert _dates("رشد اقتصادی ۱۴۰۳ کند بود.", "fa") == []
    # The REAL month usage (space-preceded) still extracts at month precision.
    assert _dates("در دی ۱۴۰۳ رخ داد", "fa") == [("2024-12-21", "month")]


def test_fa_invalid_numeric_jalali_is_skipped_not_read_as_ce():
    # 30 Esfand 1402 does not exist (1402 is not a Jalali leap year). This used
    # to fall through to the generic numeric loop and store 1402-12-30 CE — a
    # medieval date fabricated from a typo'd/impossible Jalali date.
    assert _dates("۱۴۰۲/۱۲/۳۰", "fa") == []
    assert _dates("1402/12/30", "fa") == []  # ASCII digits take the same path
    # The valid leap-year counterpart still converts exactly.
    assert _dates("۱۴۰۳/۱۲/۳۰", "fa") == [("2025-03-20", "day")]


def test_fa_out_of_window_jalali_is_skipped_not_read_as_ce():
    # Jalali 1420 = 2041 CE, outside the acceptance window: the router must
    # claim-and-skip, never let the generic loop store 1420-01-01 CE.
    assert _dates("افق ۱۴۲۰/۰۱/۰۱ اعلام شد", "fa") == []


def test_fa_day_first_numeric_with_jalali_year_is_skipped_not_guessed():
    # Persian numeric convention is year-first; a day-first form with a
    # Jalali-range year is order-ambiguous. It used to be read by the generic
    # DMY loop as 1403-03-11 CE; now it is claimed and skipped — never converted
    # on an assumed field order, never read as CE.
    assert _dates("۱۱/۰۳/۱۴۰۳", "fa") == []
    # Day-first with a GREGORIAN year is unaffected (the normal DMY path).
    assert _dates("۱۱/۰۳/۲۰۲۴", "fa") == [("2024-03-11", "day")]


def test_fa_fabrication_fixes_keep_datediag_in_lockstep():
    # The probe imports the SAME compiled _FA_MY_RE, so the tightened lookbehind
    # propagates: neither the extractor nor the probe fires on the word-tail
    # text — no phantom per-language gap is reported.
    r = datediag.analyze_article("سال عادی ۱۴۰۳ بود.", language="fa",
                                 anchor=ANCHOR, today=TODAY)
    assert r["n_extracted"] == 0
    assert all(h["kind"] != "month_name"
               for h in datediag.recall_probe("سال عادی ۱۴۰۳ بود.", language="fa"))
