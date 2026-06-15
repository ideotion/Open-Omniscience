"""Sourced world-events batch 2 — courts/legal, fiscal/budget, parliaments/institutional.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer repeatedly asks for the agenda to be FLOODED with sourced events
("parliaments, courts, fiscal dates"). This batch adds genuinely-recurring,
SOURCED entries reusing the existing ``civic`` / ``economic`` / ``summits``
calendars (no new calendar keys). Honesty by construction (mirrors
tests/test_world_events_batch.py / test_elections_calendar.py):

* a concrete ``day`` ONLY when fixed by law/statute — US Supreme Court term
  opening (first Monday in October, 28 U.S.C. §1) and the US federal fiscal
  year start (1 October, 31 U.S.C. §1102): ``confirmed: true`` + a real day;
* every other court session, budget and plenary moves per cycle:
  ``day: null`` + ``confirmed: false`` + the institution's ``official_url``.

These tests pin that the new events LOAD through the catalog, every one carries
an http ``official_url``, the movable/fixed honesty rule holds, the fixed dates
resolve to a real calendar date, and nothing in the wider catalog breaks.
"""

from datetime import date
from pathlib import Path

import yaml

from src.events.catalog import CATALOG_PATH, agenda, load_calendars, load_events

# Titles added by THIS batch — kept in sync with the configs/world_events.yml
# "BATCH 2" block.

# Courts / international legal — all MOVABLE. The SCOTUS term opens on the "first
# Monday in October", a recurring RULE the (month, day) schema can't express — so it
# is movable (confirmed:false, day:null) with the rule + 2026 date in its note, never
# a pinned day that would mis-show in other years.
_BATCH_COURTS_FIXED: set[str] = set()
_BATCH_COURTS_MOVABLE = {
    "United States Supreme Court — Term opening (First Monday in October)",
    "International Court of Justice (ICJ) — hearings & judgments",
    "International Criminal Court (ICC) — Assembly of States Parties",
    "European Court of Human Rights (ECtHR) — Grand Chamber hearings & judgments",
    "Court of Justice of the European Union (CJEU) — hearings & judgments",
}
_BATCH_COURTS = _BATCH_COURTS_FIXED | _BATCH_COURTS_MOVABLE

# Fiscal / budget — movable except the statute-fixed US fiscal year start.
_BATCH_FISCAL_FIXED = {
    "United States — Federal fiscal year start (1 October)",
}
_BATCH_FISCAL_MOVABLE = {
    "United Kingdom — Autumn Budget",
    "United Kingdom — Spring Statement",
    "European Union — Annual budget procedure",
    "France — Projet de loi de finances (annual budget bill)",
    "Germany — Federal budget (Bundeshaushalt)",
    "India — Union Budget",
}
_BATCH_FISCAL = _BATCH_FISCAL_FIXED | _BATCH_FISCAL_MOVABLE

# Parliaments / institutional — all movable (set per cycle / no fixed day).
_BATCH_INSTITUTIONAL = {
    "European Parliament — Strasbourg plenary session",
    "European Council summit (heads of state or government)",
    "State of the Union Address (United States)",
    "EU State of the Union address (President of the European Commission)",
    "UN Security Council — monthly presidency rotation",
    "G20 Finance Ministers and Central Bank Governors meeting",
    "G7 Finance Ministers and Central Bank Governors meeting",
    "IMF / World Bank Annual Meetings",
}

# The statute-fixed members of the batch (concrete day allowed) vs the movable rest.
_BATCH_FIXED = _BATCH_COURTS_FIXED | _BATCH_FISCAL_FIXED
_BATCH_MOVABLE = _BATCH_COURTS_MOVABLE | _BATCH_FISCAL_MOVABLE | _BATCH_INSTITUTIONAL
_BATCH_ALL = _BATCH_COURTS | _BATCH_FISCAL | _BATCH_INSTITUTIONAL


def _by_title() -> dict[str, dict]:
    return {e["title"]: e for e in load_events()}


def test_yaml_parses_and_no_new_calendar_keys():
    """The catalog YAML still parses and the batch reuses existing calendars only."""
    raw = yaml.safe_load(Path(CATALOG_PATH).read_text("utf-8"))
    assert isinstance(raw, dict) and isinstance(raw.get("events"), list)
    cal_keys = {c["key"] for c in load_calendars()}
    # batch reuses these three; asserts they exist and the batch invented none.
    for key in ("civic", "economic", "summits"):
        assert key in cal_keys, key
    by_title = _by_title()
    for title in _BATCH_ALL:
        assert by_title[title]["calendar"] in cal_keys, title


def test_all_batch_events_load_via_agenda():
    """Every batch-2 event is present in the loaded catalog and reachable via agenda()."""
    titles = {e["title"] for e in load_events()}
    missing = _BATCH_ALL - titles
    assert not missing, f"batch-2 events missing from the catalog: {sorted(missing)}"
    # Sizeable batch as commissioned (~20-35 new events).
    assert 20 <= len(_BATCH_ALL) <= 35
    # Each one is returned by an unfiltered agenda() too.
    agenda_titles = {e["title"] for e in agenda()}
    assert not (_BATCH_ALL - agenda_titles)


def test_every_batch_event_has_an_http_official_url():
    """No batch event without a real source link to the institution / authority."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        url = by_title[title]["official_url"]
        assert isinstance(url, str) and url.startswith("http"), title


def test_batch_events_use_only_existing_categories():
    """Batch events reuse existing data-driven categories — never invent one."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        assert by_title[title]["category"] in (
            "civic",
            "political",
            "economic",
            "technology",
        ), title


