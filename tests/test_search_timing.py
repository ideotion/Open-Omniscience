"""
Per-search intra-request timing instrument (planning §4 — search instrumentation FIRST).

Proves the mechanism the operator's live decision rests on: the per-phase wall-clock timer, the
percentile aggregate, and — non-vacuously — that the DOMINANT phase is the one with the highest
MEASURED p95, never the first-recorded phase. Plus the aggregator MEMBERSHIP contract (the §4
report is in the all-diagnostics bundle) and the honesty guards (no score, degrade on empty).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from src.monitoring.search_timing import (
    _RES_CAP,
    SCHEMA,
    SearchPhaseTimer,
    _FakeClock,
    _reset_for_tests,
    _snapshot,
    aggregate_phases,
    record_search_phases,
    run_search_timing_selftest,
    search_timing_report,
)


def _record(ticks: list[float], names: list[str]) -> dict:
    t = SearchPhaseTimer(monotonic=_FakeClock(ticks))
    for n in names:
        t.phase(n)
    return t.finish()


def test_phase_ms_and_total_are_exact_off_an_injected_clock():
    rec = _record([0.0, 0.010, 0.055, 0.058, 0.060], ["fts_match", "content_fetch", "serialize"])
    ms = {p["phase"]: p["ms"] for p in rec["phases"]}
    assert ms == {"fts_match": 10.0, "content_fetch": 45.0, "serialize": 3.0}
    # Total is the FULL wall (60), so the 2 ms of unmarked time between serialize and finish is
    # visible as total minus the phase sum (58) — the timer never hides where wall-clock goes.
    assert rec["total_ms"] == 60.0
    assert rec["total_ms"] > sum(p["ms"] for p in rec["phases"])


def test_dominant_phase_is_measured_p95_not_insertion_order():
    # fts_match is recorded FIRST but content_fetch is the wall-clock hog in both searches.
    a = _record([0.0, 0.010, 0.055, 0.058, 0.060], ["fts_match", "content_fetch", "serialize"])
    b = _record([0.0, 0.012, 0.052, 0.056, 0.058], ["fts_match", "content_fetch", "serialize"])
    agg = aggregate_phases([a, b])
    assert agg["dominant_phase"] == "content_fetch"
    assert agg["phases"]["content_fetch"]["n"] == 2
    assert set(agg["phases"]["content_fetch"]) >= {"p50_ms", "p95_ms", "p99_ms", "max_ms", "mean_ms"}


def test_dominant_phase_tracks_the_data():
    # A different split → a different dominant phase. The answer is derived, not hard-coded.
    c = _record([0.0, 0.002, 0.006, 0.106, 0.107], ["fts_match", "content_fetch", "serialize"])
    assert aggregate_phases([c])["dominant_phase"] == "serialize"


def test_empty_aggregate_is_honest():
    empty = aggregate_phases([])
    assert empty["schema"] == SCHEMA
    assert empty["phases"] == {}
    assert empty["dominant_phase"] is None
    assert empty["searches"] == 0
    assert empty["total"]["max_ms"] == 0.0


def test_malformed_phase_entries_are_skipped_not_crashed():
    # A record with a non-numeric ms and a missing total must not blow up the aggregate.
    bad = {"phases": [{"phase": "x", "ms": "oops"}, {"phase": "y", "ms": 5.0}]}
    agg = aggregate_phases([bad])
    assert "y" in agg["phases"] and "x" not in agg["phases"]
    assert agg["total"]["n"] == 0  # no total_ms present → counted as zero totals


def test_record_window_is_bounded():
    _reset_for_tests()
    for _ in range(_RES_CAP + 25):
        record_search_phases({"phases": [{"phase": "x", "ms": 1.0}], "total_ms": 1.0})
    assert len(_snapshot()) <= _RES_CAP
    # The live report reflects what was recorded.
    assert search_timing_report()["phases"]["x"]["n"] <= _RES_CAP
    _reset_for_tests()
    assert search_timing_report()["phases"] == {}


def test_selftest_all_green_and_non_vacuous():
    log = run_search_timing_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]
    names = {c["check"] for c in log["checks"]}
    # The load-bearing, easy-to-fake checks must be present (a green run is never vacuous).
    assert {"dominant_is_measured_not_first", "dominant_tracks_the_data", "empty_is_honest"} <= names


def test_no_score_field_anywhere():
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    a = _record([0.0, 0.01, 0.02, 0.03, 0.04], ["fts_match", "content_fetch", "serialize"])
    walk(aggregate_phases([a]))
    walk(run_search_timing_selftest())


def test_aggregator_carries_the_search_timing_report():
    # MEMBERSHIP CONTRACT (source-inspected, no app import): _all_diagnostics_members must carry
    # the §4 report so a future edit can never silently drop it from the bundle.
    src = Path("src/api/diagnostics.py").read_text(encoding="utf-8")
    start = src.index("def _all_diagnostics_members")
    end = src.index("def _all_diagnostics_manifest", start)
    assert '"search-timing.json"' in src[start:end], "search-timing.json dropped from the bundle"
