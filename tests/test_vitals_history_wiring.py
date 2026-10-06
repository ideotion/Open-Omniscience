"""The vitals history is wired where it must be: the liveness tick, the bundle, the route, the map.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The recorder itself is tested in ``test_vitals_history.py``. Here: that the session ledger's 5-second
liveness thread starts it, ticks it and flushes it at a clean end (with no thread of its own), that
the bundle carries it as ``vitals.json`` in a light run as well as a full one, and that its route is
classified, so the run-time coverage report and the CI ratchet both see it.
"""

from __future__ import annotations

import threading

from src.api import diagnostics as d
from src.api.diagnostics import bundle as b
from src.monitoring import session_history as sh
from src.monitoring import session_hwm
from src.monitoring import vitals_history as v


def test_the_liveness_thread_starts_ticks_and_flushes_the_history(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    sh._reset_for_tests()
    v.reset_for_tests()
    monkeypatch.setattr(sh, "MEMORY_WATCH_S", 0.01)
    monkeypatch.setattr(session_hwm, "observe", lambda *a, **k: None)
    ticked = threading.Event()
    count: list[int] = []

    def counting_tick(now=None):
        count.append(1)
        if len(count) >= 3:
            ticked.set()

    monkeypatch.setattr(v, "tick", counting_tick)
    try:
        assert sh.start_liveness() is True
        assert v._STARTED is True  # started where the liveness thread is started
        assert ticked.wait(5.0), "the liveness loop never called the vitals tick"
        assert [t.name for t in threading.enumerate()].count("oo-session-liveness") == 1
        assert not any("vitals" in t.name for t in threading.enumerate())  # no thread of its own
    finally:
        sh.stop_liveness()
    assert v._path().exists()  # a clean end writes the history it holds
    sh._reset_for_tests()


def test_a_tick_that_raises_does_not_stop_the_liveness_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    sh._reset_for_tests()
    v.reset_for_tests()
    monkeypatch.setattr(sh, "MEMORY_WATCH_S", 0.01)
    monkeypatch.setattr(session_hwm, "observe", lambda *a, **k: None)
    seen = threading.Event()
    calls: list[int] = []

    def boom(now=None):
        calls.append(1)
        if len(calls) >= 3:
            seen.set()
        raise RuntimeError("the history fell over")

    monkeypatch.setattr(v, "tick", boom)
    try:
        sh.start_liveness()
        assert seen.wait(5.0), "one failing tick ended the loop"
    finally:
        sh.stop_liveness()
        sh._reset_for_tests()


def test_the_bundle_carries_the_history_in_every_profile():
    names = [name for name, _fn in b._all_diagnostics_members(None)]
    assert names.count("vitals.json") == 1
    assert "vitals.json" not in b._LIGHT_DECLINED  # a light run keeps it: it is a read of a small file


def test_the_route_is_registered_and_classified():
    paths = [getattr(r, "path", "") for r in d.router.routes]
    assert "/api/diagnostics/vitals-history" in paths
    assert b._DIAG_COVERAGE_MAP["/vitals-history"] == "vitals.json"
    report = b._diagnostics_coverage_report()
    assert report["available"] is True
    assert "/vitals-history" not in report["unclassified"]
    assert "vitals.json" not in report["missing_bundle_members"]
    assert report["complete"] is True, report


def test_the_route_and_the_member_serve_the_same_document(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    v.reset_for_tests()
    served = d.vitals_history_report()
    member = b._vitals_history_member()
    assert served["schema"] == member["schema"] == v.SCHEMA
    assert served["columns"] == member["columns"] == list(v.COLUMNS)
