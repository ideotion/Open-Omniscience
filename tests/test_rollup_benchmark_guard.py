"""R278 (audit 0.5.0, #1310 class): the rollup benchmark meets the start-time guards the served build meets.

Before: ``GET /api/diagnostics/rollup-benchmark`` built the whole-corpus keyword rollup in memory, the build that crashed the app in #1310, with
no verdict and no hold: it ran while a stop hold said the machine cannot afford it, while memory was short and beside a served build.
After: ``run_rollup_benchmark`` asks the same verdicts (judged as the in-memory build it is), holds the build lock, and DECLINES with the verdict's
reason code and builds nothing. (The cross-site guard on the GET route itself is a separate item.)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("duckdb")

from src.analytics import columnar, rollup_serve  # noqa: E402
from src.monitoring.rollup_benchmark import run_rollup_benchmark  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    keys = ("con", "stopped", "failures", "failure_class", "last_outcome", "last_decline", "last_skip", "persisted", "built_at", "bind")
    keep = {k: rollup_serve._STATE.get(k) for k in keys}
    rollup_serve._STATE.update(con=None, stopped=None, failures=0, failure_class=None, last_outcome=None, last_decline=None,
                               last_skip=None, persisted=False, built_at=0.0, bind=None)
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", True)
    for name in ("_boot_order_verdict", "_memory_verdict", "_last_build_verdict", "_affordability_verdict"):
        monkeypatch.setattr(rollup_serve, name, lambda: None)
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)

    def never(*a, **k):
        raise AssertionError("the benchmark built something past a verdict that refuses it")

    monkeypatch.setattr(columnar, "connect", never)
    monkeypatch.setattr(columnar, "build_keyword_daily", never)
    yield
    rollup_serve._STATE.update(keep)


def test_a_seeded_in_memory_stop_hold_makes_the_benchmark_decline_and_build_nothing(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_stopped_build_verdict", rollup_serve._stopped_build_verdict)  # the real one
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 500.0)
    rollup_serve._STATE["stopped"] = {"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": 500.0, "epoch": 1}
    out = run_rollup_benchmark(session=None, repeats=1)  # type: ignore[arg-type]  # a declined run never touches the session
    assert out["available"] is False and out["declined"] is True
    assert out["reason"] == "duckdb-limit" and out["source"] == "stopped"
    assert rollup_serve._STATE["last_skip"] is None, "a benchmark's refusal is not the serve's decline"


@pytest.mark.parametrize("verdict,source", [("_affordability_verdict", "affordability"), ("_last_build_verdict", "last-build"),
                                            ("_memory_verdict", "memory"), ("_boot_order_verdict", "boot-order")])
def test_each_start_time_verdict_declines_the_benchmark_with_its_own_reason(monkeypatch, verdict, source):
    monkeypatch.setattr(rollup_serve, verdict, lambda: {"reason": "mem-short", "at": 1.0})
    out = run_rollup_benchmark(session=None, repeats=1)  # type: ignore[arg-type]
    assert (out["declined"], out["reason"], out["source"]) == (True, "mem-short", source)


def test_the_exclusive_window_declines_the_benchmark(monkeypatch):
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: {"reason": "exclusive-window", "at": 1.0})
    out = run_rollup_benchmark(session=None, repeats=1)  # type: ignore[arg-type]
    assert out["declined"] is True and out["source"] == "exclusive"


def test_a_running_rollup_build_makes_the_benchmark_decline(monkeypatch):
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    try:
        out = run_rollup_benchmark(session=None, repeats=1)  # type: ignore[arg-type]
        assert out["declined"] is True and out["reason"] == "build-running"
    finally:
        rollup_serve._BUILD_LOCK.release()


def test_the_benchmark_releases_the_build_lock_after_a_decline_and_after_an_error(monkeypatch):
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: {"reason": "mem-low", "at": 1.0})
    assert run_rollup_benchmark(session=None, repeats=1)["declined"] is True  # type: ignore[arg-type]
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False), "a decline left the build lock held"
    rollup_serve._BUILD_LOCK.release()
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    with pytest.raises(AttributeError):  # session None: the run gets past the verdicts and fails on its first query
        run_rollup_benchmark(session=None, repeats=1)  # type: ignore[arg-type]
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False), "an error left the build lock held"
    rollup_serve._BUILD_LOCK.release()


def test_the_benchmark_judges_the_in_memory_build_even_when_the_persisted_store_is_active(monkeypatch):
    """The affordability and killed-build verdicts stand aside for a persisted store; the benchmark always builds in memory, so it must not."""
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", rollup_serve._persisted_serve_active)  # the real one, which reads the setting
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    assert rollup_serve._persisted_serve_active() is True
    seen: list = []

    def afford():
        seen.append(rollup_serve._persisted_serve_active())
        return {"reason": "mem-short", "at": 1.0}

    monkeypatch.setattr(rollup_serve, "_affordability_verdict", afford)
    out = run_rollup_benchmark(session=None, repeats=1)  # type: ignore[arg-type]
    assert out["declined"] is True and seen == [False], "the verdict was asked about the persisted store"
    assert rollup_serve._persisted_serve_active() is True, "the view leaked past the benchmark"
