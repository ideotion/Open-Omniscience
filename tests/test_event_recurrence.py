"""Agenda recurrence schema: origin/until years + month-spans (Group / RC agenda content).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The first deliverable of the RC-BLOCKING agenda-content row is the recurrence SCHEMA:
an event may declare an ACTIVE year range (origin_year/until_year — "since 1950", or an
observance that has ended) and a MONTH-SPAN (end_month/end_day — "Dry January", a
multi-day summit) that may wrap the year end. These are ADDITIVE + honest: a span is
built only from explicit start+end, never guessed, and out-of-range occurrences are
suppressed. Pure logic, no network, no data fabrication.
"""

from __future__ import annotations

from datetime import date

from src.events import catalog


def test_active_range_inclusive_and_open_bounds():
    assert catalog._in_active_range(2026, None, None) is True
    assert catalog._in_active_range(2026, 2027, None) is False  # before it began
    assert catalog._in_active_range(2027, 2027, None) is True   # the origin year is active
    assert catalog._in_active_range(2016, None, 2015) is False  # after it ended
    assert catalog._in_active_range(2015, 2010, 2015) is True   # until-year inclusive


def test_span_end_same_year_and_wrap():
    # A span ending later in the same year.
    s = date(2026, 1, 1)
    assert catalog._span_end_date(s, 1, 31) == date(2026, 1, 31)
    # A span whose end is calendar-earlier than the start WRAPS into the next year.
    s2 = date(2026, 12, 20)
    assert catalog._span_end_date(s2, 1, 5) == date(2027, 1, 5)
    # No end stated -> no span.
    assert catalog._span_end_date(s, None, None) is None
    # Invalid end date -> None (never a fabricated span).
    assert catalog._span_end_date(s, 2, 31) is None


def test_next_occurrence_respects_origin_year():
    today = date(2026, 6, 1)
    # An event that begins in 2028 has no 2026/2027 instance — next is 2028.
    assert catalog._next_occurrence(3, 8, today, origin_year=2028) == "2028-03-08"
    # An event that ENDED in 2024 has no future occurrence.
    assert catalog._next_occurrence(3, 8, today, until_year=2024) is None
    # Plain fixed-date still works (next March 8 from June 2026 is 2027-03-08).
    assert catalog._next_occurrence(3, 8, today) == "2027-03-08"
    # Not a fixed date.
    assert catalog._next_occurrence(None, None, today) is None


def test_span_for_active_and_upcoming():
    # "Dry January": Jan 1 -> Jan 31. Mid-January today => active.
    e = {"month": 1, "day": 1, "end_month": 1, "end_day": 31}
    s = catalog._span_for(e, date(2026, 1, 15))
    assert s == {"start": "2026-01-01", "end": "2026-01-31", "active": True}
    # After this year's span ends, the NEXT year's span is returned, not active.
    s2 = catalog._span_for(e, date(2026, 6, 1))
    assert s2["start"] == "2027-01-01" and s2["end"] == "2027-01-31" and s2["active"] is False
    # A year-wrapping span active across New Year.
    ew = {"month": 12, "day": 20, "end_month": 1, "end_day": 5}
    sw = catalog._span_for(ew, date(2026, 12, 31))
    assert sw["start"] == "2026-12-20" and sw["end"] == "2027-01-05" and sw["active"] is True
    # No end fields => no span.
    assert catalog._span_for({"month": 1, "day": 1}, date(2026, 1, 15)) is None


def test_agenda_exposes_span_and_origin(monkeypatch):
    synthetic = {
        "calendars": [{"key": "test", "name": "Test", "category": "civic"}],
        "events": [
            {"title": "Future Summit", "calendar": "test", "category": "civic",
             "month": 5, "day": 1, "origin_year": 2030, "confirmed": True,
             "official_url": "https://example.org/a"},
            {"title": "Awareness Month", "calendar": "test", "category": "civic",
             "month": 4, "day": 1, "end_month": 4, "end_day": 30, "confirmed": True,
             "official_url": "https://example.org/b"},
        ],
    }
    monkeypatch.setattr(catalog, "_raw", lambda: synthetic)
    catalog.load_events.cache_clear()
    try:
        items = catalog.agenda(today=date(2026, 6, 1))
        by_title = {i["title"]: i for i in items}
        # Future Summit: origin 2030 surfaced, next occurrence is 2030 (not 2026/2027).
        assert by_title["Future Summit"]["origin_year"] == 2030
        assert by_title["Future Summit"]["next_occurrence"] == "2030-05-01"
        # Awareness Month: carries a span; from June 2026 the next span is April 2027.
        span = by_title["Awareness Month"]["span"]
        assert span["start"] == "2027-04-01" and span["end"] == "2027-04-30"
    finally:
        catalog.load_events.cache_clear()