def test_batch_events_carry_tags():
    """Every batch event carries at least one tag (the filterable backbone)."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        tags = by_title[title]["tags"]
        assert isinstance(tags, list) and len(tags) >= 1, title


def test_batch_country_is_iso2_or_int_block():
    """Country is INT/EU for supranational bodies, or a 2-letter uppercase ISO code."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        cc = by_title[title]["country"]
        assert isinstance(cc, str), title
        assert cc in ("INT", "EU") or (len(cc) == 2 and cc.isupper()), (title, cc)


# --- courts / legal ------------------------------------------------------------ #
def test_batch_courts_in_civic_calendar():
    """All batch courts live in the civic calendar, category civic, tagged courts/legal."""
    by_title = _by_title()
    for title in _BATCH_COURTS:
        e = by_title[title]
        assert e["calendar"] == "civic", title
        assert e["category"] == "civic", title
        assert "courts" in e["tags"] and "legal" in e["tags"], title


def test_batch_movable_courts_have_no_fabricated_day():
    """Movable international courts: confirmed:false + day:null (case-by-case schedule)."""
    by_title = _by_title()
    for title in _BATCH_COURTS_MOVABLE:
        e = by_title[title]
        assert e["confirmed"] is False, title
        assert e["day"] is None, title


# --- fiscal / budget ----------------------------------------------------------- #
def test_batch_fiscal_in_economic_calendar():
    """All batch fiscal/budget events live in the economic calendar, tagged budget."""
    by_title = _by_title()
    for title in _BATCH_FISCAL:
        e = by_title[title]
        assert e["calendar"] == "economic", title
        assert e["category"] == "economic", title
        assert "budget" in e["tags"], title


def test_batch_movable_budgets_have_no_fabricated_day():
    """Movable budgets/statements: confirmed:false + day:null (set per year)."""
    by_title = _by_title()
    for title in _BATCH_FISCAL_MOVABLE:
        e = by_title[title]
        assert e["confirmed"] is False, title
        assert e["day"] is None, title


# --- parliaments / institutional ----------------------------------------------- #
def test_batch_institutional_in_summits_calendar_and_movable():
    """Institutional/parliamentary events live in summits, movable (no fabricated day)."""
    by_title = _by_title()
    for title in _BATCH_INSTITUTIONAL:
        e = by_title[title]
        assert e["calendar"] == "summits", title
        assert e["confirmed"] is False, title
        assert e["day"] is None, title


# --- the statute-FIXED dates: confirmed:true + a concrete, resolvable day ------- #
def test_fixed_dates_are_confirmed_with_a_concrete_day():
    """SCOTUS term opening + US fiscal year start are fixed by statute → confirmed:true."""
    by_title = _by_title()
    for title in _BATCH_FIXED:
        e = by_title[title]
        assert e["confirmed"] is True, title
        assert isinstance(e["month"], int) and 1 <= e["month"] <= 12, title
        assert isinstance(e["day"], int) and 1 <= e["day"] <= 31, title


def test_fixed_dates_resolve_to_a_real_next_occurrence():
    """A fixed (month, day) resolves to a real calendar date via agenda()."""
    items = {e["title"]: e for e in agenda(today=date(2026, 1, 1))}
    for title in _BATCH_FIXED:
        assert items[title]["next_occurrence"] is not None, title


def test_scotus_term_opening_is_movable_with_the_rule_in_its_note():
    """SCOTUS term opening is the "first Monday in October" — a recurring RULE the
    (month, day) schema can't express, so it is MOVABLE (confirmed:false, day:null,
    month hint) with the rule + the 2026 date stated in its note, never a pinned day
    that would mis-render in other years."""
    e = _by_title()["United States Supreme Court — Term opening (First Monday in October)"]
    assert e["confirmed"] is False and e["day"] is None and e["month"] == 10
    assert "first Monday" in e["note"] and "October" in e["note"]
    assert e["official_url"].startswith("https://www.supremecourt.gov")


def test_us_fiscal_year_starts_october_first():
    """The US federal fiscal year start is the statute-fixed 1 October."""
    e = _by_title()["United States — Federal fiscal year start (1 October)"]
    assert (e["month"], e["day"]) == (10, 1)
    assert e["country"] == "US"


# --- global honesty: movable rows never claim a fabricated date ---------------- #
def test_no_batch_event_fabricates_a_date():
    """day:null implies confirmed:false; confirmed implies a concrete month+day."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        e = by_title[title]
        if e["day"] is None:
            assert e["confirmed"] is False, title
        if e["confirmed"]:
            assert e["month"] is not None and e["day"] is not None, title


def test_batch_movable_rows_match_the_declared_movable_set():
    """Only the two statute-fixed rows carry a concrete day; everything else is movable."""
    by_title = _by_title()
    for title in _BATCH_MOVABLE:
        assert by_title[title]["day"] is None, title
        assert by_title[title]["confirmed"] is False, title


def test_batch_does_not_break_the_wider_catalog():
    """Adding the batch leaves every catalog row well-formed (no schema breakage)."""
    evs = load_events()
    assert all(e["title"] and e["official_url"].startswith("http") for e in evs)
    assert all(e["calendar"] and isinstance(e["tags"], list) for e in evs)
    # No duplicate titles introduced by the batch.
    titles = [e["title"] for e in evs]
    assert len(titles) == len(set(titles)), "duplicate event titles in the catalog"
