"""Elections: a stated date that has passed, the Wikidata snapshot layer, and the coverage report.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three refusals, each pinned:

* A one-off election the catalogue states (the US 2026 midterm) is never rolled forward into a
  later year: once its date has gone by it reads as PASSED, as the source gave it, and it no
  longer counts as coverage.
* The app reads the operator's Wikidata snapshot when one exists, says so with its counts, and
  says just as plainly when there is none or it cannot be read. Never half-read.
* The release-record report lists every floor country, missing ones included. Offline.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.civic.calendar_report import country_tier_report, load_snapshot, with_snapshot
from src.civic.coverage_floor import load_floor as _load_floor
from src.civic.elections import annotate, has_passed

TODAY = date(2026, 11, 13)


def _ev(**kw):
    return {"calendar": "elections", "title": "X — election", "country": "BR", **kw}


# --- has_passed ------------------------------------------------------------------------ #
@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"until_year": 2026, "month": 11, "day": 3}, True),
        ({"until_year": 2026, "month": 11, "day": 13}, False),  # today has not passed
        ({"until_year": 2026, "month": 10}, True),
        ({"until_year": 2026, "month": 11}, False),  # the current month has not passed
        ({"window_year": 2026}, False),  # the current year has not passed
        ({"window_year": 2025}, True),
        ({"window_year": 2027, "month": 4}, False),
        ({"month": 4}, False),  # no stated year: never guessed to have passed
        ({}, False),
        ({"until_year": "2025"}, False),  # a string is not a stated year
        ({"until_year": 2026, "month": 2, "day": 30}, True),  # an impossible day falls back to the month
    ],
)
def test_has_passed_reads_only_what_the_entry_states(fields, expected):
    assert has_passed(_ev(**fields), TODAY) is expected


def test_annotate_marks_a_passed_stated_date_and_leaves_its_tier():
    out = annotate(_ev(until_year=2026, month=11, day=3, confirmed=True), TODAY)
    assert out["date_confidence"] == "scheduled" and out["passed"] is True
    assert "passed" not in annotate({"calendar": "summits", "title": "x"}, TODAY)


# --- the shipped catalogue ------------------------------------------------------------- #
def test_the_us_2026_midterm_is_never_rolled_forward_to_2027():
    from src.events.catalog import agenda

    rows = [e for e in agenda(calendar="elections", today=TODAY) if "Midterm elections 2026" in e["title"]]
    assert len(rows) == 1
    (us,) = rows
    assert us["next_occurrence"] is None, "a one-off election never recurs annually"
    assert us["passed"] is True
    before = [e for e in agenda(calendar="elections", today=date(2026, 6, 1)) if "Midterm elections 2026" in e["title"]]
    assert before[0]["next_occurrence"] == "2026-11-03" and before[0]["passed"] is False


def test_every_dated_curated_election_is_bounded_to_its_year():
    """A curated election with a month is ONE election: unbounded, the agenda repeats it yearly."""
    from src.events.catalog import load_curated_events

    for e in load_curated_events():
        if e["calendar"] == "elections" and e.get("month"):
            assert e.get("until_year") or e.get("window_year"), e["title"]


def test_a_passed_stated_date_is_its_own_state_and_not_coverage():
    rep = country_tier_report(
        [_ev(until_year=2026, month=10), _ev(country="CA", until_year=2029, month=10)], {"br", "ca"}, TODAY
    )
    by = {r["cc"]: r for r in rep["countries"]}
    assert by["br"]["state"] == "passed" and "not listed" in by["br"]["reason"]
    assert by["ca"]["state"] == "window"
    assert rep["counts"]["passed"] == 1 and "passed (every stated date" in rep["method"]


def test_floor_coverage_does_not_count_a_passed_stated_date(monkeypatch):
    from src.civic import coverage_floor as cf

    floor = cf.load_floor()
    cc = sorted(floor["countries"])[0]
    monkeypatch.setattr(cf, "load_floor", lambda: {**floor, "countries": [cc]})
    monkeypatch.setattr("src.events.catalog.load_events",
                        lambda: [{"calendar": "elections", "country": cc, "until_year": 2026, "month": 3}])
    c = cf.floor_coverage(TODAY)
    assert c["covered"] == [] and c["only_passed_projection"] == [cc] and c["missing"] == []


# --- the snapshot ---------------------------------------------------------------------- #
def _write(tmp_path, payload):
    p = tmp_path / "snap.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return p


def test_no_snapshot_is_stated_and_changes_nothing(tmp_path):
    curated = [_ev(until_year=2027, month=4)]
    events, info = with_snapshot(curated, TODAY, tmp_path / "absent.json")
    assert events == curated and info == {"state": "absent"}


@pytest.mark.parametrize("payload", ["{not json", json.dumps([1, 2]), json.dumps({"rows": []}),
                                     json.dumps({"rows": "x", "as_of": "2026-11-01"})])
def test_an_unreadable_snapshot_is_never_half_read(tmp_path, payload):
    snap, state = load_snapshot(_write(tmp_path, payload))
    assert snap is None and state == "unreadable"
    events, info = with_snapshot([], TODAY, _write(tmp_path, payload))
    assert events == [] and info == {"state": "unreadable"}


def test_a_present_snapshot_is_layered_with_its_counts(tmp_path):
    rows = [
        # Same country, same year and month as the curated entry: shadowed, with a record.
        {"country": "FR", "office": "President", "qid": "Q1", "point_in_time": "2027-04-01", "precision": "month"},
        # A new election: added, bounded to its year.
        {"country": "DE", "office": "Bundestag", "qid": "Q2", "point_in_time": "2029-09-01", "precision": "month"},
        # A past one: refused.
        {"country": "IT", "office": "Senate", "qid": "Q3", "point_in_time": "2022-09-25", "precision": "day"},
        # No date: kept, with the reason it has none.
        {"country": "PL", "office": "Sejm", "qid": "Q4"},
    ]
    p = _write(tmp_path, {"as_of": "2026-11-01", "rows": rows, "refused": [{"qid": "Q9"}]})
    curated = [{"calendar": "elections", "title": "France — Presidential election 2027", "country": "FRA",
                "month": 4, "window_year": 2027}]
    events, info = with_snapshot(curated, TODAY, p)
    assert info == {"state": "present", "as_of": "2026-11-01", "rows": 4, "added": 2, "shadowed": 1,
                    "refused": 1, "generator_refused": 1}
    added = {e["source_qid"]: e for e in events if e.get("source_qid")}
    assert set(added) == {"Q2", "Q4"}
    assert added["Q2"]["origin_year"] == added["Q2"]["until_year"] == 2029
    assert added["Q4"]["until_year"] is None and added["Q4"]["note"] == "row states no usable date"
    assert added["Q2"]["country"] == "DE", "the snapshot speaks the catalogue's country form"


def test_a_snapshot_election_does_not_recur_in_the_agenda(tmp_path, monkeypatch):
    from src.events import catalog

    rows = [{"country": "DE", "office": "Bundestag", "qid": "Q2", "point_in_time": "2027-09-26",
             "precision": "day", "official_url": "https://example.org/"}]
    events, _ = with_snapshot([], TODAY, _write(tmp_path, {"as_of": "2026-11-01", "rows": rows}))
    monkeypatch.setattr(catalog, "load_events", lambda: events)
    (row,) = catalog.agenda(calendar="elections", today=TODAY)
    assert row["next_occurrence"] == "2027-09-26" and row["date_confidence"] == "scheduled"
    (later,) = catalog.agenda(calendar="elections", today=date(2027, 10, 1))
    assert later["next_occurrence"] is None and later["passed"] is True


def test_the_floor_endpoint_states_the_snapshot():
    from src.api.diagnostics import elections_coverage_floor

    snap = elections_coverage_floor()["snapshot"]
    assert snap["state"] in ("absent", "unreadable", "present")


def test_the_agenda_says_when_there_is_no_snapshot():
    from pathlib import Path

    from tests.js_source_helper import function_body

    js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app-agenda.js").read_text(encoding="utf-8")
    body = function_body(js, "agSnapshotLine")
    for phrase in ("No Wikidata election snapshot on this install yet", "could not be read", "{refused} refused"):
        assert phrase in body


# --- the report ------------------------------------------------------------------------ #
def test_the_report_lists_every_floor_country_and_states_the_missing(tmp_path):
    from scripts.elections_coverage_report import main

    out = tmp_path / "r.md"
    assert main(["-o", str(out), "--today", "2026-11-13"]) == 0
    text = out.read_text(encoding="utf-8")
    floor = _load_floor()["countries"]
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and len(ln.split("|")[1].strip()) == 2]
    assert sorted(ln.split("|")[1].strip().lower() for ln in rows) == sorted(c.lower() for c in floor)
    assert "missing (no entry)" in text and "no election entry for this country" in text
    assert "| US | passed" in text, "the 2026 midterm reads as passed on 2026-11-13"
    header = next(ln for ln in text.splitlines() if ln.startswith("| Country"))
    assert not any(b in header.lower() for b in ("score", "rating", "rank")), "counts and reasons only"


# --- review follow-ups ------------------------------------------------------------------ #
def test_a_passed_curated_entry_never_hides_a_later_snapshot_election(tmp_path):
    """A curated Brazil 2026 (October) must not shadow a snapshot Brazil 2030 (October): the
    report would then say "the next one is not listed" while the snapshot listed it. The years
    differ, so the until_year bound keeps them apart."""
    rows = [{"country": "BR", "office": "General", "qid": "Q30", "point_in_time": "2030-10-06",
             "precision": "day", "official_url": "https://example.org/"}]
    p = _write(tmp_path, {"as_of": "2026-11-01", "rows": rows})
    curated = [{"calendar": "elections", "title": "Brazil — General election 2026", "country": "BR",
                "month": 10, "until_year": 2026}]
    events, info = with_snapshot(curated, TODAY, p)
    assert info["added"] == 1 and info["shadowed"] == 0
    rep = country_tier_report(events, {"br"}, TODAY)
    assert rep["countries"][0]["state"] == "scheduled"


def test_until_year_is_the_curated_year_for_matching():
    """A one-cycle curated entry still shadows the SAME election from the snapshot."""
    rows = [{"country": "CA", "office": "Federal", "qid": "Q29", "point_in_time": "2029-10-01",
             "precision": "month"}]
    curated = [{"calendar": "elections", "title": "Canada — Federal election 2029", "country": "CA",
                "month": 10, "until_year": 2029}]
    from src.civic.calendar_report import layer, snapshot_to_events

    evs, _ = snapshot_to_events(rows, TODAY)
    _, shadowed = layer(curated, evs, TODAY)
    assert len(shadowed) == 1 and "year 2029" in shadowed[0]["reason"]


def test_the_passed_reason_names_a_dateless_entry_when_there_is_one():
    rep = country_tier_report([_ev(until_year=2026, month=10), _ev(title="Brazil — next")], {"br"}, TODAY)
    row = rep["countries"][0]
    assert row["state"] == "passed" and "states no date" in row["reason"]


def test_a_passed_entry_carries_the_passed_caveat():
    from src.civic.elections import PASSED_CAVEAT

    out = annotate(_ev(until_year=2026, month=10), TODAY)
    assert out["passed"] is True and out["date_caveat"] == PASSED_CAVEAT


def test_a_snapshot_written_while_running_is_read_without_a_restart(tmp_path, monkeypatch):
    from src.civic import calendar_report
    from src.events import catalog

    path = tmp_path / "elections_snapshot.json"
    monkeypatch.setattr(calendar_report, "SNAPSHOT_PATH", path)
    catalog.load_events.cache_clear()
    try:
        assert catalog.layered_events(TODAY)[1] == {"state": "absent"}
        path.write_text(json.dumps({"as_of": "2026-11-01", "rows": []}), encoding="utf-8")
        assert catalog.layered_events(TODAY)[1]["state"] == "present"
    finally:
        catalog.load_events.cache_clear()


def test_the_floor_endpoint_builds_every_half_from_one_read():
    from pathlib import Path

    from tests.js_source_helper import python_function_source

    src = (Path(__file__).resolve().parents[1] / "src" / "api" / "diagnostics" / "system.py").read_text("utf-8")
    fn = python_function_source(src, "elections_coverage_floor")
    assert "layered_events(today)" in fn and "events=events" in fn and "with_snapshot" not in fn


def test_every_agenda_grid_places_a_bounded_entry_only_inside_its_years():
    """A one-off election (origin_year = until_year) never reappears in other years' grids."""
    import subprocess
    from pathlib import Path

    from tests.js_source_helper import function_body, function_source

    js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app-agenda.js").read_text(encoding="utf-8")
    for name in ("renderAgendaYear", "agEventsInMonth", "renderAgendaDecade", "renderAgendaMonth", "agEventsOn"):
        assert "agInYear(e, y)" in function_body(js, name), name
    assert "agInYear(e, d.getFullYear())" in function_body(js, "renderAgendaWeek")
    probe = function_source(js, "agInYear") + """
const e = {origin_year: 2026, until_year: 2026};
if (!agInYear(e, 2026) || agInYear(e, 2027) || agInYear(e, 2025)) process.exit(1);
if (!agInYear({}, 1999) || !agInYear({origin_year: 1950, until_year: null}, 2030)) process.exit(2);
// A curated election bounded only by until_year starts that year too.
const us = {calendar: "elections", until_year: 2026};
if (agInYear(us, 2025) || !agInYear(us, 2026) || agInYear(us, 2027)) process.exit(3);
if (!agInYear({calendar: "observances", until_year: 2026}, 2020)) process.exit(4);
"""
    assert subprocess.run(["node", "-e", probe], timeout=30).returncode == 0


def test_the_same_passed_election_from_the_snapshot_stays_shadowed(tmp_path):
    """The snapshot's year-precision copy of the passed Brazil 2026 election must not come back as
    a live window that counts as coverage."""
    rows = [{"country": "BR", "office": "General", "qid": "Q26", "point_in_time": "2026-01-01",
             "precision": "year"}]
    p = _write(tmp_path, {"as_of": "2026-11-01", "rows": rows})
    curated = [{"calendar": "elections", "title": "Brazil — General election 2026", "country": "BR",
                "month": 10, "until_year": 2026}]
    events, info = with_snapshot(curated, TODAY, p)
    assert info["shadowed"] == 1 and info["added"] == 0
    assert country_tier_report(events, {"br"}, TODAY)["countries"][0]["state"] == "passed"
