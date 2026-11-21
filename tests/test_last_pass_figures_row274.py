"""Row 274: the diagnostics report never shows a pass that never ran as "0 fetch failures".

The scheduler keeps its last result in memory only, so after every start it is None until a pass
finishes. The performance report read that as ``fetch_failed: 0``. These pin the four cases and the
wiring: no pass, a pass without a tally, a tally that says 0, a tally that says N.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from src.api.diagnostics import performance
from src.api.diagnostics.performance import (
    LAST_PASS_NO_PASS,
    LAST_PASS_NO_TALLY,
    LAST_PASS_UNREADABLE,
    last_pass_figures,
)


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_no_pass_since_start_is_null_with_its_reason():
    out = last_pass_figures(None)
    assert out["last_pass_fetch_failed"] is None
    assert out["last_pass_measured"] is False
    assert out["last_pass_absent_reason"] == LAST_PASS_NO_PASS
    assert "last_pass_error" not in out


def test_a_pass_without_a_tally_is_null_with_its_reason():
    for result in ({}, {"tally": None}, {"tally": "?"}, {"sources_processed": 3}):
        out = last_pass_figures(result)
        assert out["last_pass_fetch_failed"] is None, result
        assert out["last_pass_measured"] is False
        assert out["last_pass_absent_reason"] == LAST_PASS_NO_TALLY


def test_a_recorded_zero_is_a_measured_zero():
    # The runner's tally is sparse: a key no source incremented is absent, and that is a real 0.
    for tally in ({"fetch_failed": 0, "stored": 4}, {"stored": 4}):
        out = last_pass_figures({"tally": tally})
        assert out["last_pass_fetch_failed"] == 0
        assert out["last_pass_measured"] is True
        assert "last_pass_absent_reason" not in out


def test_a_count_that_is_not_a_whole_number_is_never_turned_into_zero():
    for raw in (None, "3", 2.5, True):
        out = last_pass_figures({"tally": {"fetch_failed": raw}})
        assert out["last_pass_fetch_failed"] is None, raw
        assert out["last_pass_measured"] is False
        assert out["last_pass_absent_reason"] == LAST_PASS_UNREADABLE


def test_a_recorded_count_is_carried():
    out = last_pass_figures({"tally": {"fetch_failed": 7, "ff:http_403": 7}})
    assert out == {"last_pass_fetch_failed": 7, "last_pass_measured": True}


def test_a_newer_pass_that_died_is_named_beside_the_older_figure():
    out = last_pass_figures({"tally": {"fetch_failed": 2}}, "OperationalError")
    assert out["last_pass_fetch_failed"] == 2
    assert out["last_pass_error"] == "OperationalError"
    out = last_pass_figures(None, "OSError")
    assert out["last_pass_fetch_failed"] is None
    assert out["last_pass_absent_reason"] == LAST_PASS_NO_PASS
    assert out["last_pass_error"] == "OSError"


def test_the_report_reads_the_figure_through_the_helper_and_nowhere_else():
    src = inspect.getsource(performance.performance_report)
    assert "last_pass_figures(" in src
    assert '_last_tally.get("fetch_failed") or 0' not in src
    assert '"last_pass_fetch_failed": int(' not in src


def test_the_report_on_a_fresh_process_says_no_pass(client):
    from src.scheduler.runner import get_scheduler

    sched = get_scheduler()
    saved = (sched._last_result, sched._last_error)
    sched._last_result, sched._last_error = None, None
    try:
        r = client.post("/api/diagnostics/performance", params={"selftest": "false"})
    finally:
        sched._last_result, sched._last_error = saved
    assert r.status_code == 200
    col = r.json()["data"]["collection"]
    assert col["last_pass_fetch_failed"] is None
    assert col["last_pass_measured"] is False
    assert col["last_pass_absent_reason"] == LAST_PASS_NO_PASS
    assert col["fetch_failed_reasons"] is None
