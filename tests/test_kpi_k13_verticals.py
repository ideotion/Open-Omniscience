"""Row 183 (R751): K13 "Vertical coverage" reads what the verticals already persisted, and fetches or scans nothing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

K13 had no resolver: it read "await the §4 vertical builds" while climate (0.6) and the elections floor were shipped. These
tests pin the four facts the board must keep apart:

* never measured (no fetch recorded, no snapshot on disk) is ``not-measurable-here`` with no value and no date;
* a fetch that stored nothing new is still a fetch ("fetched, nothing new"), never read as missing;
* a source that answered with no figures is its own outcome, and not a first slice;
* the value is a COUNT of verticals with a first slice, with n = the verticals listed, and the target names the open bar
  (R751(d)), so the verdict is ``measured-no-bar``, never green on an unruled freshness.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from src.monitoring import kpi as K

_NONE = {"state": "absent"}
_SNAP = {"state": "present", "as_of": "2026-11-01", "rows": 42, "added": 30}


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """Records live beside K6's: point that folder at tmp_path. The elections snapshot is stubbed per test."""
    monkeypatch.setattr(K, "_coverage_path", lambda: tmp_path / "keyword-coverage.json")
    _snapshot(monkeypatch, _NONE)
    return tmp_path


def _snapshot(monkeypatch, snap: dict) -> None:
    from src.events import catalog

    real = catalog.layered_events

    def fake(today=None):
        events, _ = real(today)
        return events, dict(snap)

    monkeypatch.setattr(catalog, "layered_events", fake)


def _k13() -> dict:
    return next(m for m in K.kpi_snapshot()["metrics"] if m["id"] == "K13")


def _block(m: dict, name: str) -> dict:
    return next(b for b in m["verticals"] if b["vertical"] == name)


def _fetch(dataset: str = "oni", *, figures: int = 120, new: int = 120, revised: int = 0, param=None) -> dict:
    return {"dataset": dataset, "param": param, "fetched_at": "2026-11-18T10:00:00+00:00", "figures": figures,
            "tally": {"new": new, "revised": revised, "unchanged": figures - new - revised}}


def _medical(**over) -> dict:
    rec = {"fetched_at": "2026-11-18T10:00:00+00:00", "listed": 40, "remaining": 33, "applied": 7, "failed": None,
           "stopped": False, "papers": 3, "by_class": {"journal": 2, "preprint": 0, "retracted": 1},
           "coverage": {"cited": 10, "cited_found": 3, "cited_not_found": 7, "named": 0, "named_found": 0,
                        "named_not_found": 0},
           "last_file": "pubmed25n1400.xml.gz"}
    rec.update(over)
    return rec


def test_nothing_recorded_is_not_measured_with_no_value_and_no_date(isolated):
    m = _k13()
    assert m["verdict"] == "not-measurable-here"
    assert m["value"] is None and m["as_of"] is None
    assert {b["vertical"]: b["state"] for b in m["verticals"]} == {"climate": "not-measured", "elections": "not-measured",
                                                                 "law": "not-measured", "medical": "not-measured",
                                                                 "osm": "not-measured",
                                                                 "wiki": "not-measured"}
    assert all(b["reason"] for b in m["verticals"])
    assert K.run_kpi_selftest()["passed"]


def test_a_recorded_fetch_is_counted_with_its_own_date_and_an_open_bar(isolated):
    rec = K.record_climate_fetch(_fetch())
    assert rec is not None
    m = _k13()
    assert m["verdict"] == "measured-no-bar"
    assert "pending-ruling" in m["target"]
    assert (m["value"], m["n"]) == (1, 6)
    assert m["as_of"] == rec["measured_at"]
    row = _block(m, "climate")["datasets"][0]
    assert (row["dataset"], row["figures"], row["outcome"]) == ("oni", 120, "fetched, stored new or revised figures")
    assert K.run_kpi_selftest()["passed"]


def test_a_refetch_with_nothing_new_is_a_fetch_not_a_gap(isolated):
    K.record_climate_fetch(_fetch(new=0, revised=0))
    m = _k13()
    block = _block(m, "climate")
    assert block["state"] == "recorded" and block["first_slice"] is True
    assert block["datasets"][0]["outcome"] == "fetched, nothing new"
    assert m["value"] == 1


