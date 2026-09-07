"""The elections coverage floor — the ruled denominator, and what the calendar covers of it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-07-14 (V1_PATHWAY §4.5(1)): the elections vertical must cover "at
least every country whose official or major language is one of the twelve UI languages",
from a dated, sourced language→country mapping — **never guessed**. That mapping is
``configs/language_countries.yml``; this module turns it into a measurement.

WHY THIS EXISTS AS CODE RATHER THAN AS A NUMBER IN A DOC. The floor is the DENOMINATOR of
the elections component of the K13 vertical-coverage bar, and a denominator that lives in
prose drifts from the catalog silently. Computed here, "the floor is N countries and the
calendar reaches M of them" is a fact that moves when either side moves, rather than a
figure someone transcribed once.

TWO HONESTY PROPERTIES, both of which are refusals rather than caveats:

* **A country is covered only by an entry that survives the date-confidence tiers.** An
  election entry that states no date and cannot be projected is the refusal-(1) gap in
  ``elections.py``; counting it as coverage would let the floor be cleared by rows that
  tell the reader nothing. ``covered`` and ``present_but_dateless`` are therefore separate
  counts, because "we have no entry for Chad" and "we have an entry for Chad with no
  usable date" are different facts and only the first is a research task.

* **The mapping's own verification status travels with every answer.** It was drafted from
  training knowledge with no network available and is not verified; a coverage figure
  computed over an unverified denominator must say so, or the number reads as settled.
  ``load_floor()`` refuses to silently drop a country code the ISO set does not know —
  the invalid codes are REPORTED, because a typo that removes a country from the floor
  makes the app claim coverage it never had.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.civic.elections import (
    ELECTIONS_CALENDAR,
    PROJECTED,
    date_confidence,
    missing_projection_fields,
    projection,
)

FLOOR_PATH = Path(__file__).resolve().parents[2] / "configs" / "language_countries.yml"

#: The mapping's own as-of date, mirrored here as a source constant because the
#: external-artifact registry pins ``{file, const}`` and its guard scans the tree for
#: ``*_AS_OF`` literals. It is a SECOND spelling of a fact the YAML already states, which
#: is exactly how two sources of truth drift apart, so
#: ``tests/test_elections_coverage_floor.py`` asserts the two agree and reddens by name
#: when only one is bumped.
LANGUAGE_COUNTRIES_AS_OF = "2026-09-07"

#: The basis values a row may declare. `regional` counts toward the floor — the ruling
#: says "official OR major" — but is labelled, being the class most likely to be contested.
VALID_BASES: tuple[str, ...] = ("official", "de-facto", "regional")


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    if not FLOOR_PATH.exists():
        return {}
    loaded = yaml.safe_load(FLOOR_PATH.read_text("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


@lru_cache(maxsize=1)
def load_floor() -> dict[str, Any]:
    """The parsed floor: per-language country rows, plus every refusal the parse made.

    Returns ``{as_of, verification_status, method, languages, countries, invalid,
    contested}``. ``invalid`` holds any ``(language, cc)`` whose code is not in the repo's
    own ISO 3166-1 set — reported rather than dropped, because a silently-dropped code
    shrinks the floor and a smaller floor is easier to clear.
    """
    # The repo's own ISO 3166-1 alpha-2 set, used directly rather than through
    # `to_iso2`: that helper also admits the four project SPECIAL_CODES, which are not
    # countries and must never enter a per-country floor.
    from src.catalog.countries import ISO_3166_1_ALPHA2

    raw = _raw()
    langs: dict[str, Any] = {}
    countries: set[str] = set()
    invalid: list[dict[str, str]] = []
    contested: list[dict[str, str]] = []

    for code, block in (raw.get("languages") or {}).items():
        if not isinstance(block, dict):
            continue
        rows = []
        for row in block.get("countries") or []:
            if not isinstance(row, dict):
                continue
            cc = str(row.get("cc") or "").strip().lower()
            basis = str(row.get("basis") or "").strip()
            if not cc:
                continue
            if cc not in ISO_3166_1_ALPHA2:
                invalid.append({"language": str(code), "cc": cc, "reason": "not an ISO 3166-1 alpha-2 code"})
                continue
            if basis not in VALID_BASES:
                invalid.append({"language": str(code), "cc": cc, "reason": f"unknown basis {basis!r}"})
                continue
            # Annotated: `contested` is a bool beside two strs, and an inferred
            # dict[str, str] rejects it (mypy caught this, not review).
            entry: dict[str, Any] = {"cc": cc, "basis": basis}
            if row.get("contested"):
                entry["contested"] = True
                contested.append({"language": str(code), "cc": cc, "note": str(row.get("note") or "")})
            if row.get("note"):
                entry["note"] = str(row["note"])
            rows.append(entry)
            countries.add(cc)
        langs[str(code)] = {
            "name": str(block.get("name") or code),
            "source": str(block.get("source") or ""),
            "countries": rows,
        }

    return {
        "as_of": str(raw.get("as_of") or ""),
        "verification_status": str(raw.get("verification_status") or ""),
        "method": str(raw.get("method") or ""),
        "languages": langs,
        "countries": sorted(countries),
        "invalid": invalid,
        "contested": contested,
    }


def floor_countries() -> set[str]:
    """The union country set — the floor, as a denominator."""
    return set(load_floor()["countries"])


def floor_coverage(today: date | None = None) -> dict[str, Any]:
    """What the shipped elections calendar covers of the ruled floor.

    Network-free and cheap (one config read, one catalog read), so it rides the
    all-diagnostics bundle rather than needing an operator run.

    The payload separates three states that a single "covered" count would conflate:
    ``covered`` (a floor country with at least one election entry carrying a usable date
    tier), ``present_but_dateless`` (an entry exists but falls in the refusal-(1) gap —
    named with the fields it lacks, so it is a worklist rather than a complaint), and
    ``missing`` (no entry at all).
    """
    from src.events.catalog import load_events

    today = today or date.today()
    floor = load_floor()
    wanted = set(floor["countries"])

    with_date: set[str] = set()
    live: set[str] = set()
    dateless: dict[str, list[str]] = {}
    for ev in load_events():
        if str(ev.get("calendar") or "") != ELECTIONS_CALENDAR:
            continue
        cc = str(ev.get("country") or "").strip().lower()
        if not cc:
            continue
        tier = date_confidence(ev)
        if tier is None:
            dateless.setdefault(cc, missing_projection_fields(ev))
            continue
        with_date.add(cc)
        # A PASSED projection is still an entry, and the ruling makes it a lead rather
        # than a deletion ("status unknown -- check the official source"). But it is the
        # weakest coverage there is, so a country whose only entry is one is counted
        # apart: folding it into `covered` would let the floor be cleared by dates that
        # have already gone by.
        proj = projection(ev, today) if tier == PROJECTED else None
        if proj is None or proj["status"] != "passed":
            live.add(cc)

    covered = sorted(wanted & live)
    only_passed = sorted((wanted & with_date) - live)
    # A country with BOTH a dated and a dateless entry counts as covered: the dated one
    # answers the reader. Only a country whose ONLY entries are dateless is a gap.
    present_dateless = sorted((set(dateless) & wanted) - with_date)
    missing = sorted(wanted - with_date - set(present_dateless))
    outside = sorted(with_date - wanted)

    return {
        "as_of": floor["as_of"],
        "verification_status": floor["verification_status"],
        "method": (
            "The floor is the union of countries whose official, de-facto national or "
            "regionally predominant language is one of the twelve UI languages "
            "(configs/language_countries.yml). A floor country counts as covered when the "
            "elections calendar holds an entry for it with a date-confidence tier "
            "(scheduled, window, or a projection that has not yet passed). An entry that "
            "states no date and carries no sourced recurrence rule, and a country whose "
            "only entry is an already-passed projection, are each reported separately -- "
            "never as coverage."
        ),
        "caveat": (
            "The country list is drafted, not verified — no row has been checked against a "
            "primary source, so this share is measured against an unverified denominator. "
            "Coverage is a count of calendar ENTRIES, never a claim that an election will "
            "be held."
        ),
        "floor_countries": len(wanted),
        "covered": covered,
        "covered_n": len(covered),
        # Floor countries whose ONLY election entry is a projection whose date has
        # already passed -- an investigative lead, not coverage.
        "only_passed_projection": only_passed,
        "only_passed_projection_n": len(only_passed),
        "present_but_dateless": [{"cc": cc, "missing_fields": dateless[cc]} for cc in present_dateless],
        "present_but_dateless_n": len(present_dateless),
        "missing": missing,
        "missing_n": len(missing),
        # Not a defect: the calendar may legitimately carry a country outside the floor
        # (the floor is a MINIMUM). Reported so the two numbers are never read as one.
        "covered_outside_floor": outside,
        "invalid_rows": floor["invalid"],
        "contested_rows": floor["contested"],
    }
