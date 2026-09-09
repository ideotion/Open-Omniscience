"""The agenda's span and year-range facts were computed, tested, and never shown.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/events/catalog.py`` has carried ``_span_for``, ``_span_end_date``,
``_in_active_range`` and the ``origin_year`` / ``until_year`` / ``end_month`` /
``end_day`` fields since 2026-07-31, with their own test file. ``app-agenda.js``
read none of them: ``agRow`` never touched ``e.span``, ``e.origin_year`` or
``e.until_year``. So a month-span event would have rendered as a single START
DAY, and a recurrence whose active range has ended would simply stop appearing
with nothing said. `docs/ledger/OPEN_QUEUE.md` records the split precisely —
"the BACKEND is shipped and has a dedicated test file ... What is unbuilt is the
DISPLAY".

**AND IT RENDERS NOTHING TODAY, which is the part that must not be overstated.**
``configs/world_events.yml`` uses NONE of these fields: zero events carry
``end_month``, ``origin_year`` or ``until_year``. The display half was genuinely
missing and is now present and guarded, but no shipped event exercises it. Adding
one is a CONTENT change needing sourced facts (which observances are month-spans,
since when each has been held) — exactly the kind of thing a session must not
invent — so it is recorded in the queue rather than done here.

The four rendering cases were driven in Chromium against the real ``agRow``:
an active span shows "On now, ends 2026-09-30"; an upcoming one shows "Runs
2027-01-01 – 2027-01-31"; a year range shows "· since 1950 · nothing listed
after 2030"; and an event with none of them shows neither. What is guarded here
is that those reads stay in the source, because the browser drive cannot run in
CI.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from tests.js_source_helper import function_source, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def _ag_row() -> str:
    return strip_comments(function_source(read_static("app-agenda.js"), "agRow"))


def test_the_row_reads_every_field_the_catalog_computes() -> None:
    src = _ag_row()
    for field in ("e.span", "e.origin_year", "e.until_year"):
        assert field in src, (
            f"{field} is computed by src/events/catalog.py and tested there; a row "
            "that never reads it renders a month-span event as a single start day"
        )
    assert "span.active" in src, (
        "an active span and an upcoming one are different facts and must not print "
        "as one string"
    )


def test_the_year_range_is_worded_about_the_listing_not_about_the_world() -> None:
    """``until_year`` means the catalogue SUPPRESSES occurrences past that year.
    That is a fact about what this app will show, not a claim that the event will
    never happen again, and the wording has to keep the difference."""
    src = _ag_row()
    assert "nothing listed after {year}" in src, (
        "the until_year wording must describe the listing; anything like "
        '"ends in {year}" asserts something about the world the catalogue does '
        "not know"
    )
    assert "since {year}" in src, "origin_year is the 'since YYYY' provenance"


def test_the_facts_are_marked_catalog_asserted() -> None:
    """Same two-class honesty the source facts carry: these come from the
    catalogue's explicitly-stated fields (``_span_for`` builds a span "only from
    explicitly stated start+end, never guessed"), never from anything deduced."""
    src = _ag_row()
    assert "Stated by the event catalog (asserted, not deduced)." in src
    assert src.count("catalogNote") >= 3, (
        "both the span pill and the year note need the hover, and it should be one "
        "string rather than two copies that can drift"
    )


def test_an_event_with_none_of_them_renders_neither() -> None:
    """Guarded in the source because the alternative — a default banner — is how a
    surface comes to assert a span for an event that has none."""
    src = _ag_row()
    assert 'let span = "";' in src, "the span must default to nothing at all"
    assert ".filter(Boolean).join(" in src, (
        "the year note must drop absent halves rather than printing an empty one"
    )
    assert "yearNote = years" in src, "and must render nothing when both are absent"


def test_the_five_strings_ship_in_all_twelve_locales() -> None:
    keys = [
        "On now, ends {end}",
        "Runs {start} – {end}",
        "since {year}",
        "nothing listed after {year}",
        "Stated by the event catalog (asserted, not deduced).",
    ]
    locales = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        mapping = json.loads(path.read_text(encoding="utf-8"))
        mapping = mapping.get("map", mapping)
        for key in keys:
            assert mapping.get(key), f"{path.name} is missing {key!r}"


def test_the_shipped_catalog_uses_none_of_these_fields_yet() -> None:
    """The measurement this pass must not overstate away.

    Deliberately NOT an equality assertion on zero: the day someone adds a
    sourced month-span event, this should keep passing and the display should
    light up. What it pins is the reverse — that the fields the display reads are
    the SAME names the catalogue loader honours, so a future entry reaches the
    screen instead of being read under a different key.
    """
    catalog = yaml.safe_load((_ROOT / "configs" / "world_events.yml").read_text(encoding="utf-8"))
    events = catalog.get("events") or []
    assert events, "the catalogue is empty; this test would prove nothing"

    loader = (_ROOT / "src" / "events" / "catalog.py").read_text(encoding="utf-8")
    for field in ("origin_year", "until_year", "end_month", "end_day"):
        assert f'"{field}"' in loader, f"the loader no longer honours {field}"

    using = [
        e for e in events
        if any(e.get(f) is not None for f in ("origin_year", "until_year", "end_month"))
    ]
    # Recorded, not enforced: on 2026-09-09 this was 0 of them, which is why the
    # display is present-but-unexercised rather than a visible improvement.
    assert isinstance(using, list)


def test_the_row_is_driven_for_real_in_node() -> None:
    """The half a source grep cannot do.

    ``tests/agenda_span_node_test.js`` EXECUTES the shipped ``agRow`` and reads
    the HTML back, so "on now" vs "upcoming", a half-stated span, a dangling
    separator and ``origin_year == 0`` are checked as behaviour rather than as
    the presence of a substring. Every one of those was a live mutant that the
    source-level guards above let through or caught only incidentally.
    """
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "agenda_span_node_test.js")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "10 passed" in proc.stdout, proc.stdout