def test_a_source_that_gave_no_figures_is_recorded_but_is_no_first_slice(isolated):
    K.record_climate_fetch(_fetch(figures=0, new=0))
    m = _k13()
    block = _block(m, "climate")
    assert block["state"] == "recorded" and block["first_slice"] is False
    assert block["datasets"][0]["outcome"] == "source gave no figures"
    # Measured: the count is 0 of 2, a value, not "not measured".
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 0, 6)
    assert K.run_kpi_selftest()["passed"]


def test_each_dataset_keeps_its_last_fetch_and_no_unit_is_written(isolated):
    K.record_climate_fetch(_fetch("ghcnd", param="USW00094728"))
    K.record_climate_fetch(_fetch("oni"))
    K.record_climate_fetch(_fetch("oni", new=0))
    text = (isolated / "vertical-climate.json").read_text(encoding="utf-8")
    assert "USW00094728" not in text  # which station someone reads is not written to a plaintext file
    block = _block(_k13(), "climate")
    assert [r["dataset"] for r in block["datasets"]] == ["ghcnd", "oni"]
    assert block["datasets"][1]["outcome"] == "fetched, nothing new"
    assert block["datasets_fetched"] == 2


@pytest.mark.parametrize("bad", [None, {}, {"dataset": "not-a-dataset"}, {"dataset": 7}])
def test_an_unknown_dataset_writes_nothing(isolated, bad):
    assert K.record_climate_fetch(bad) is None
    assert not (isolated / "vertical-climate.json").exists()


@pytest.mark.parametrize("content", ["{not json", json.dumps({"schema": "someone-else-1", "datasets": {"oni": {}}}),
                                     json.dumps({"schema": "oo-vertical-climate-1", "datasets": []})])
def test_an_unreadable_or_foreign_file_reads_as_not_measured(isolated, content):
    (isolated / "vertical-climate.json").write_text(content, encoding="utf-8")
    m = _k13()
    assert _block(m, "climate")["state"] == "not-measured"
    assert m["verdict"] == "not-measurable-here" and m["value"] is None


def test_the_fetch_date_is_the_fetch_s_own_never_re_stamped(isolated):
    K.record_climate_fetch(_fetch())
    path = isolated / "vertical-climate.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    rec["measured_at"] = old
    rec["datasets"]["oni"]["fetched_at"] = old
    path.write_text(json.dumps(rec), encoding="utf-8")
    m = _k13()
    assert m["as_of"] == old
    assert _block(m, "climate")["datasets"][0]["age_days"] >= 29.9


def test_an_election_snapshot_with_rows_is_the_elections_first_slice(isolated, monkeypatch):
    _snapshot(monkeypatch, _SNAP)
    m = _k13()
    block = _block(m, "elections")
    assert block["state"] == "recorded" and block["first_slice"] is True
    assert block["snapshot_rows"] == 42 and block["floor_countries"] > 0
    assert (m["verdict"], m["value"], m["n"], m["as_of"]) == ("measured-no-bar", 1, 6, "2026-11-01")


def test_an_empty_snapshot_is_recorded_but_is_no_first_slice(isolated, monkeypatch):
    """A snapshot on disk with no rows is a measurement (the run found nothing), like a climate source with no figures."""
    _snapshot(monkeypatch, {**_SNAP, "rows": 0})
    m = _k13()
    block = _block(m, "elections")
    assert block["state"] == "recorded" and block["first_slice"] is False
    assert "holds no rows" in block["reason"]
    assert (m["verdict"], m["value"], m["as_of"]) == ("measured-no-bar", 0, "2026-11-01")
    assert K.run_kpi_selftest()["passed"]


def test_an_empty_answer_for_one_unit_never_erases_another_unit_s_figures(isolated):
    """A fetch is one station or region; the record is per dataset. Station B answering empty after station A brought
    figures must not turn the dataset's first slice off."""
    K.record_climate_fetch(_fetch("ghcnd", figures=120, new=120, param="A"))
    K.record_climate_fetch(_fetch("ghcnd", figures=0, new=0, param="B"))
    m = _k13()
    row = _block(m, "climate")["datasets"][0]
    assert row["outcome"] == "source gave no figures"  # the last fetch is still told as it was
    assert row["last_fetch_with_figures_at"] == "2026-11-18T10:00:00+00:00"
    assert _block(m, "climate")["first_slice"] is True and m["value"] == 1


