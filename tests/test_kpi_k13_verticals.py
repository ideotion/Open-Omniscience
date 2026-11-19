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


def test_nothing_recorded_is_not_measured_with_no_value_and_no_date(isolated):
    m = _k13()
    assert m["verdict"] == "not-measurable-here"
    assert m["value"] is None and m["as_of"] is None
    assert {b["vertical"]: b["state"] for b in m["verticals"]} == {"climate": "not-measured", "elections": "not-measured",
                                                                 "law": "not-measured"}
    assert all(b["reason"] for b in m["verticals"])
    assert K.run_kpi_selftest()["passed"]


def test_a_recorded_fetch_is_counted_with_its_own_date_and_an_open_bar(isolated):
    rec = K.record_climate_fetch(_fetch())
    assert rec is not None
    m = _k13()
    assert m["verdict"] == "measured-no-bar"
    assert "pending-ruling" in m["target"]
    assert (m["value"], m["n"]) == (1, 3)
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
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 0, 3)
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
    assert (m["verdict"], m["value"], m["n"], m["as_of"]) == ("measured-no-bar", 1, 3, "2026-11-01")


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
    assert (m["value"], m["n"]) == (2, 3)
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
    _snapshot(monkeypatch, _SNAP)

    def refuse(*a, **k):
        raise AssertionError("the KPI GET reached the network")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    m = _k13()
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 3, 3)
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
    assert (m["verdict"], m["value"], m["n"]) == ("measured-no-bar", 1, 3)
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
