"""Tests for explicit-date extraction from article text (temporal map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap.dateextract import extract_dates

TODAY = date(2026, 6, 9)


def _dates(text):
    return [(c["date"], c["precision"]) for c in extract_dates(text, today=TODAY)]


def test_iso_and_full_forms():
    assert ("2001-09-11", "day") in _dates("It happened on 2001-09-11 downtown.")
    assert ("2001-09-11", "day") in _dates("On 11 September 2001 the towers fell.")
    assert ("2001-09-11", "day") in _dates("On September 11, 2001 the towers fell.")
    assert ("2001-09-11", "day") in _dates("Filed 11th September 2001 by our desk.")


def test_month_precision_and_abbreviations():
    assert ("2003-03-01", "month") in _dates("The invasion began in March 2003.")
    assert ("2003-03-01", "month") in _dates("Back in Mar. 2003 things changed.")
    # 'sept' must win over 'sep'
    assert ("2001-09-01", "month") in _dates("Sept 2001 was a turning point.")


def test_day_match_suppresses_inner_month_match():
    # 'September 11, 2001' should yield ONE day candidate, not also 'September 2001'
    got = _dates("September 11, 2001 is remembered.")
    assert got == [("2001-09-11", "day")]


def test_no_bare_years_or_relative():
    assert _dates("Revenue hit 2000 units and the 1945 bombing is history.") == []
    assert _dates("It happened last Tuesday, the report said.") == []
    assert _dates("See page 1999 for details.") == []


def test_invalid_dates_rejected():
    # 'Month DD, YYYY' with an impossible day and no bare 'Month YYYY' adjacency -> nothing
    assert _dates("Dated February 30, 2001 supposedly.") == []
    # an impossible 'DD Month YYYY' degrades to the month it still names — never a bad day,
    # never dropped entirely (honest: the text does reference that month).
    assert _dates("The 31 February 2001 memo.") == [("2001-02-01", "month")]


def test_out_of_range_year_rejected():
    assert _dates("A prophecy for January 3000.") == []  # too far ahead
    assert _dates("Filed 2099-01-01 in the system.") == []  # >today+5


def test_dedup_and_order_and_provenance():
    text = "First March 2003, later 2003-03-01 again, then April 2004."
    cands = extract_dates(text, today=TODAY)
    iso = [c["date"] for c in cands]
    # 2003-03-01 appears via both 'March 2003' (month) and ISO (day) -> distinct precisions kept,
    # but ordered by first appearance; April 2004 comes last.
    assert iso[-1] == "2004-04-01"
    assert all("text" in c and c["text"] for c in cands)  # provenance snippet present


def test_empty_and_limit():
    assert extract_dates("", today=TODAY) == []
    many = " ".join(f"{i} January 2001" for i in range(1, 20))
    assert len(extract_dates(many, today=TODAY, limit=3)) == 3