def test_a_record_that_does_not_say_what_was_stored_claims_nothing(isolated):
    K.record_climate_fetch({"dataset": "oni", "fetched_at": "2026-11-18T10:00:00+00:00", "figures": 50})
    row = _block(_k13(), "climate")["datasets"][0]
    assert row["outcome"] == "fetched, what it stored was not recorded"


def test_a_tampered_date_degrades_one_block_never_the_whole_metric(isolated, monkeypatch):
    _snapshot(monkeypatch, _SNAP)
    K.record_climate_fetch(_fetch())
    path = isolated / "vertical-climate.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["measured_at"] = 12345
    rec["datasets"]["oni"]["fetched_at"] = ["not", "a", "date"]
    path.write_text(json.dumps(rec), encoding="utf-8")
    m = _k13()
    assert m["verdict"] == "measured-no-bar" and m["value"] == 2
    assert m["as_of"] == "2026-11-01"  # the one readable date
    assert _block(m, "climate")["datasets"][0]["age_days"] is None


def test_both_verticals_are_counted_apart_never_blended(isolated, monkeypatch):
    _snapshot(monkeypatch, _SNAP)
    K.record_climate_fetch(_fetch())
    m = _k13()
    assert (m["value"], m["n"]) == (2, 6)
    assert "climate, elections" in m["method"]


def test_one_vertical_failing_never_hides_the_other(isolated, monkeypatch):
    from src.events import catalog

    def boom(today=None):
        raise RuntimeError("catalogue unreadable")

    monkeypatch.setattr(catalog, "layered_events", boom)
    K.record_climate_fetch(_fetch())
    m = _k13()
    assert _block(m, "elections")["reason"] == "its block could not be read (RuntimeError)"
    assert (m["verdict"], m["value"]) == ("measured-no-bar", 1)


def test_the_kpi_get_opens_no_socket(isolated, monkeypatch):
    """The board reads; it never fetches. Any name lookup or connection, on either vertical's path, fails the test."""
    import socket

    K.record_climate_fetch(_fetch())
    K.record_law_coverage(_law_report())
    K.record_osm_lane([_osm_row()])
    K.record_wiki_coverage([_wiki_row()], True)
    K.record_medical_fetch(_medical())
    _snapshot(monkeypatch, _SNAP)

    def refuse(*a, **k):
        raise AssertionError("the KPI GET reached the network")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    m = _k13()
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 6, 6)
    assert all(b["state"] == "recorded" for b in m["verticals"])  # every block read its record, none hit its error path


def test_the_fetch_job_records_after_its_session_closed(isolated, monkeypatch):
    """The record is written by the job, once the session that stored the figures has closed."""
    from src.api import climate as api
    from src.database import session as dbs
    from src.stats import climate

    order: list[str] = []

    @contextlib.contextmanager
    def scope():
        yield object()
        order.append("committed")

    def fake_fetch(db, dataset, param, progress=None):
        order.append("stored")
        return _fetch(dataset)

    real_record = K.record_climate_fetch

    def spy(record):
        order.append("recorded")
        return real_record(record)

    monkeypatch.setattr(dbs, "session_scope", scope)
    monkeypatch.setattr(climate, "fetch_and_store", fake_fetch)
    monkeypatch.setattr(K, "record_climate_fetch", spy)

    class Ctx:
        def set_progress(self, **kw):
            pass

    out = api._fetch_worker(Ctx(), dataset="oni", param=None)
    assert out["dataset"] == "oni"
    assert order == ["stored", "committed", "recorded"]
    assert _block(_k13(), "climate")["state"] == "recorded"


def test_a_session_that_fails_to_commit_records_nothing(isolated, monkeypatch):
    from src.api import climate as api
    from src.database import session as dbs
    from src.stats import climate

    @contextlib.contextmanager
    def scope():
        yield object()
        raise RuntimeError("commit failed")

    monkeypatch.setattr(dbs, "session_scope", scope)
    monkeypatch.setattr(climate, "fetch_and_store", lambda db, d, p, progress=None: _fetch(d))

    class Ctx:
        def set_progress(self, **kw):
            pass

    with pytest.raises(RuntimeError):
        api._fetch_worker(Ctx(), dataset="oni", param=None)
    assert not (isolated / "vertical-climate.json").exists()


