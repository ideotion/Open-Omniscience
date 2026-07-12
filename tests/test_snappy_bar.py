"""
S2.7 — the snappy-bar verdict: the latency reservoir renders each interactive route's
measured p95 as an explicit pass/fail against the written ~500 ms bar, so a field export
SHOWS pass/fail instead of anecdotes. Measurements only — no fabricated numbers.
"""

from __future__ import annotations

import pytest

from src.monitoring import latency


@pytest.fixture(autouse=True)
def _reset():
    latency._reset_for_tests()
    yield
    latency._reset_for_tests()


def _record(route: str, ms: float, n: int, status: int = 200) -> None:
    for i in range(n):
        latency.record(i, route, status, ms)


def test_fast_interactive_route_passes_and_slow_one_fails():
    _record("GET /api/insights/top", 40.0, 30)          # fast, enough samples -> pass
    _record("GET /api/articles", 900.0, 30)             # slow -> fail
    s = latency.summary()
    by_route = {r["route"]: r for r in s["routes"]}
    assert by_route["GET /api/insights/top"]["snappy"] == "pass"
    assert by_route["GET /api/articles"]["snappy"] == "fail"

    bar = s["snappy_bar"]
    assert bar["bar_ms"] == 500.0
    assert bar["passing"] == 1
    assert bar["failing"] == 1
    assert bar["all_interactive_pass"] is False
    failing = {f["route"] for f in bar["failing_routes"]}
    assert "GET /api/articles" in failing
    assert "GET /api/insights/top" not in failing


def test_thin_window_is_low_n_not_a_fabricated_pass_or_fail():
    _record("GET /api/insights/latest", 20.0, 3)  # only 3 samples (< _SNAPPY_MIN_N)
    s = latency.summary()
    by_route = {r["route"]: r for r in s["routes"]}
    assert by_route["GET /api/insights/latest"]["snappy"] == "low-n"
    assert s["snappy_bar"]["low_n"] == 1
    assert s["snappy_bar"]["passing"] == 0
    assert s["snappy_bar"]["failing"] == 0


def test_heavy_on_demand_routes_are_exempt_never_a_fail():
    # A deliberately slow diagnostics export is NOT held to the interactive bar.
    _record("GET /api/diagnostics/keywords", 120000.0, 30)
    _record("POST /api/backup/v2/volumes/start", 90000.0, 30)
    s = latency.summary()
    by_route = {r["route"]: r for r in s["routes"]}
    assert by_route["GET /api/diagnostics/keywords"]["snappy"] == "exempt"
    assert by_route["POST /api/backup/v2/volumes/start"]["snappy"] == "exempt"
    bar = s["snappy_bar"]
    assert bar["failing"] == 0  # exempt routes never count as a fail
    assert bar["interactive_routes"] == 0  # both were exempt


def test_all_interactive_pass_is_true_only_when_there_are_passing_interactive_routes():
    _record("GET /api/insights/trending-windows", 100.0, 25)
    bar = latency.summary()["snappy_bar"]
    assert bar["all_interactive_pass"] is True
    assert bar["failing"] == 0 and bar["passing"] == 1
