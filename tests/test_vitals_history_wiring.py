"""The vitals history is wired where it must be: the liveness tick, the bundle, the route, the map.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The recorder itself is tested in ``test_vitals_history.py``. Here: that the session ledger's 5-second
liveness thread starts it, ticks it and flushes it at a clean end (with no thread of its own), that
the bundle carries it as ``vitals.json`` in a light run as well as a full one, and that its route is
classified, so the run-time coverage report and the CI ratchet both see it.
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

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


def test_a_liveness_thread_a_test_left_running_is_stopped_before_it_can_tick_the_next_tests_recorder(
    monkeypatch, tmp_path
):
    """Seen once on CI: a test that boots the app leaves the daemon thread ticking, and the loop's
    ``tick()`` reads the REAL clock, so a later test that started the recorder found a sample stamped at
    the run's own wall time ahead of its injected rows. The autouse fixture stops the thread through this
    helper, which must leave no live thread and must not flush into the current data dir."""
    from tests.conftest import _stop_leaked_liveness_thread

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    sh._reset_for_tests()
    v.reset_for_tests()
    monkeypatch.setattr(sh, "MEMORY_WATCH_S", 0.01)
    monkeypatch.setattr(session_hwm, "observe", lambda *a, **k: None)
    ticked = threading.Event()
    monkeypatch.setattr(v, "tick", lambda *a, **k: ticked.set())
    try:
        assert sh.start_liveness() is True
        assert ticked.wait(5.0), "the liveness loop never ticked"
        v._path().unlink(missing_ok=True)  # start() may have written nothing; the flush below must not
        _stop_leaked_liveness_thread()
        assert sh._THREAD is None
        assert not any(t.name == "oo-session-liveness" and t.is_alive() for t in threading.enumerate())
        assert not v._path().exists()  # stopped, not stop_liveness(): no flush into the current data dir
    finally:
        sh._reset_for_tests()


def test_the_helper_waits_for_a_tick_in_flight_and_keeps_a_thread_that_outlives_the_wait(monkeypatch, tmp_path):
    """Finding L2 of the read. The join is what makes the stop real (a tick in flight must finish before the
    recorder is reset), and a thread still alive after the wait stays recorded as the process's thread, so a
    later ``start_liveness`` does not start a second one."""
    from tests.conftest import _stop_leaked_liveness_thread

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    sh._reset_for_tests()
    v.reset_for_tests()
    monkeypatch.setattr(sh, "MEMORY_WATCH_S", 0.01)
    inside, release = threading.Event(), threading.Event()

    def held_observe(*_a, **_k):
        inside.set()
        release.wait(30.0)  # in flight until the test lets it go: no stall of the machine can end it early

    monkeypatch.setattr(session_hwm, "observe", held_observe)
    monkeypatch.setattr(v, "tick", lambda *a, **k: None)
    try:
        assert sh.start_liveness() is True
        assert inside.wait(5.0)
        thread = sh._THREAD
        _stop_leaked_liveness_thread(timeout=0.01)  # the tick in flight outlives this wait
        assert thread is not None and thread.is_alive() and sh._THREAD is thread
        assert sh.start_liveness() is False  # no second thread
        release.set()
        _stop_leaked_liveness_thread()  # the real wait: the tick finishes, the loop ends
        assert not thread.is_alive() and sh._THREAD is None
    finally:
        release.set()
        sh._reset_for_tests()


def test_the_isolation_fixture_stops_the_leaked_thread_before_it_resets_the_recorder():
    """A guard on the fixture itself (a fixture cannot be called from a test): it is an autouse fixture, and on
    the way OUT (after the ``yield``) the stop is a statement of its own, called with no argument (so the wait
    stays the helper's default and no condition or wrapper can skip it), with nothing but imports ahead of it
    and a reset of the recorder after it, so a tick in flight finishes before the recorder is wiped. Read from
    the syntax tree, not sliced out of the source text."""
    tree = ast.parse((Path(__file__).parent / "conftest.py").read_text(encoding="utf-8"))
    fixture = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_vitals_history_isolated"), None
    )
    assert fixture is not None, "the isolation fixture is gone"
    assert any(
        isinstance(d, ast.Call)
        and getattr(d.func, "attr", None) == "fixture"
        and any(k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True for k in d.keywords)
        for d in fixture.decorator_list
    ), "the isolation fixture is not an autouse pytest fixture"

    def calls(node: ast.AST, name: str) -> bool:
        return any(
            isinstance(c, ast.Call) and name in (getattr(c.func, "id", None), getattr(c.func, "attr", None))
            for c in ast.walk(node)
        )

    body = fixture.body
    yielded = next(
        (i for i, st in enumerate(body) if isinstance(st, ast.Expr) and isinstance(st.value, ast.Yield)), None
    )
    assert yielded is not None, "the fixture has no top-level yield"
    teardown = body[yielded + 1 :]

    def is_bare_stop(st: ast.stmt) -> bool:
        return (
            isinstance(st, ast.Expr)
            and isinstance(st.value, ast.Call)
            and isinstance(st.value.func, ast.Name)
            and st.value.func.id == "_stop_leaked_liveness_thread"
            and not st.value.args
            and not st.value.keywords
        )

    stop = next((i for i, st in enumerate(teardown) if is_bare_stop(st)), None)
    assert stop is not None, "no bare call of the stop helper, as a statement of its own, after the yield"
    assert all(isinstance(st, ast.Import | ast.ImportFrom) for st in teardown[:stop]), "something can skip the stop"
    reset = next((i for i, st in enumerate(teardown) if calls(st, "reset_for_tests")), None)
    assert reset is not None and stop < reset


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
    from src.api import diagnostics_slots as slots

    member = dict(slots.members())["vitals.json"]()  # the slot's own producer
    assert served["schema"] == member["schema"] == v.SCHEMA
    assert served["columns"] == member["columns"] == list(v.COLUMNS)