def test_a_failing_record_never_fails_a_fetch_already_kept(isolated, monkeypatch):
    from src.api import climate as api
    from src.database import session as dbs
    from src.stats import climate

    @contextlib.contextmanager
    def scope():
        yield object()

    def broken(record):
        raise OSError("disk full")

    monkeypatch.setattr(dbs, "session_scope", scope)
    monkeypatch.setattr(climate, "fetch_and_store", lambda db, d, p, progress=None: _fetch(d))
    monkeypatch.setattr(K, "record_climate_fetch", broken)

    class Ctx:
        def set_progress(self, **kw):
            pass

    assert api._fetch_worker(Ctx(), dataset="oni", param=None)["figures"] == 120


# --------------------------------------------------------------------------- row 184: the law lane (R751(a))
def _wiki_row(edition: str = "fr", *, ran: bool = True, pages=150, total=100, hot=2, warm=5, gaps=1,
              event: str | None = "2026-11-18T06:00:00+00:00", complete: bool = False) -> dict:
    if not ran:
        return {"edition": edition, "has_run": False, "reason": "no-run-yet"}
    return {"edition": edition, "has_run": True, "pages_seen": pages, "edition_articles": total, "walk_complete": complete,
            "full_text": {"hot_pages_with_text": hot, "warm_pages_with_text": warm},
            "gaps": {"total": gaps, "by_reason": {"retention": gaps}}, "last_event_recorded_at": event}


def _osm_row(alpha3: str = "FRA", *, status: str = "complete", diffs=3, gaps=1,
             applied: str | None = "2026-11-18T06:00:00+00:00") -> dict:
    return {"alpha3": alpha3, "status": status, "diffs_recorded": diffs, "gaps_total": gaps, "last_applied_at": applied}


def _law_report(docs: int = 12, *, floor: dict | None = None, readable: bool = True) -> dict:
    return {
        "documents": docs, "baselined": docs - 2,
        "catalog": {"readable": readable, "error": None if readable else "unreadable"},
        "jurisdictions": [
            {"jurisdiction": "fr", "tracked": 8, "never_checked": 1, "oldest_check_age_hours": 70.0,
             "newest_check_age_hours": 2.5},
            {"jurisdiction": "uk", "tracked": 4, "never_checked": 0, "oldest_check_age_hours": 300.0,
             "newest_check_age_hours": 9.0},
        ],
        "floor": {"by_state": floor if floor is not None else {"tracked": ["fr", "gb"], "verified-not-yet-tracked": ["de"],
                                                                 "unverified": ["es", "it"], "no-eligible-source": []}},
    }


def test_the_law_lane_is_a_block_under_k13_never_a_new_metric(isolated):
    assert K.record_law_coverage(_law_report()) is not None
    snap = K.kpi_snapshot()
    assert len(snap["metrics"]) == 14  # R751(a): a block, no new K id
    m = next(x for x in snap["metrics"] if x["id"] == "K13")
    block = _block(m, "law")
    assert (block["kind"], block["state"], block["first_slice"]) == ("lane", "recorded", True)
    assert (block["documents"], block["jurisdictions"], block["never_checked"]) == (12, 2, 1)
    assert (block["oldest_check_age_hours"], block["newest_check_age_hours"]) == (300.0, 2.5)
    assert block["floor_by_state"] == {"tracked": 2, "verified-not-yet-tracked": 1, "unverified": 2, "no-eligible-source": 0}
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 1, 6)
    assert K.run_kpi_selftest()["passed"]


def test_the_law_record_names_no_country_or_jurisdiction(isolated):
    K.record_law_coverage(_law_report())
    text = (isolated / "lane-law-coverage.json").read_text(encoding="utf-8")
    for name in ('"fr"', '"uk"', '"gb"', '"de"'):
        assert name not in text


def test_a_report_with_no_tracked_document_is_recorded_with_no_first_slice(isolated):
    K.record_law_coverage(_law_report(0))
    m = _k13()
    block = _block(m, "law")
    assert block["state"] == "recorded" and block["first_slice"] is False
    assert "no tracked document" in block["reason"]
    assert (m["verdict"], m["value"]) == ("measured-no-bar", 0)


def test_an_unreadable_catalogue_keeps_the_floor_unknown_not_zero(isolated):
    """The real report's floor when the catalogue cannot be read: the states that need the catalogue are never looked up,
    so they read as unknown, never as a counted 0."""
    from src.law.coverage import floor_report

    floor = floor_report([], None, reason="catalogue unreadable")
    assert floor.get("state") == "unchecked" and isinstance(floor.get("by_state"), dict)  # the shape the record must handle
    report = {**_law_report(), "floor": floor, "catalog": {"readable": False, "error": "x"}}
    K.record_law_coverage(report)
    block = _block(_k13(), "law")
    counts = block["floor_by_state"]
    assert counts["unchecked"] > 0 and counts["tracked"] == 0
    for state in ("verified-not-yet-tracked", "unverified", "no-eligible-source"):
        assert counts[state] is None, state
    assert block["catalog_readable"] is False and block["floor_state"] == "unchecked"
    assert "never looked up" in block["method"]


