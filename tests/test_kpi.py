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
        # "measured-no-bar" joined the domain 2026-09-07 with K6's persisted resolver:
        # a figure that IS known whose numeric bar is still a ruling. Widening this
        # guard is deliberate, and it is paid for by
        # test_measured_no_bar_can_never_be_used_to_withhold_a_red below.
        assert m["verdict"] in ("green", "red", "measured-no-bar", "not-measurable-here")
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


def test_k2_selects_over_the_routes_a_human_waits_on(monkeypatch):
    """The field shape, 2026-08-02: K2 published GREEN at 31.2 ms — the worst of three
    2-second pollers — while GET /api/articles sat at a measured p95 of 68,137 ms in the
    SAME reservoir, excluded because its window was thin.

    Restricting the selection to pass|fail could never see an interactive route, because
    a thin window IS the signature of one: the UI polls, a person clicks. So the value
    must come from every measured interactive route, carrying its own n."""
    import src.monitoring.latency as latency

    def _fake_summary():
        return {
            "snappy_bar": {"bar_ms": 500.0, "interactive_routes": 4, "passing": 3,
                           "failing": 0, "breaching": 1, "all_interactive_pass": False},
            "routes": [
                {"route": "GET /api/system/network", "p95_ms": 30.4,
                 "window_n": 275, "snappy": "pass"},
                {"route": "GET /api/system/egress-window", "p95_ms": 29.3,
                 "window_n": 512, "snappy": "pass"},
                {"route": "GET /api/scheduler/status", "p95_ms": 28.5,
                 "window_n": 274, "snappy": "pass"},
                {"route": "GET /api/articles", "p95_ms": 68137.5,
                 "window_n": 2, "snappy": "low-n"},
                # exempt stays out: the bar genuinely does not cover heavy exports
                {"route": "GET /api/diagnostics/keywords", "p95_ms": 900000.0,
                 "window_n": 3, "snappy": "exempt"},
            ],
        }

    monkeypatch.setattr(latency, "summary", _fake_summary)
    k2 = next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K2")
    assert k2["value"] == 68137.5, "the worst MEASURED interactive route, not the worst poller"
    assert k2["verdict"] == "red"
    assert k2["n"] == 2, "the worst route's OWN n, never a sum that hides how thin it is"
    assert "/api/articles" in k2["method"]
    assert "thin window" in k2["method"], "the uncertainty is disclosed, not the reason to drop it"
    assert "900000" not in str(k2["value"]), "an exempt route never sets the value"


def test_k2_stays_green_when_only_fast_routes_were_measured(monkeypatch):
    """Negative-space twin: widening the selection must not make a thin-but-fast route
    read as a breach. A fabricated red is exactly as dishonest as the fabricated green."""
    import src.monitoring.latency as latency

    monkeypatch.setattr(latency, "summary", lambda: {
        "snappy_bar": {"bar_ms": 500.0},
        "routes": [
            {"route": "GET /api/insights/top", "p95_ms": 40.0, "window_n": 30, "snappy": "pass"},
            {"route": "GET /api/articles", "p95_ms": 120.0, "window_n": 2, "snappy": "low-n"},
        ],
    })
    k2 = next(m for m in kpi_snapshot()["metrics"] if m["id"] == "K2")
    assert k2["verdict"] == "green"
    assert k2["value"] == 120.0


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


# --------------------------------------------------------------------------- #
#  K6 — cross-language translation coverage from a PERSISTED measurement
#  (the 2026-07-20 ring-lifecycle ruling; wired 2026-09-07)
# --------------------------------------------------------------------------- #

def _isolate_coverage(monkeypatch, tmp_path):
    """Point the coverage record at tmp_path — the suite shares one OO_DATA_DIR, so a
    record written here would otherwise change K6 for every later test in the session."""
    from src.monitoring import kpi as kpi_mod

    monkeypatch.setattr(kpi_mod, "_coverage_path", lambda: tmp_path / "keyword-coverage.json")
    return kpi_mod


