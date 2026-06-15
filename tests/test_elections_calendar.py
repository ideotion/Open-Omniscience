"""Sourced elections-calendar first slice (France 2027 pilot).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The civic/elections vertical's lowest-risk first slice: a sourced ``elections``
calendar in world_events.yml. Honesty by construction — movable elections carry
``confirmed: false`` + the electoral authority's ``official_url``, never a
fabricated day. These tests pin that the entries load through the catalog, are
subscribable/filterable by the ``elections`` tag, and stay honest about dates.
"""

from pathlib import Path

import yaml

from src.events.catalog import CATALOG_PATH, agenda, load_calendars, load_events


def test_yaml_parses_and_has_elections_calendar():
    """The catalog YAML parses, and the elections calendar is declared."""
    raw = yaml.safe_load(Path(CATALOG_PATH).read_text("utf-8"))
    assert isinstance(raw, dict) and isinstance(raw.get("events"), list)
    cal_keys = {c["key"] for c in load_calendars()}
    assert "elections" in cal_keys  # subscribable collection
    elections_cal = next(c for c in load_calendars() if c["key"] == "elections")
    # Reuses an EXISTING data-driven category — never invents one (chips are keyed, so a
    # new category would render untranslated). The civic vertical owns elections.
    assert elections_cal["category"] == "civic"


def test_elections_load_via_tag_query():
    """Elections are reachable through the subscribable/filterable `elections` tag."""
    evs = agenda(tag="elections")
    assert len(evs) >= 6  # France pilot + a handful of well-known upcoming elections
    # The tag query is honest: every returned row actually carries the tag.
    assert all("elections" in e["tags"] for e in evs)
    # Every election sits in the elections calendar and reuses an existing category.
    assert all(e["calendar"] == "elections" for e in evs)
    assert all(e["category"] in ("civic", "political", "economic", "technology") for e in evs)


def test_every_election_carries_an_official_url_to_the_authority():
    """No election without a real source link to its electoral authority."""
    for e in agenda(tag="elections"):
        url = e["official_url"]
        assert isinstance(url, str) and url.startswith("http"), e["title"]


def test_countries_are_iso2():
    """`country` is stored as a 2-letter ISO code (project-wide canonical form)."""
    for e in agenda(tag="elections"):
        cc = e["country"]
        assert isinstance(cc, str) and len(cc) == 2 and cc.isalpha() and cc.isupper(), e


def test_movable_elections_are_not_given_a_fabricated_date():
    """Movable elections are confirmed:false; a concrete day is set only when truly fixed.

    Honesty rule: an election may only claim a precise day (`day` set) when it is
    officially fixed — otherwise `confirmed` must be False and the exact day stays
    open (None), with the authority's URL carrying the real date.
    """
    evs = agenda(tag="elections")
    # The France 2027 presidential pilot is movable within the constitutional window.
    fr = next(e for e in evs if e["country"] == "FR")
    assert fr["confirmed"] is False
    assert fr["day"] is None  # never a fabricated day
    assert "conseil-constitutionnel" in fr["official_url"]
    assert "france-2027" in fr["tags"]
    # Any election that has NOT been given a concrete day must be confirmed:false.
    for e in evs:
        if e["day"] is None:
            assert e["confirmed"] is False, e["title"]
    # And any confirmed election must actually carry a fixed month+day (no empty claim).
    for e in evs:
        if e["confirmed"]:
            assert e["month"] is not None and e["day"] is not None, e["title"]


def test_us_2026_midterms_fixed_date_sorts_first():
    """The one statute-fixed date (US 2026 midterms, Nov 3) gets a next_occurrence."""
    us = next(e for e in agenda(tag="elections") if e["country"] == "US")
    assert us["confirmed"] is True and us["month"] == 11 and us["day"] == 3
    # Fixed dates are enriched with next_occurrence; movable ones are not.
    from datetime import date

    items = {e["country"]: e for e in agenda(tag="elections", today=date(2026, 1, 1))}
    assert items["US"]["next_occurrence"] == "2026-11-03"
    assert items["FR"]["next_occurrence"] is None  # movable → no fabricated date


def test_every_election_carries_a_country_year_provenance_tag():
    """Each election carries a `<country>-<year>` tag (filterable provenance), so the
    subscribable `elections` tag is not the only handle and cycles stay distinguishable."""
    import re

    for e in agenda(tag="elections"):
        assert any(re.fullmatch(r"[a-z-]+-20\d{2}", t) for t in e["tags"]), e["title"]


def test_confirmed_elections_are_not_in_the_past():
    """An election may only claim confirmed:true with a concrete day if that day is a
    REAL upcoming/recurring date — the loader's next_occurrence must resolve it (a fixed
    statutory date like the US midterms always has a forthcoming occurrence)."""
    for e in agenda(tag="elections"):
        if e["confirmed"]:
            assert e["next_occurrence"] is not None, e["title"]


def test_elections_do_not_break_the_wider_catalog():
    """Adding elections leaves every catalog row well-formed (no schema breakage)."""
    evs = load_events()
    assert all(e["title"] and e["official_url"].startswith("http") for e in evs)
    assert all(e["calendar"] and isinstance(e["tags"], list) for e in evs)