def test_odd_check_ages_never_reach_the_record(isolated):
    report = _law_report()
    report["jurisdictions"] = [
        {"never_checked": 0, "oldest_check_age_hours": float("nan"), "newest_check_age_hours": -5.0},
        {"never_checked": 0, "oldest_check_age_hours": True, "newest_check_age_hours": float("inf")},
        {"never_checked": 0, "oldest_check_age_hours": 40.0, "newest_check_age_hours": 3.0},
    ]
    K.record_law_coverage(report)
    text = (isolated / "lane-law-coverage.json").read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    block = _block(_k13(), "law")
    assert (block["oldest_check_age_hours"], block["newest_check_age_hours"]) == (40.0, 0.0)


@pytest.mark.parametrize("bad", [None, {}, {"jurisdictions": []}])
def test_a_report_without_its_document_count_writes_nothing(isolated, bad):
    assert K.record_law_coverage(bad) is None
    assert not (isolated / "lane-law-coverage.json").exists()


def test_the_law_report_route_writes_the_record_and_the_kpi_get_does_not(isolated):
    """The record is written where the report is made; reading K13 never runs the report."""
    from src.api.diagnostics import system
    from src.law import coverage

    calls: list[int] = []

    def fake_report(db, **kw):
        calls.append(1)
        return _law_report()

    import unittest.mock as mock

    with mock.patch.object(coverage, "law_coverage_report", fake_report):
        system.law_coverage(download=False, db=object())
        assert calls == [1]
        assert _block(_k13(), "law")["state"] == "recorded"
        assert calls == [1]  # the GET did not run the report again


# --------------------------------------------------------------------------- row 184: the OSM lane (R751(a))
from tests import _osm_lane_helpers  # noqa: E402 - the OSM lane's own fixtures, for the end-to-end tests below
from tests.test_osm_apply import _extract  # noqa: E402

osm_lane_dir = _osm_lane_helpers.osm_lane_dir


def test_the_osm_lane_is_a_block_under_k13_counted_never_named(isolated):
    rows = [_osm_row("FRA"), _osm_row("DEU", diffs=0, gaps=0, applied=None),
            _osm_row("ITA", status="ingesting", diffs=None, gaps=None, applied=None)]
    assert K.record_osm_lane(rows) is not None
    text = (isolated / "lane-osm.json").read_text(encoding="utf-8")
    for code in ("FRA", "DEU", "ITA"):
        assert code not in text
    snap = K.kpi_snapshot()
    assert len(snap["metrics"]) == 14  # a block, no new K id
    block = _block(next(x for x in snap["metrics"] if x["id"] == "K13"), "osm")
    assert (block["kind"], block["state"], block["first_slice"]) == ("lane", "recorded", True)
    assert block["countries"] == 3 and block["countries_by_status"] == {"complete": 2, "ingesting": 1}
    assert (block["countries_with_change_files"], block["change_files_recorded"], block["gaps_total"]) == (1, 3, 1)
    # A lane that predates the run or gap table: unknown, said apart, never folded into the sums as 0.
    assert (block["countries_change_files_unknown"], block["countries_gaps_unknown"]) == (1, 1)
    assert "unknown, never 0" in block["method"]
    assert block["newest_change_file_applied_at"] == "2026-11-18T06:00:00+00:00"
    assert K.run_kpi_selftest()["passed"]


def test_an_osm_lane_with_no_complete_country_has_no_first_slice(isolated):
    K.record_osm_lane([_osm_row(status="ingesting", diffs=0, gaps=0, applied=None)])
    block = _block(_k13(), "osm")
    assert block["state"] == "recorded" and block["first_slice"] is False
    assert "cut to completion" in block["reason"]


def test_an_absent_osm_lane_is_a_measurement_not_a_gap(isolated):
    K.record_osm_lane(None)
    m = _k13()
    block = _block(m, "osm")
    assert (block["state"], block["lane"], block["first_slice"]) == ("recorded", "absent", False)
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 0, 6)


