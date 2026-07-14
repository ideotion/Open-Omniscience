"""
The V1 KPI snapshot (R1, V1_PATHWAY §2.3) — honesty invariants + wiring.

Pins: all 14 K-metrics present, a declared direction on every metric (R2 needs it), verdicts in
domain with not-measurable-here used honestly (never a fabricated pass), NO composite score key,
the run_kpi_selftest gate is registered in the recursive loop, and the endpoint + bundle member
are wired.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from src.monitoring.kpi import kpi_snapshot, run_kpi_selftest


def _walk_no_score(o) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade")), k
            _walk_no_score(v)
    elif isinstance(o, list):
        for v in o:
            _walk_no_score(v)


def test_snapshot_has_all_14_metrics_with_directions_and_verdicts():
    snap = kpi_snapshot()
    assert snap["schema"] == "oo-kpi-1"
    metrics = snap["metrics"]
    assert [m["id"] for m in metrics] == [f"K{i}" for i in range(1, 15)]
    for m in metrics:
        assert m["direction"] in ("up", "down", "exact")  # ALWAYS present (R2)
        assert m["verdict"] in ("green", "red", "not-measurable-here")
        assert m["target"]  # never blank
        assert set(m) >= {"id", "name", "value", "method", "n", "as_of", "source_endpoint",
                          "direction", "target", "verdict"}


def test_not_measurable_metrics_carry_no_fabricated_value():
    for m in kpi_snapshot()["metrics"]:
        if m["verdict"] == "not-measurable-here":
            assert m["value"] is None and m["as_of"] is None
            assert m["method"]  # an honest reason, never silent


def test_i18n_metric_is_measurable_in_process():
    # K11 reads the locale files cheaply in-process — it is the one metric that is a real
    # verdict on a dev checkout (the repo ships --min 100).
    k11 = next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K11")
    assert k11["verdict"] in ("green", "red") and k11["value"] is not None


def test_no_composite_score_anywhere():
    _walk_no_score(kpi_snapshot())


def test_selftest_passes_and_is_registered():
    assert run_kpi_selftest()["passed"] is True
    from src.monitoring.recursive_loop import LOOP_SELFTESTS

    assert any(fn == "run_kpi_selftest" for _n, _m, fn in LOOP_SELFTESTS)


def test_endpoint_and_bundle_membership_are_wired():
    src = Path("src/api/diagnostics.py").read_text(encoding="utf-8")
    assert '@router.get("/kpi")' in src and "def kpi(" in src
    start = src.index("def _all_diagnostics_members")
    end = src.index("def _all_diagnostics_manifest", start)
    assert '"kpi.json"' in src[start:end], "kpi.json dropped from the all-diagnostics aggregator"
