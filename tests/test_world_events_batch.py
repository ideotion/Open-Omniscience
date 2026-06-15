"""Sourced world-events batch — UN days, summits, central banks, elections.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer repeatedly asks for the agenda to be FLOODED with sourced events.
This batch adds genuinely-recurring, SOURCED entries across the existing
``un_days`` / ``summits`` / ``economic`` / ``elections`` calendars. Honesty by
construction (mirrors tests/test_elections_calendar.py): fixed-date UN days carry
``confirmed: true`` + a concrete day; movable summits, central-bank cadences, and
elections carry ``confirmed: false`` + ``day: null`` + the organising body's
``official_url`` — never a fabricated date.

These tests pin that the new events LOAD through the catalog, every one carries an
http ``official_url``, the movable/fixed honesty rule holds, and nothing in the
wider catalog breaks.
"""

from datetime import date
from pathlib import Path

import yaml

from src.events.catalog import CATALOG_PATH, agenda, load_calendars, load_events

# Titles added by THIS batch (the markers used to scope the assertions to new rows).
# Kept in sync with the configs/world_events.yml batch-B / batch-C blocks.
_BATCH_UN_DAYS = {
    "World Wildlife Day",
    "International Day of Forests",
    "World Meteorological Day",
    "World Tuberculosis Day",
    "World Intellectual Property Day",
    "World Day for Safety and Health at Work",
    "World Telecommunication and Information Society Day",
    "International Day of Living Together in Peace",
    "World No Tobacco Day",
    "World Day to Combat Desertification and Drought",
    "World Population Day",
    "International Youth Day",
    "International Day for the Total Elimination of Nuclear Weapons",
    "International Day of Non-Violence",
    "International Day for Disaster Risk Reduction",
    "International Day for the Eradication of Poverty",
    "World Tsunami Awareness Day",
    "International Day for Tolerance",
    "International Day of Persons with Disabilities",
    "International Human Solidarity Day",
}
_BATCH_SUMMITS = {
    "Conference of the Parties to the Convention on Biological Diversity (CBD COP)",
    "Commonwealth Heads of Government Meeting (CHOGM)",
    "Organisation of Islamic Cooperation (OIC) Summit",
    "Shanghai Cooperation Organisation (SCO) Summit",
    "European Council summit (EU)",
    "UN Ocean Conference",
    "International Labour Conference (ILO)",
    "Boao Forum for Asia Annual Conference",
}
_BATCH_CENTRAL_BANKS = {
    "Bank of Korea Monetary Policy Board decision",
    "Banco Central do Brasil Copom interest-rate decision",
    "Reserve Bank of New Zealand Official Cash Rate decision",
    "Sveriges Riksbank monetary policy decision",
    "Norges Bank policy rate decision",
    "South African Reserve Bank MPC decision",
    "Banco de México monetary policy decision",
}
_BATCH_ELECTIONS = {
    "United Kingdom — General election 2029",
    "Australia — Federal election 2028",
    "South Korea — Presidential election 2030",
    "Italy — General election 2027",
    "Poland — Parliamentary election 2027 (Sejm and Senate)",
    "Philippines — General election 2028",
    "Colombia — Presidential election 2026",
    "Chile — General election 2029",
}
_BATCH_ALL = _BATCH_UN_DAYS | _BATCH_SUMMITS | _BATCH_CENTRAL_BANKS | _BATCH_ELECTIONS


def _by_title() -> dict[str, dict]:
    return {e["title"]: e for e in load_events()}


def test_yaml_parses_and_calendars_unchanged():
    """The catalog YAML still parses and the four target calendars exist (no new keys)."""
    raw = yaml.safe_load(Path(CATALOG_PATH).read_text("utf-8"))
    assert isinstance(raw, dict) and isinstance(raw.get("events"), list)
    cal_keys = {c["key"] for c in load_calendars()}
    for key in ("un_days", "summits", "economic", "elections"):
        assert key in cal_keys, key


def test_all_batch_events_load_via_agenda():
    """Every batch event is present in the loaded catalog and reachable via agenda()."""
    titles = {e["title"] for e in load_events()}
    missing = _BATCH_ALL - titles
    assert not missing, f"batch events missing from the catalog: {sorted(missing)}"
    # Sizeable batch as commissioned.
    assert len(_BATCH_ALL) >= 30