def test_the_newest_applied_time_is_compared_by_age_and_odd_ones_are_ignored(isolated):
    rows = [_osm_row("AAA", applied="2026-11-10T00:00:00+00:00"), _osm_row("BBB", applied="2026-11-12T00:00:00"),
            _osm_row("CCC", applied="not a date"), _osm_row("DDD", applied=None), "not a row"]
    K.record_osm_lane(rows)
    assert _block(_k13(), "osm")["newest_change_file_applied_at"] == "2026-11-12T00:00:00"


@pytest.mark.parametrize("bad", ["rows", 3, {"a": 1}])
def test_osm_rows_that_are_not_a_list_write_nothing(isolated, bad):
    assert K.record_osm_lane(bad) is None
    assert not (isolated / "lane-osm.json").exists()


def test_the_bundle_member_records_the_lane_and_the_kpi_get_reads_it_without_opening_the_lane(osm_lane_dir, monkeypatch):
    """End to end: the OSM diagnostics member (what the bundle calls) writes the record; the KPI GET reads it and never
    opens the lane store."""
    from src.osm import diagnostics as D
    from src.osm import ingest
    from src.versioned import store

    _snapshot(monkeypatch, _NONE)
    got = D.diagnostics_member(20_000)
    assert got["lane"] == "absent"
    assert _block(_k13(), "osm")["lane"] == "absent"

    assert ingest.ingest_country(_extract(osm_lane_dir), "ZZ", reader="python").status == "complete"
    D.diagnostics_member(20_000)
    assert "ZZZ" not in (osm_lane_dir / "diagnostics" / "lane-osm.json").read_text(encoding="utf-8")

    def refuse(*a, **k):
        raise AssertionError("the KPI GET opened the OSM lane")

    monkeypatch.setattr(store, "lane_session", refuse)
    monkeypatch.setattr(store, "lane_exists", refuse)
    block = _block(_k13(), "osm")
    assert (block["first_slice"], block["countries"], block["countries_by_status"]) == (True, 1, {"complete": 1})


def test_a_failing_record_never_breaks_the_member(osm_lane_dir, monkeypatch):
    from src.osm import diagnostics as D

    def boom(rows):
        raise RuntimeError("disk full")

    monkeypatch.setattr(K, "record_osm_lane", boom)
    got = D.diagnostics_member(20_000)
    assert got["lane"] == "absent" and "error" not in got


def test_a_lane_where_no_country_can_say_records_unknown_never_zero(isolated):
    """Every country on a lane older than the run and gap tables: the sums are unknown, never 0."""
    K.record_osm_lane([_osm_row("AAA", diffs=None, gaps=None, applied=None),
                       _osm_row("BBB", diffs=None, gaps=None, applied=None)])
    block = _block(_k13(), "osm")
    assert (block["change_files_recorded"], block["gaps_total"]) == (None, None)
    assert (block["countries_change_files_unknown"], block["countries_gaps_unknown"]) == (2, 2)
    assert "an unknown number of daily change files" in block["method"]
    assert "an unknown number of gaps" in block["method"] and "their gaps are unknown, never 0" in block["method"]
    assert " 0 daily change files" not in block["method"]


def test_a_hand_edited_osm_record_never_reaches_the_method_as_a_claim(isolated):
    K.record_osm_lane([_osm_row()])
    path = isolated / "lane-osm.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec.update({"countries": "many", "change_files_recorded": True, "countries_change_files_unknown": True,
                "countries_by_status": {"complete": True}})
    path.write_text(json.dumps(rec), encoding="utf-8")
    block = _block(_k13(), "osm")
    assert block["first_slice"] is False
    assert "many" not in block["method"] and "True" not in block["method"]
    assert "an unknown number of countries listed" in block["method"]


def test_a_failing_record_never_breaks_the_member_on_a_present_lane(osm_lane_dir, monkeypatch):
    from src.osm import diagnostics as D
    from src.osm import ingest

    assert ingest.ingest_country(_extract(osm_lane_dir), "ZZ", reader="python").status == "complete"

    def boom(rows):
        raise RuntimeError("disk full")

    monkeypatch.setattr(K, "record_osm_lane", boom)
    got = D.diagnostics_member(20_000)
    assert got["lane"] == "present" and "error" not in got and got["countries_without_updates"] == ["ZZZ"]


