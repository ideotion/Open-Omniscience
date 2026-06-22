"""Date-vocabulary additions for the remainder field-test languages (2026-06-22).

uk/et/ur gained month names; vi gained the "tháng N" number-pattern; th gained Thai
month names with Buddhist-Era -> CE conversion. Each gap was confirmed missing before
this change (date diagnostics). A month/number only ever yields a date when a day or a
year sits adjacent, so vocabulary raises recall without inventing dates from prose.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap.dateextract import extract_dates

TODAY = date(2026, 6, 22)
ANCHOR = date(2024, 6, 10)


def _dates(text, language=None, anchor=None):
    return [
        (c["date"], c["precision"])
        for c in extract_dates(text, today=TODAY, anchor=anchor, language=language)
    ]


def test_ukrainian_months_cyrillic():
    # genitive (the date form), locative ("у вересні"), and nominative+year all resolve
    assert ("2024-05-05", "day") in _dates("Зустріч відбулась 5 травня 2024 року.", "uk")
    assert ("2023-09-01", "month") in _dates("Подія сталася у вересні 2023 року.", "uk")
    assert ("2022-02-24", "day") in _dates("Вторгнення почалося 24 лютого 2022.", "uk")


def test_estonian_specific_months():
    assert ("2024-01-05", "day") in _dates("Kohtumine toimus 5. jaanuar 2024.", "et")
    assert ("2023-12-05", "day") in _dates("5. detsember 2023 oli tähtis.", "et")
    assert ("2024-03-01", "month") in _dates("Aruanne ilmus märts 2024.", "et")


def test_urdu_months_arabic_script():
    assert ("2024-03-05", "day") in _dates("اجلاس 5 مارچ 2024 کو ہوا۔", "ur")
    # Eastern-Arabic digits parse the same way
    assert ("2023-12-25", "day") in _dates("یہ ۲۵ دسمبر ۲۰۲۳ کو ہوا۔", "ur")


def test_vietnamese_thang_pattern():
    # "ngày D tháng M năm Y" full date; the month is a NUMBER, not a name
    assert ("2024-05-05", "day") in _dates("Cuộc họp diễn ra ngày 5 tháng 5 năm 2024.", "vi")
    # "tháng M năm Y" and "tháng M/Y" -> month precision
    assert ("2023-09-01", "month") in _dates("Báo cáo tháng 9 năm 2023.", "vi")
    assert ("2024-03-01", "month") in _dates("Sự kiện vào tháng 3/2024.", "vi")
    # no-year "ngày D tháng M" resolves against the anchor (publication date)
    assert ("2024-05-05", "day") in _dates("Sự kiện ngày 5 tháng 5.", "vi", anchor=ANCHOR)


def test_thai_buddhist_era_conversion():
    # BE 2567 -> CE 2024 (the common Thai convention)
    assert ("2024-01-05", "day") in _dates("การประชุมจัดขึ้นเมื่อ 5 มกราคม 2567", "th")
    # "พ.ศ." (B.E.) marker + month precision
    assert ("2023-09-01", "month") in _dates("รายงานเดือน กันยายน พ.ศ. 2566", "th")
    # a Thai-script month with a CE year is kept as-is (some Thai sites use CE)
    assert ("2024-01-05", "day") in _dates("ประชุม 5 มกราคม 2024", "th")


def test_no_fabricated_date_from_a_bare_month_word():
    # A month name with NO adjacent day/year never yields a date (recall, not invention).
    assert _dates("Подія сталася у травні.", "uk") == []
    assert _dates("Cuộc họp vào tháng tới.", "vi") == []  # "tháng tới" = next month, no number