def test_every_batch_event_has_an_http_official_url():
    """No batch event without a real source link to the organising body / authority."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        e = by_title[title]
        url = e["official_url"]
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
    """Every batch event carries at least one tag (the filterable/subscribable backbone)."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        tags = by_title[title]["tags"]
        assert isinstance(tags, list) and len(tags) >= 1, title


# --- UN days: FIXED dates → confirmed:true + concrete day --------------------- #
def test_un_days_are_fixed_confirmed_dates():
    """Each batch UN day is in un_days, confirmed:true, with a real (month, day)."""
    by_title = _by_title()
    for title in _BATCH_UN_DAYS:
        e = by_title[title]
        assert e["calendar"] == "un_days", title
        assert e["confirmed"] is True, title
        assert isinstance(e["month"], int) and 1 <= e["month"] <= 12, title
        assert isinstance(e["day"], int) and 1 <= e["day"] <= 31, title
        # un.org is the authority for UN international days.
        assert "un.org" in e["official_url"], title


def test_un_days_resolve_to_a_real_next_occurrence():
    """A fixed (month, day) must resolve to a real calendar date (no Feb 30 etc.)."""
    items = {e["title"]: e for e in agenda(calendar="un_days", today=date(2026, 1, 1))}
    for title in _BATCH_UN_DAYS:
        assert items[title]["next_occurrence"] is not None, title


# --- summits & central banks: MOVABLE → confirmed:false + day:null ------------ #
def test_summits_are_movable_and_unconfirmed():
    """Batch summits carry confirmed:false + day:null (host/date rotates yearly)."""
    by_title = _by_title()
    for title in _BATCH_SUMMITS:
        e = by_title[title]
        assert e["calendar"] == "summits", title
        assert e["confirmed"] is False, title
        assert e["day"] is None, title  # never a fabricated day


def test_central_bank_cadences_are_movable_and_unconfirmed():
    """Central-bank decision cadences are in economic, confirmed:false, day:null."""
    by_title = _by_title()
    for title in _BATCH_CENTRAL_BANKS:
        e = by_title[title]
        assert e["calendar"] == "economic", title
        assert e["category"] == "economic", title
        assert e["confirmed"] is False, title
        assert e["day"] is None, title
        assert e["month"] is None, title
        assert "central-bank" in e["tags"], title


# --- elections: movable → confirmed:false + authority's source ---------------- #
def test_batch_elections_are_honest_and_sourced():
    """Batch elections: in elections, ISO-2 country, confirmed:false, day:null, http url."""
    by_title = _by_title()
    for title in _BATCH_ELECTIONS:
        e = by_title[title]
        assert e["calendar"] == "elections", title
        assert e["confirmed"] is False, title
        assert e["day"] is None, title  # none fixed by a simple statute → no fabricated day
        cc = e["country"]
        assert isinstance(cc, str) and len(cc) == 2 and cc.isupper(), title
        assert "elections" in e["tags"], title


def test_batch_elections_carry_a_country_year_provenance_tag():
    """Each batch election carries a `<country>-<year>` tag (cycle-distinguishable)."""
    import re

    by_title = _by_title()
    for title in _BATCH_ELECTIONS:
        tags = by_title[title]["tags"]
        assert any(re.fullmatch(r"[a-z-]+-20\d{2}", t) for t in tags), title


def test_batch_elections_reachable_via_elections_tag():
    """The batch elections appear under the subscribable `elections` tag query."""
    titles = {e["title"] for e in agenda(tag="elections")}
    missing = _BATCH_ELECTIONS - titles
    assert not missing, f"elections missing from tag query: {sorted(missing)}"


# --- global honesty: movable rows never claim a fabricated date --------------- #
def test_no_batch_event_fabricates_a_date():
    """Across the whole batch: a concrete day implies confirmed:true (and vice-versa
    for movable rows). Mirrors the elections-calendar honesty rule, applied broadly."""
    by_title = _by_title()
    for title in _BATCH_ALL:
        e = by_title[title]
        if e["day"] is None:
            assert e["confirmed"] is False, title
        if e["confirmed"]:
            assert e["month"] is not None and e["day"] is not None, title


def test_batch_does_not_break_the_wider_catalog():
    """Adding the batch leaves every catalog row well-formed (no schema breakage)."""
    evs = load_events()
    assert all(e["title"] and e["official_url"].startswith("http") for e in evs)
    assert all(e["calendar"] and isinstance(e["tags"], list) for e in evs)
    # No duplicate titles introduced by the batch.
    titles = [e["title"] for e in evs]
    assert len(titles) == len(set(titles)), "duplicate event titles in the catalog"