# --------------------------------------------------------------------------- row 184: the wiki lane (R751(a))
def test_the_wiki_lane_is_a_block_under_k13_counted_never_named(isolated):
    rows = [_wiki_row("fr", complete=True), _wiki_row("de", pages=0, hot=0, warm=None, gaps=0, event=None),
            _wiki_row("en", ran=False), _wiki_row("xx", total=None, hot=0, warm=0, pages=40, event="2026-11-19T01:00:00")]
    assert K.record_wiki_coverage(rows, True) is not None
    text = (isolated / "lane-wiki.json").read_text(encoding="utf-8")
    for code in ('"fr"', '"de"', '"en"', '"xx"'):
        assert code not in text
    snap = K.kpi_snapshot()
    assert len(snap["metrics"]) == 14  # a block, no new K id
    block = _block(next(x for x in snap["metrics"] if x["id"] == "K13"), "wiki")
    assert (block["kind"], block["state"], block["first_slice"]) == ("lane", "recorded", True)
    assert (block["editions_listed"], block["editions_with_a_run"], block["editions_walk_complete"]) == (4, 3, 1)
    assert (block["editions_with_pages_seen"], block["editions_with_text"]) == (2, 1)
    assert (block["pages_seen"], block["edition_articles"], block["editions_without_total"]) == (190, 200, 1)
    # Text bounds per edition: fr max(2,5)=5 / 2+5=7; de (HOT 0, WARM unknown) 0 / unknown; xx 0 / 0.
    # The upper bound is a bound only when every part is known; de's WARM is not, so it is unknown and the text says "at least".
    assert (block["pages_with_text_lower_bound"], block["pages_with_text_upper_bound"]) == (5, None)
    assert "at least 5 pages with a text" in block["method"]
    assert block["editions_text_bound_unknown"] == 1 and block["gaps_total"] == 2
    assert block["newest_event_recorded_at"] == "2026-11-19T01:00:00"
    assert "1 editions' own article count unknown, never 0" in block["method"]
    assert K.run_kpi_selftest()["passed"]


def test_a_wiki_report_with_nothing_seen_is_recorded_with_no_first_slice(isolated):
    K.record_wiki_coverage([_wiki_row(ran=False), _wiki_row("de", ran=False)], False)
    m = _k13()
    block = _block(m, "wiki")
    assert (block["state"], block["first_slice"], block["measured"]) == ("recorded", False, False)
    # No edition ran, so no edition could give a figure: unknown, never 0.
    for key in ("pages_seen", "edition_articles", "gaps_total", "pages_with_text_lower_bound", "pages_with_text_upper_bound"):
        assert block[key] is None, key
    assert "no edition with pages seen" in block["reason"] and " 0 pages seen" not in block["method"]
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 0, 6)


def test_a_wiki_sum_no_edition_could_give_is_unknown_never_zero(isolated):
    K.record_wiki_coverage([_wiki_row(pages=None, total=None, hot=0, warm=None, gaps=None)], True)
    block = _block(_k13(), "wiki")
    assert (block["pages_seen"], block["edition_articles"], block["gaps_total"]) == (None, None, None)
    assert block["pages_with_text_upper_bound"] is None and block["pages_with_text_lower_bound"] == 0
    assert "an unknown number of pages seen" in block["method"]
    assert "an unknown number of gaps" in block["method"]


@pytest.mark.parametrize("rows,measured", [(None, True), ("rows", True), ([], "yes")])
def test_a_wiki_report_of_the_wrong_shape_writes_nothing(isolated, rows, measured):
    assert K.record_wiki_coverage(rows, measured) is None
    assert not (isolated / "lane-wiki.json").exists()


def test_a_hand_edited_wiki_record_never_reaches_the_method_as_a_claim(isolated):
    K.record_wiki_coverage([_wiki_row()], True)
    path = isolated / "lane-wiki.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec.update({"editions_with_pages_seen": True, "editions_with_text": "lots", "pages_seen": -3})
    path.write_text(json.dumps(rec), encoding="utf-8")
    block = _block(_k13(), "wiki")
    assert block["first_slice"] is False
    assert "lots" not in block["method"] and "True" not in block["method"] and "-3" not in block["method"]


