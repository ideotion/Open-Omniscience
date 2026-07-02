"""Date-extractor fabrication fixes (field F4 follow-up, 2026-07-01).

A systematic probe of the extractor found five ACTIVE wrong-date bugs — forms
where the anchored no-year path (or a homograph month entry) stored an INVENTED
date on the production call (anchor + language passed, exactly as ingest does):

  1. Era-name years: 昭和20年8月15日 (15 Aug 1945) stored as 2026-08-15 — the
     unparsed era year left the 月日 tail to the anchored resolver. Fixed by
     exact era conversion (Reiwa/Heisei/Shōwa/Taishō/Meiji + ROC 民國) plus a
     preceding-年 suppression guard for eras we cannot parse.
  2. Un-mirrored year connectors: "στις 11 Σεπτεμβρίου του 2001" (el) and
     "في 11 سبتمبر من عام 2001" (ar) stored as 2026-09-11 — the no-year
     lookahead did not know the connector, so the anchored path claimed a date
     whose true year was IN the text. Fixed by connector support in the
     full-date patterns MIRRORED into the no-year lookaheads (lockstep rule).
  3. Homograph months: Croatian "5. listopada 2024" (5 OCTOBER) stored as
     5 November via the Polish table entry. Fixed by the language-gated
     override map: a hint picks the meaning, no hint -> skipped, never guessed.
  4. Ranges: "June 11-13, 2026" with a 2027 anchor stored 2027-06-11 —
     overriding the explicit in-text year. Fixed by explicit range patterns
     (both endpoints extracted) + the widened no-year lookahead.
  5. Dual-named Arabic months: "في 11 سبتمبر/أيلول 2001" anchored to 2026.
     Fixed by the Levantine vocabulary + the slash form (months must AGREE).

Every fix is suppression-or-exact-conversion — nothing here guesses. Pure
module, runs in the sandbox and CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap.dateextract import extract_dates

TODAY = date(2026, 6, 22)
ANCHOR = date(2026, 6, 10)


def _dates(text, lang=None, anchor=ANCHOR):
    return [
        (c["date"], c["precision"])
        for c in extract_dates(text, today=TODAY, anchor=anchor, language=lang)
    ]


# ---- 1. era-name years: exact conversion, never anchor-resolution ---------- #

def test_japanese_era_dates_convert_exactly():
    assert _dates("戦争は昭和20年8月15日に終わった。", "ja") == [("1945-08-15", "day")]
    assert _dates("会議は令和6年6月11日に開かれた。", "ja") == [("2024-06-11", "day")]
    assert _dates("大正元年9月1日の関東の話。", "ja") == [("1912-09-01", "day")]  # 元 = year 1
    assert ("2019-04-01", "month") in _dates("平成31年4月に改元された。", "ja")


def test_roc_era_dates_convert_exactly():
    assert _dates("民國113年6月11日舉行會議。", "zh") == [("2024-06-11", "day")]


def test_unparseable_year_prefix_suppresses_anchored_md():
    # A 2-digit year or an unknown era name before 月日 means an explicit year we
    # could NOT parse — suppress, never resolve near the publication year.
    assert _dates("会議は24年6月11日に開かれた。", "ja") == []
    assert _dates("文久2年5月1日の出来事。", "ja") == []  # era outside the table
    # ...while a genuinely year-less form still anchors (existing behavior).
    assert _dates("会議は6月11日に開かれた。", "ja") == [("2026-06-11", "day")]


# ---- 2. year/day connectors, mirrored into the no-year lookaheads ---------- #

def test_connector_forms_extract_the_true_year_not_the_anchor():
    # Both were MEASURED fabrications: stored 2026-09-11 before the fix.
    assert _dates("Η επίθεση έγινε στις 11 Σεπτεμβρίου του 2001.", "el") == [
        ("2001-09-11", "day")
    ]
    assert _dates("وقع الهجوم في 11 سبتمبر من عام 2001.", "ar") == [("2001-09-11", "day")]


def test_connector_recall_gains():
    assert _dates("The vote is set for the 3rd of June 2026.", "en") == [("2026-06-03", "day")]
    assert ("2024-01-01", "month") in _dates("It was signed in January of 2024.", "en")
    assert ("2024-05-01", "month") in _dates("El informe de mayo de 2024 fue claro.", "es")


def test_english_homograph_months_never_take_the_of_form():
    # "the march of 2024 protesters" is a procession, not March 2024 — miss over invent.
    assert _dates("The march of 2024 protesters filled the square.", "en") == []
    assert _dates("He may of 2024 said nothing.", "en") == []


# ---- 3. homograph months resolve only via the language hint ---------------- #

def test_croatian_listopada_is_october_not_november():
    # MEASURED live wrong-month bug: stored 2024-11-05 before the fix.
    assert _dates("Sastanak je bio 5. listopada 2024.", "hr") == [("2024-10-05", "day")]
    assert _dates("Spotkanie odbyło się 5 listopada 2024 roku.", "pl") == [("2024-11-05", "day")]
    assert _dates("Schůzka byla 5. listopadu 2024.", "cs") == [("2024-11-05", "day")]


def test_homograph_month_without_language_hint_is_skipped_not_guessed():
    assert _dates("5 listopada 2024.", None) == []


def test_gated_marta_and_mac():
    assert _dates("Sastanak je bio 5. marta 2024.", "sr") == [("2024-03-05", "day")]
    assert _dates("Mesyuarat pada 5 Mac 2024 di bandar.", "ms") == [("2024-03-05", "day")]
    # The homograph readings stay protected:
    assert _dates("Marta 2024 es una gran persona.", "es") == []
    assert _dates("The new Mac 2024 lineup launched.", "en") == []


# ---- 4. explicit ranges: both endpoints, never the anchor's year ----------- #

def test_range_extracts_both_endpoints_with_the_in_text_year():
    # MEASURED fabrication: with a 2027 anchor this stored 2027-06-11.
    far = date(2027, 1, 10)
    got = _dates("The summit runs June 11-13, 2026 in Geneva.", "en", anchor=far)
    assert got == [("2026-06-11", "day"), ("2026-06-13", "day")]
    assert _dates("The summit runs 11–13 June 2026 in Geneva.", "en") == [
        ("2026-06-11", "day"),
        ("2026-06-13", "day"),
    ]
    assert _dates("Held between 11 and 13 June 2026.", "en") == [
        ("2026-06-11", "day"),
        ("2026-06-13", "day"),
    ]


def test_reversed_range_is_skipped_not_guessed():
    assert _dates("Numbers June 13-11, 2026 follow.", "en", anchor=date(2027, 1, 10)) == []


# ---- 5. Levantine months + the dual slash-joined form ---------------------- #

def test_levantine_months_extract():
    assert _dates("وقع الهجوم في 11 أيلول 2001.", "ar") == [("2001-09-11", "day")]
    assert ("2024-07-01", "month") in _dates("صدر التقرير في تموز 2024.", "ar")


def test_dual_named_month_both_orders_agree():
    # Pan-Arab convention: international/Levantine names slash-joined.
    assert _dates("في 11 سبتمبر/أيلول 2001 وقع الهجوم.", "ar") == [("2001-09-11", "day")]
    assert _dates("في 11 أيلول/سبتمبر 2001 وقع الهجوم.", "ar") == [("2001-09-11", "day")]


def test_dual_named_month_disagreement_never_yields_a_day():
    # "11 June/July 2024": ambiguous day — no day row may appear; the explicit
    # adjacent "July 2024" month reference is honest and may.
    got = _dates("On 11 June/July 2024 something happened.", "en")
    assert all(p != "day" for _, p in got)


def test_nisan_and_ab_stay_withheld():
    # Deliberately WITHHELD fabrication vectors (Nissan model years; fa/ur "water").
    assert _dates("اشترى سيارة نيسان 2023 جديدة.", "ar") == []
    assert _dates("آب 2023 کا ذکر تھا۔", "ur") == []


# ---- second adversarial round (verifier-found defects in the first cut) ---- #

def test_bare_cardinal_of_is_a_counter_reference_not_a_day():
    # "Page 3 of May 2024" invented day 3 in the first cut; the "of" connector
    # now REQUIRES the ordinal ("the 3rd of June"), so counters stay counters.
    assert _dates("Page 3 of May 2024 covers the storm.", "en") == [("2024-05-01", "month")]
    assert _dates("Chapter 11 of September 2001 archives.", "en") == [("2001-09-01", "month")]
    assert _dates("See page 3 of May for details.", "en") == []  # no anchored invention
    # ...while the ordinal forms keep working, with and without a year:
    assert _dates("The vote is set for the 3rd of June 2026.", "en") == [("2026-06-03", "day")]
    assert _dates("It happens on the 3rd of June.", "en") == [("2026-06-03", "day")]


def test_tamuz_is_gated_to_arabic():
    # تموز is a real Persian word ("midsummer heat") — ungated it fabricated
    # month rows from fa prose, incl. Solar-Hijri years. ar-gated only.
    assert _dates("آفتاب تموز 2023 بر شهر می‌تابید.", "fa") == []
    assert _dates("در گرمای تموز ۱۴۰۳ کشاورزان...", "fa") == []
    assert ("2024-07-01", "month") in _dates("صدر التقرير في تموز 2024.", "ar")


def test_override_months_never_take_the_month_first_order():
    # "Marta 30 godina kasnije" (name + number) fabricated March 30; homograph
    # months are all day-first genitives, so the month-first order is excluded.
    assert _dates("Marta 30 godina kasnije.", "sr", anchor=date(2026, 3, 15)) == []
    assert _dates("Sastanak je bio 30. marta 2024.", "sr") == [("2024-03-30", "day")]


def test_cjk_deictic_years_resolve_exactly():
    # 今年 (this year) was suppressed by the first cut's blunt 年-guard — the
    # commonest ja/zh date form; deictics now resolve EXACTLY (and 昨年 gets the
    # true previous year, which the pre-slice code got wrong via nearest-year).
    assert _dates("今年6月11日に発表された。", "ja") == [("2026-06-11", "day")]
    assert _dates("昨年6月11日に発表された。", "ja") == [("2025-06-11", "day")]
    assert _dates("去年6月11日，政府宣布。", "zh") == [("2025-06-11", "day")]
    assert _dates("来年6月11日に開催される。", "ja") == [("2027-06-11", "day")]
    # punctuation between an era year and the 月日 tail still suppresses:
    assert _dates("令和6年、6月11日に開かれた。", "ja") == []
    assert _dates("昭和0年8月15日の話。", "ja") == []  # gengō year 0 does not exist


def test_range_sibling_spellings_never_anchor_the_first_endpoint():
    far = date(2027, 7, 1)
    # Each of these fabricated an anchored 2027-06-11 before; now every row (if
    # any) carries the explicit in-text year — a partial miss beats an invention.
    for text in (
        "held June 11-June 13, 2026.",
        "held June 11 to 13, 2026.",
        "on June 11 and 12, 2026.",
        "overnight June 11/12, 2026.",
        "filed June 11/2026 by desk.",
    ):
        got = _dates(text, "en", anchor=far)
        assert all(dt.startswith("2026") for dt, _ in got), f"{text!r} -> {got!r}"


def test_cross_month_range_never_invents_an_endpoint():
    # "May 11-13 June 2026" means May 11 -> June 13; the first cut invented
    # June 11. Now the cross-month shape is skipped/suppressed — only explicit
    # dates survive.
    got = _dates("runs May 11-13 June 2026.", "en", anchor=date(2027, 7, 1))
    assert ("2026-06-11", "day") not in got
    assert all(dt.startswith("2026") for dt, _ in got)
    got2 = _dates("from 11 May – 13 June 2026.", "en", anchor=date(2027, 2, 1))
    assert all(dt.startswith("2026") for dt, _ in got2)


def test_asymmetric_dot_range_is_a_sentence_boundary():
    # "aged 5-7. June 2026" — the dot belongs to the sentence, not a German
    # ordinal pair; the range must not fire (the German pair keeps working).
    got = _dates("for children aged 5-7. June 2026 brings the new season.", "en")
    assert ("2026-06-05", "day") not in got
    assert _dates("vom 5.-7. Juni 2026 in Berlin.", "de") == [
        ("2026-06-05", "day"),
        ("2026-06-07", "day"),
    ]


def test_sl_bs_listopad_rulings():
    # sl: archaic listopad = November (restores the pre-slice recall);
    # bs: Croat usage = October (the pre-slice November was wrong).
    assert _dates("Dogodek je bil 5. listopada 2024.", "sl") == [("2024-11-05", "day")]
    assert _dates("Sastanak je 5. listopada 2024.", "bs") == [("2024-10-05", "day")]


# ---- regression: the fixes never widen what the anchored path may claim ---- #

def test_anchored_no_year_forms_still_work():
    assert _dates("The meeting is on 11 September.", "en") == [("2026-09-11", "day")]
    assert _dates("La réunion a eu lieu le 11 juin.", "fr") == [("2026-06-11", "day")]


def test_full_dates_still_beat_the_anchored_path():
    # The lockstep mirror: an explicit year in ANY accepted continuation shape
    # blocks the no-year classification.
    assert _dates("On 11 September 2001 the towers fell.", "en") == [("2001-09-11", "day")]
    assert _dates("On September 11, 2001 the towers fell.", "en") == [("2001-09-11", "day")]