def _k6(snap) -> dict:
    return next(m for m in snap["metrics"] if m["id"] == "K6")


def test_k6_reports_the_recorded_coverage_with_the_date_it_was_measured(monkeypatch, tmp_path):
    """The as_of must be the MEASUREMENT's, not the snapshot's: re-stamping a months-old
    figure as fresh turns a record of the past into a claim about today, and two cycle
    snapshots would then look like two agreeing measurements.

    The record is deliberately AGED — recording and reading inside one second makes
    `_now()` and `measured_at` the same string, so a same-second fixture cannot tell a
    correct resolver from one that re-stamps."""
    import json as _json
    from datetime import UTC, datetime, timedelta

    kpi_mod = _isolate_coverage(monkeypatch, tmp_path)
    kpi_mod.record_translation_coverage(
        {"translation_coverage": {"top_n": 500, "in_a_ring": 61, "pct": 12.2, "rings_total": 684}}
    )
    path = tmp_path / "keyword-coverage.json"
    rec = _json.loads(path.read_text(encoding="utf-8"))
    then = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    rec["measured_at"] = then
    path.write_text(_json.dumps(rec), encoding="utf-8")

    m = _k6(kpi_snapshot())
    assert m["value"] == 12.2 and m["n"] == 500
    assert m["as_of"] == then  # the MEASUREMENT time, never re-stamped as now
    assert m["verdict"] == "measured-no-bar"  # a real figure; the bar is still a ruling
    assert "684" in m["method"]
    assert "30.0 day(s) ago" in m["method"]  # the age is stated, not left to be inferred


def test_k6_is_not_measurable_until_a_run_records_one(monkeypatch, tmp_path):
    _isolate_coverage(monkeypatch, tmp_path)
    m = _k6(kpi_snapshot())
    assert m["verdict"] == "not-measurable-here"
    assert m["value"] is None and m["as_of"] is None
    assert "no run has recorded one yet" in m["method"]  # says what would fix it


def test_k6_never_turns_an_empty_corpus_into_a_coverage_of_zero(monkeypatch, tmp_path):
    """NEGATIVE SPACE. engine_report's _pct returns None when there are no top terms to
    divide by. "we looked at the keywords and none are ring-covered" and "there were no
    keywords" are opposite findings; a stored 0.0 would assert the first."""
    kpi_mod = _isolate_coverage(monkeypatch, tmp_path)
    rec = kpi_mod.record_translation_coverage(
        {"translation_coverage": {"top_n": 0, "in_a_ring": 0, "pct": None, "rings_total": 684}}
    )
    assert rec["pct"] is None  # stored as the gap it is
    m = _k6(kpi_snapshot())
    assert m["value"] is None and m["verdict"] == "not-measurable-here"
    assert "different fact from a coverage of 0" in m["method"]


def test_recording_ignores_a_report_without_a_coverage_block(monkeypatch, tmp_path):
    kpi_mod = _isolate_coverage(monkeypatch, tmp_path)
    assert kpi_mod.record_translation_coverage({}) is None
    assert kpi_mod.record_translation_coverage({"translation_coverage": "not a dict"}) is None
    assert kpi_mod.read_translation_coverage() is None  # nothing written


def test_a_failed_record_leaves_k6_saying_nothing_was_recorded(monkeypatch, tmp_path):
    """A diagnostic side-record must never break the diagnostic, and its failure must not
    invent a value either — K6 simply reports that no run recorded one."""
    kpi_mod = _isolate_coverage(monkeypatch, tmp_path)
    monkeypatch.setattr(kpi_mod, "_coverage_path", lambda: (_ for _ in ()).throw(OSError("nope")))
    assert kpi_mod.record_translation_coverage(
        {"translation_coverage": {"top_n": 5, "in_a_ring": 1, "pct": 20.0, "rings_total": 2}}
    ) is None
    assert _k6(kpi_snapshot())["verdict"] == "not-measurable-here"