def test_the_coverage_report_records_and_the_kpi_get_does_not_open_the_lane(tmp_path, monkeypatch):
    """End to end: the per-edition report (what Living sources, the counters and the bundle call) writes the record from its
    full rows, the compact bundle form included; the KPI GET reads it and never opens the lane."""
    from datetime import UTC, datetime

    from src.versioned import store
    from src.wiki.coverage import edition_coverage
    from src.wiki.lane_models import WikiWalkCursor

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    _snapshot(monkeypatch, _NONE)
    store.dispose_all()
    store.create_lane("wiki")
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    try:
        with store.lane_session("wiki") as lane:
            lane.add(WikiWalkCursor(edition="fr", pages_seen=150, edition_articles=100, started_at=t0, updated_at=t0))
            lane.commit()
            edition_coverage(lane, now=t0, newest_gaps=False)  # the compact form trims unrun rows; the record must not
        path = tmp_path / "diagnostics" / "lane-wiki.json"
        assert '"fr"' not in path.read_text(encoding="utf-8")

        def refuse(*a, **k):
            raise AssertionError("the KPI GET opened the wiki lane")

        monkeypatch.setattr(store, "lane_session", refuse)
        block = _block(_k13(), "wiki")
        assert (block["first_slice"], block["editions_with_a_run"], block["pages_seen"]) == (True, 1, 150)
        assert block["editions_listed"] >= 12  # the twelve are listed whether or not they ran
    finally:
        store.dispose_all()


def test_a_failing_record_never_breaks_the_coverage_report(tmp_path, monkeypatch):
    from src.versioned import store
    from src.wiki.coverage import edition_coverage

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    store.dispose_all()
    store.create_lane("wiki")

    def boom(rows, measured):
        raise RuntimeError("disk full")

    monkeypatch.setattr(K, "record_wiki_coverage", boom)
    try:
        with store.lane_session("wiki") as lane:
            rep = edition_coverage(lane)
        assert rep["measured"] is False and rep["reason"] == "lane-never-run" and len(rep["editions"]) >= 12
    finally:
        store.dispose_all()


def test_a_wiki_upper_bound_never_sits_below_the_lower(isolated):
    """HOT is always counted, WARM may be unknown: a partial upper sum could read "between 10 and 0". It is unknown instead."""
    K.record_wiki_coverage([_wiki_row("aa", hot=10, warm=None), _wiki_row("bb", hot=0, warm=0)], True)
    block = _block(_k13(), "wiki")
    assert (block["pages_with_text_lower_bound"], block["pages_with_text_upper_bound"]) == (10, None)
    assert "between" not in block["method"] and "at least 10 pages with a text" in block["method"]
    K.record_wiki_coverage([_wiki_row("aa", hot=10, warm=4), _wiki_row("bb", hot=0, warm=0)], True)
    assert "between 10 and 14 pages with a text" in _block(_k13(), "wiki")["method"]


def test_an_unreadable_last_event_is_counted_apart_from_none(isolated):
    row = {**_wiki_row(event=None), "last_event_unreadable": True}
    K.record_wiki_coverage([row], True)
    block = _block(_k13(), "wiki")
    assert block["newest_event_recorded_at"] is None and block["editions_event_unreadable"] == 1
    assert "last event could not be read" in block["method"]


# --------------------------------------------------------------------------- the medical block (row 173, PR 4)


def test_a_medical_fetch_is_a_block_with_counts_and_its_newest_file(isolated):
    K.record_medical_fetch(_medical())
    block = _block(_k13(), "medical")
    assert block["state"] == "recorded" and block["first_slice"] is True
    assert block["newest_file_applied"] == "pubmed25n1400.xml.gz"
    assert block["coverage"]["cited_not_found"] == 7  # the gap travels with the block (R750)
    assert block["outcome"] == "fetched, applied new update files"


def test_the_medical_record_never_holds_a_paper_id(isolated):
    K.record_medical_fetch(_medical(last_file="10.1000/needle-doi", cited_ids=["12345"], pmid=12345))
    text = (isolated / "vertical-medical.json").read_text(encoding="utf-8")
    assert "needle" not in text and "12345" not in text
    assert _block(_k13(), "medical")["first_slice"] is False  # no NLM file name: nothing applied that it can name


def test_a_medical_fetch_that_applied_nothing_or_failed_says_so(isolated):
    K.record_medical_fetch(_medical(applied=0, last_file=None))
    assert _block(_k13(), "medical")["outcome"] == "fetched, no new update file applied"
    K.record_medical_fetch(_medical(applied=0, failed="FileRefused"))
    assert "FileRefused" in _block(_k13(), "medical")["outcome"]
