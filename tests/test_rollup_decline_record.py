"""The reason a rollup build stopped survives the checks that come after it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, a running install: the boot's rollup step was "declined" after 921 s and the bundle could not say
why. ``last_skip`` is whatever declined most recently, every windowed serve that finds no rollup re-runs the
verdicts (533 ``trending-windows`` calls did), and the diagnostics run's own exclusive window was the last
to write it. The stop record itself (``_STATE["stopped"]``) was never exported. These tests pin that the reason
is exported and survives, and that the numbers it is read against (DuckDB's limit, whether it may offload)
travel with it.
"""

from __future__ import annotations

import time

import pytest

from src.analytics import rollup_serve


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    for name in ("_boot_order_verdict", "_memory_verdict", "_last_build_verdict", "_affordability_verdict"):
        monkeypatch.setattr(rollup_serve, name, lambda: None)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 1005.0)
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 7)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "built")
    keep = {k: rollup_serve._STATE[k] for k in ("last_skip", "stopped", "last_decline")}
    rollup_serve._STATE.update(last_skip=None, stopped=None, last_decline=None)
    yield
    rollup_serve._STATE.update(keep)


def _stop(monkeypatch, **extra):
    record = {"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 1005.0, "stage": "aggregate",
              "rows_done": 12_004_191, "rss_mb": 1500.0, "begin_rss_mb": 300.0, "mentions_total": 12_004_191,
              "epoch": 7, **extra}
    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", lambda: dict(record))
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"


def _again():
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    return rollup_serve._build_and_swap()


def test_a_build_stopped_part_way_is_exported_with_its_stage_and_numbers(monkeypatch):
    _stop(monkeypatch)
    st = rollup_serve.status()
    assert st["stopped"]["reason"] == "duckdb-limit" and st["stopped"]["stage"] == "aggregate"
    assert st["stopped"]["duckdb_limit_mb"] == 1005.0
    d = st["last_decline"]
    assert d["kind"] == "stopped" and d["reason"] == "duckdb-limit" and d["stage"] == "aggregate"
    assert d["rows_done"] == 12_004_191 and d["repeats"] == 0


def test_the_diagnostics_runs_own_exclusive_window_does_not_overwrite_the_reason(monkeypatch):
    _stop(monkeypatch)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict",
                        lambda: {"reason": "exclusive-hold", "at": time.time()})
    assert _again() == "declined"
    st = rollup_serve.status()
    assert st["last_skip"]["source"] == "exclusive", "last_skip says which verdict declined"
    assert st["last_skip"]["reason"] == "exclusive-hold"  # last_skip stays "whatever declined most recently"
    assert st["last_decline"]["reason"] == "duckdb-limit" and st["last_decline"]["stage"] == "aggregate"
    assert st["stopped"]["reason"] == "duckdb-limit"


def test_the_boots_ordering_decline_is_transient_too(monkeypatch):
    _stop(monkeypatch)
    monkeypatch.setattr(rollup_serve, "_boot_order_verdict", lambda: {"reason": "boot_order", "at": time.time()})
    assert _again() == "declined"
    assert rollup_serve.status()["last_decline"]["reason"] == "duckdb-limit"


def test_every_serve_request_finding_the_same_hold_counts_but_does_not_replace_the_stop(monkeypatch):
    _stop(monkeypatch)
    for _ in range(3):  # the 533 trending-windows calls re-ran the verdicts
        assert _again() == "declined"
    d = rollup_serve.status()["last_decline"]
    assert d["kind"] == "stopped" and d["stage"] == "aggregate" and d["rows_done"] == 12_004_191
    assert d["repeats"] == 3 and d["last_seen_at"] is not None
    assert rollup_serve.status()["last_skip"]["reason"] == "duckdb-limit"  # the verdict's echo


def test_a_different_decline_about_the_machine_replaces_it(monkeypatch):
    _stop(monkeypatch)
    rollup_serve._STATE["stopped"] = None  # the hold was released, so the stopped verdict no longer fires
    monkeypatch.setattr(rollup_serve, "_memory_verdict",
                        lambda: {"reason": "mem-low", "at": time.time(), "guard_reason": "available 90 MB"})
    assert _again() == "declined"
    d = rollup_serve.status()["last_decline"]
    assert d["kind"] == "skipped" and d["source"] == "memory" and d["reason"] == "mem-low"


def test_a_build_that_finishes_leaves_the_last_decline_as_history(monkeypatch):
    _stop(monkeypatch)
    rollup_serve._STATE["stopped"] = None
    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", lambda: None)
    assert _again() == "built"
    st = rollup_serve.status()
    assert st["stopped"] is None
    assert st["last_decline"]["reason"] == "duckdb-limit"  # what happened at the boot is not erased by a later build


def test_the_budget_a_stop_is_read_against_is_exported(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: True)
    assert rollup_serve.status()["build_budget"] == {"duckdb_limit_mb": 1005.0, "offload_allowed": False}
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    assert rollup_serve.status()["build_budget"]["offload_allowed"] is True


def test_an_encrypted_corpus_gets_no_offload_folder_so_duckdbs_limit_is_a_wall(monkeypatch, tmp_path):
    """The reading the 10-16 stop is inferred to be: nothing may spill, so 12 M staged rows meet the limit."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: True)
    assert rollup_serve._spill_setting() == ""
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    folder = rollup_serve._spill_setting()
    assert folder and str(tmp_path) in folder
    rollup_serve._remove_spill(folder)