def test_a_corrupt_or_foreign_coverage_file_is_not_read_as_a_measurement(monkeypatch, tmp_path):
    kpi_mod = _isolate_coverage(monkeypatch, tmp_path)
    f = tmp_path / "keyword-coverage.json"
    f.write_text("{not json", encoding="utf-8")
    assert kpi_mod.read_translation_coverage() is None
    f.write_text('{"schema": "something-else", "pct": 99.9}', encoding="utf-8")
    assert kpi_mod.read_translation_coverage() is None
    assert _k6(kpi_snapshot())["value"] is None  # never 99.9


def _check_named(selftest: dict, name: str) -> dict:
    return next(c for c in selftest["checks"] if c["name"] == name)


def test_measured_no_bar_can_never_be_used_to_withhold_a_red(monkeypatch, tmp_path):
    """The twin that pays for widening the verdict domain: the new verdict is only legal
    for a metric that carries its figure AND whose bar is genuinely an open ruling.

    "No metric misuses it" is satisfied for free when no metric uses it at all, so this
    creates the condition first and asserts the selftest check actually SAW a
    measured-no-bar metric — then feeds it a dishonest one and requires it to fail."""
    kpi_mod = _isolate_coverage(monkeypatch, tmp_path)
    kpi_mod.record_translation_coverage(
        {"translation_coverage": {"top_n": 500, "in_a_ring": 61, "pct": 12.2, "rings_total": 684}}
    )
    nb = [m for m in kpi_snapshot()["metrics"] if m["verdict"] == "measured-no-bar"]
    assert nb, "the fixture must actually produce the verdict this guard is about"
    for m in nb:
        assert m["value"] is not None
        assert "pending-ruling" in str(m["target"])

    st = run_kpi_selftest()
    assert st["passed"]
    check = _check_named(st, "measured_no_bar_is_honest")
    assert check["passed"] and check["detail"].startswith(f"{len(nb)} ")  # it saw them
    _check_named(st, "verdict_in_domain")  # still in the domain list

    # ... and it DISCRIMINATES in BOTH directions the verdict could be abused.
    def _no_figure(spec):
        # claims to have measured, carries nothing
        return {**spec, "value": None, "verdict": "measured-no-bar",
                "method": "", "n": None, "as_of": None, "target": spec["target"]}

    def _dodging_a_bar(spec):
        # the dangerous one: a real figure against a REAL bar, parked under "no bar"
        # instead of being judged green or red
        return {**spec, "value": 12.2, "verdict": "measured-no-bar",
                "method": "", "n": 1, "as_of": None, "target": "< 500 ms"}

    for injector in (_no_figure, _dodging_a_bar):
        monkeypatch.setitem(kpi_mod._RESOLVERS, "K6", injector)
        bad = run_kpi_selftest()
        assert not bad["passed"], injector.__name__
        assert not _check_named(bad, "measured_no_bar_is_honest")["passed"], injector.__name__


def test_the_keyword_engine_endpoint_records_what_it_measured(monkeypatch, tmp_path):
    """The measurement is written down where it is MADE — this drives the real endpoint,
    not a source grep, because the defect being closed was that the report was computed,
    streamed and forgotten. The scan itself is stubbed at its seam; the wiring is real."""
    import src.analytics.engine_report as er
    from src.api.diagnostics import keyword_engine

    kpi_mod = _isolate_coverage(monkeypatch, tmp_path)
    canned = {"translation_coverage": {"top_n": 300, "in_a_ring": 27, "pct": 9.0,
                                       "rings_total": 684}}
    monkeypatch.setattr(er, "keyword_engine_report", lambda db: canned)

    resp = keyword_engine(download=False, db=object())
    assert resp.status_code == 200

    rec = kpi_mod.read_translation_coverage()
    assert rec is not None and rec["pct"] == 9.0 and rec["in_a_ring"] == 27
    assert _k6(kpi_snapshot())["value"] == 9.0
