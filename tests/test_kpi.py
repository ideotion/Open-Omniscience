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


def test_k2_resolver_reads_the_nested_snappy_bar_shape(monkeypatch):
    """S5 item 2 (field-feedback 2026-07-23): latency.summary()["snappy_bar"] is a
    DICT ({"bar_ms": ..., "interactive_routes": ..., ...}), not a plain float — a
    real resolver bug (float(dict) -> TypeError) was silently degrading K2 to
    "not-measurable-here" behind the honest resolver-error fallback on every real
    call. Pin the fix by feeding the resolver the EXACT real shape and asserting a
    genuine numeric value + verdict come back, not a swallowed exception."""
    import src.monitoring.latency as latency

    def _fake_summary():
        return {
            "snappy_bar": {"bar_ms": 500.0, "interactive_routes": 1, "passing": 1, "failing": 0},
            "routes": [
                {"route": "/api/articles", "p95_ms": 123.4, "window_n": 25, "snappy": "pass"},
            ],
        }

    monkeypatch.setattr(latency, "summary", _fake_summary)
    k2 = next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K2")
    assert k2["verdict"] == "green"
    assert k2["value"] == 123.4
    assert "not-measurable" not in k2["method"] and "resolver error" not in k2["method"]


def test_k2_resolver_never_raises_on_the_live_shape():
    """Negative-space companion: the REAL (unmocked) latency.summary() call must
    round-trip through the resolver without ever hitting the try/except fallback —
    proving the fix works against the actual module, not just a hand-shaped fixture."""
    k2 = next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K2")
    assert "resolver error" not in k2["method"]


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
