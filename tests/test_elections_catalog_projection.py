"""A curated election's recurrence rule reaches the agenda (S06-04 S1, the ruled PROJECTED tier).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Found by the 0.6 row A click-through (2026-11-20): the catalogue loader rebuilt each entry from
a fixed list of keys and left out ``interval_years``, ``last_held`` and
``recurrence_rule_source``, so ``src.civic.elections`` never saw a sourced rule and no curated
entry could ever read as projected, upcoming or passed. These tests pin that the three fields
travel as written and that the elections module, not the loader, decides what they are worth.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.events import catalog

TODAY = date(2026, 11, 20)

_YAML = """
calendars:
- {key: elections, name: "National elections", category: civic, description: "x"}
events:
- {title: "Walk A — legislative", calendar: elections, category: civic, country: PRT, cadence: "every 4 years",
   official_url: "https://example.invalid/a", interval_years: 4, last_held: 2024-03-10,
   recurrence_rule_source: "Constitution art. 1 (walk fixture)"}
- {title: "Walk B — legislative", calendar: elections, category: civic, country: GRC, cadence: "every 5 years",
   official_url: "https://example.invalid/b", interval_years: 5, last_held: "2020-06-01",
   recurrence_rule_source: "Constitution art. 2 (walk fixture)"}
- {title: "Walk C — no source", calendar: elections, category: civic, country: CHL, cadence: "every 4 years",
   official_url: "https://example.invalid/c", interval_years: 4, last_held: 2021-11-21}
- {title: "Walk D — unreadable", calendar: elections, category: civic, country: PER, cadence: "every 5 years",
   official_url: "https://example.invalid/d", interval_years: five, last_held: 2021-04-11,
   recurrence_rule_source: "Constitution art. 3 (walk fixture)"}
"""


@pytest.fixture()
def walk_catalog(tmp_path, monkeypatch):
    p = tmp_path / "world_events.yml"
    p.write_text(_YAML, encoding="utf-8")
    monkeypatch.setattr(catalog, "CATALOG_PATH", p)
    # No snapshot: the curated list alone.
    from src.civic import calendar_report

    monkeypatch.setattr(calendar_report, "SNAPSHOT_PATH", tmp_path / "absent.json")
    for fn in (catalog._raw, catalog.load_calendars, catalog._layered):
        fn.cache_clear()
    yield
    for fn in (catalog._raw, catalog.load_calendars, catalog._layered):
        fn.cache_clear()


def _by_title(items):
    return {i["title"].split(" —")[0]: i for i in items}


def test_the_rule_fields_travel_as_written(walk_catalog):
    rows = _by_title(catalog.load_curated_events())
    a = rows["Walk A"]
    # An unquoted YAML date becomes ISO text, so the row stays JSON-shaped.
    assert (a["interval_years"], a["last_held"], a["recurrence_rule_source"]) == (
        4, "2024-03-10", "Constitution art. 1 (walk fixture)")
    # Nothing is coerced by the loader: an unreadable interval stays as written for the module to refuse.
    assert rows["Walk D"]["interval_years"] == "five"


def test_the_agenda_shows_projected_upcoming_and_passed_and_refuses_the_rest(walk_catalog):
    rows = _by_title(catalog.agenda(calendar="elections", today=TODAY))
    a, b = rows["Walk A"], rows["Walk B"]
    assert a["date_confidence"] == "projected" and a["projection"]["year"] == 2028
    assert a["projection"]["status"] == "upcoming" and a["projection"]["month"] is None
    assert b["date_confidence"] == "projected" and b["projection"]["year"] == 2025
    assert b["projection"]["status"] == "passed"
    # Never rolled forward to the next cycle.
    assert b["projection"]["year"] != 2030
    # No source, or an unreadable interval: no tier at all, never a guess.
    assert rows["Walk C"]["date_confidence"] is None and not rows["Walk C"].get("projection")
    assert rows["Walk D"]["date_confidence"] is None and not rows["Walk D"].get("projection")
