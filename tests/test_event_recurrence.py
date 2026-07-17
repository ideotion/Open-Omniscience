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


def test_next_occurrence_leap_day_skips_a_non_leap_year_instead_of_aborting():
    """Audit finding 2026-07-17: a fixed-date event whose day doesn't exist in a
    PARTICULAR scanned year (a Feb 29 "leap day" entry, in a non-leap year) used
    to abort the WHOLE scan (`return None`) instead of trying the next candidate
    year -- so a genuine recurring leap-day event reported "no next occurrence"
    in any non-leap starting year, even though a later year in the very same
    scanned window has a perfectly valid answer. 2027 is not a leap year; 2028
    is -- the old code returned None here, the fix correctly finds 2028-02-29."""
    today = date(2027, 3, 1)  # scan range is [2027 (non-leap), 2028 (leap)]
    assert catalog._next_occurrence(2, 29, today) == "2028-02-29"


def test_span_for_leap_day_start_skips_a_non_leap_year_instead_of_aborting():
    """Same fix, for _span_for's 3-year scan window."""
    e = {"month": 2, "day": 29, "end_month": 3, "end_day": 1}
    # 2027 (today.year - 1) and 2027's neighbours -- only 2028 is a leap year.
    s = catalog._span_for(e, date(2028, 1, 15))
    assert s is not None
    assert s["start"] == "2028-02-29"


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


def test_floating_nth_weekday_recurrence():
    """Floating dates — '3rd Tuesday of March', 'last Monday of May' (maintainer
    2026-06-18: many recurring events are defined by an Nth weekday, not a fixed
    day). The date is computed per year; a non-existent Nth (a 5th Friday) is
    skipped to the next year, never invented."""
    from src.events.catalog import _coerce_weekday, _next_occurrence, nth_weekday

    assert nth_weekday(2026, 3, 1, 3) == date(2026, 3, 17)   # 3rd Tuesday of March
    assert nth_weekday(2026, 5, 0, -1) == date(2026, 5, 25)  # last Monday of May
    assert nth_weekday(2026, 2, 4, 5) is None                # no 5th Friday in Feb 2026
    # the next upcoming occurrence rolls to next year once this year's is past
    assert _next_occurrence(3, None, date(2026, 6, 1), weekday=1, week=3) == "2027-03-16"
    assert _next_occurrence(3, None, date(2026, 1, 1), weekday=1, week=3) == "2026-03-17"
    # weekday accepts a name or an int; unknown -> None (never guessed)
    assert _coerce_weekday("tuesday") == 1 and _coerce_weekday("Tue") == 1 and _coerce_weekday(1) == 1
    assert _coerce_weekday("nope") is None


def test_floating_event_flows_through_agenda(monkeypatch):
    """A floating catalog entry surfaces in agenda() with the right next_occurrence."""
    import src.events.catalog as catalog

    monkeypatch.setattr(catalog, "load_events", lambda: [
        {
            "title": "Third Tuesday of March", "calendar": "civic", "category": "civic",
            "country": None, "region": None, "cadence": "annual",
            "month": 3, "day": None, "weekday": 1, "week": 3,
            "end_month": None, "end_day": None, "origin_year": None, "until_year": None,
            "confirmed": True, "official_url": "https://example.org", "tags": [], "note": None,
        }
    ])
    out = catalog.agenda(today=date(2026, 1, 1))
    assert out and out[0]["next_occurrence"] == "2026-03-17"
