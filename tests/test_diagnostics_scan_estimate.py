"""A Thorough build's expected time is this machine's own, not a table's (R459, finding F9 of the 2026-11-07 Windows run).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Windows run's thorough build took 53 minutes against a field table that put the same scans at 44 at most: card-audit expected 60.5 s
took 302 s. The estimate here is read from this machine's earlier scan times scaled by the mention rows; ``est_s`` in the plan still only
ORDERS the scans.
"""

from __future__ import annotations

import json

from src.api import diagnostics_plan as plan
from src.api.diagnostics import scan_estimate


def test_with_no_history_the_estimate_is_the_field_medians_and_says_so():
    e = plan.thorough_estimate(None, 25_000_000)
    assert e["from_this_machine"] == 0 and e["from_field_medians"] == e["scans"] == len(plan.SCAN_EST_S)
    assert e["est_s"] == round(sum(min(300.0, v) for v in plan.SCAN_EST_S.values()))


def test_a_scan_timed_here_is_scaled_by_the_mention_rows_and_capped_at_its_deadline():
    hist = {
        "card-audit.json": {"wall_s": 100.0, "rows": 10_000_000, "at": "2026-11-07T00:00:00+00:00"},
        "keyword-engine.json": {"wall_s": 250.0, "rows": 10_000_000, "at": "2026-11-07T00:00:00+00:00"},
    }
    e = plan.thorough_estimate(hist, 20_000_000)
    base = plan.thorough_estimate(None, 20_000_000)["est_s"]
    # card-audit 60.5 (table) -> 200 (100 x 2); keyword-engine 231 (table) -> 300 (500 capped at the deadline)
    assert e["est_s"] == round(base - 60.5 - 231.0 + 200.0 + 300.0)
    assert e["from_this_machine"] == 2


def test_without_a_row_reading_nothing_is_scaled():
    hist = {"card-audit.json": {"wall_s": 100.0, "rows": 10, "at": "x"}}
    assert plan.thorough_estimate(hist, None)["from_this_machine"] == 0
    assert plan.thorough_estimate(hist, 0)["from_this_machine"] == 0


def test_a_damaged_history_is_ignored_not_trusted():
    for bad in ("text", ["a"], {"card-audit.json": "x"}, {"card-audit.json": {"wall_s": "slow", "rows": 5}}, {"card-audit.json": {"wall_s": 5, "rows": 0}}):
        assert plan.thorough_estimate(bad, 100)["from_this_machine"] == 0


def test_the_machine_table_is_what_a_build_orders_by_and_names_each_figure_s_source():
    hist = {"card-audit.json": {"wall_s": 290.0, "rows": 20_000_000, "at": "x"}, "benchmark.json": {"wall_s": True, "rows": 5}}
    costs, basis = plan.machine_table(hist, 20_000_000)
    assert costs["card-audit.json"] == 290.0 and basis["card-audit.json"] == "this-machine"
    assert costs["benchmark.json"] == 300.0 and basis["benchmark.json"] == "field-median", "a bool is not a time"
    assert set(costs) == set(basis) == set(plan.SCAN_EST_S)
    records, scans = plan.split_members([(n, None) for n in plan.SCAN_EST_S], costs)
    order = [n for n, _ in scans]
    assert order.index("card-audit.json") > order.index("keyword-engine.json"), "290 s here runs after the 231 s scans, not fourth"
    assert plan.thorough_estimate(hist, 20_000_000)["est_s"] == round(sum(costs.values()))


def test_a_cheap_run_here_never_orders_a_scan_before_its_field_median():
    """leads-quality takes 0.01 s from a fresh Home feed and up to 240 s without one: ordered first on the cheap run, it would spend
    the budget the way the card audit did (row 74). The Thorough estimate, a sum rather than an order, still uses the figure here."""
    hist = {"leads-quality.json": {"wall_s": 0.0, "rows": 1_000, "at": "x"}}
    costs, basis = plan.machine_table(hist, 1_000)
    assert costs["leads-quality.json"] == 275.0 and basis["leads-quality.json"] == "field-median"
    raw, raw_basis = plan.machine_table(hist, 1_000, at_least_median=False)
    assert raw["leads-quality.json"] == 0.0 and raw_basis["leads-quality.json"] == "this-machine"
    assert plan.thorough_estimate(hist, 1_000)["from_this_machine"] == 1


def test_a_stored_figure_too_large_for_a_float_is_no_figure_and_never_fails_the_build():
    for h in ({"wall_s": 10**400, "rows": 5}, {"wall_s": 5.0, "rows": 10**400}, {"wall_s": float("nan"), "rows": 5}):
        costs, basis = plan.machine_table({"card-audit.json": h}, 100)
        assert costs["card-audit.json"] == 60.5 and basis["card-audit.json"] == "field-median"


def test_a_scan_that_finished_under_a_deadline_the_budget_shortened_is_remembered():
    """Otherwise a scan Quick runs late (after 300 s of its budget) could never be timed lower than its last figure."""
    got = plan.walls_to_remember([{"file": "card-audit.json", "outcome": "ok", "wall_s": 40.0, "budget_cut": True}], 1_000, "x")
    assert got == {"card-audit.json": {"wall_s": 40.0, "rows": 1_000, "at": "x"}}


def test_scan_table_falls_back_to_the_field_medians_when_the_store_cannot_be_read(monkeypatch):
    import src.config.kv_store as kv

    def boom(_key):
        raise RuntimeError("locked")

    monkeypatch.setattr(kv, "kv_get_json", boom)
    costs, basis = scan_estimate.scan_table()
    assert costs == {k: min(300.0, v) for k, v in plan.SCAN_EST_S.items()} and set(basis.values()) == {"field-median"}


def test_est_s_still_only_orders_the_scans():
    assert plan.scan_est_s("card-audit.json") == 60.5, "the plan's own table is untouched"


def test_a_build_remembers_the_scans_that_did_their_own_work_only():
    results = [
        {"file": "card-audit.json", "outcome": "ok", "wall_s": 302.0},
        {"file": "benchmark.json", "outcome": "partial-deadline", "wall_s": 300.0},
        {"file": "source-audit.json", "outcome": "partial-deadline", "wall_s": 41.0, "budget_cut": True},
        {"file": "lemma-preview.json", "outcome": "skipped-budget", "wall_s": 0.0},
        {"file": "kpi.json", "outcome": "ok", "wall_s": 1.0},  # a record, not a scan
    ]
    got = plan.walls_to_remember(results, 25_000_000, "2026-11-07T12:00:00+00:00")
    assert set(got) == {"card-audit.json", "benchmark.json"}
    assert got["card-audit.json"] == {"wall_s": 302.0, "rows": 25_000_000, "at": "2026-11-07T12:00:00+00:00"}
    assert plan.walls_to_remember(results, None, "x") == {} and plan.walls_to_remember(results, 0, "x") == {}


def test_remembering_merges_with_what_was_kept_and_never_raises(monkeypatch):
    kept = {"card-audit.json": {"wall_s": 10.0, "rows": 5, "at": "old"}, "benchmark.json": {"wall_s": 9.0, "rows": 5, "at": "old"}}
    saved: dict = {}
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda _k: kept)
    monkeypatch.setattr("src.config.kv_store.kv_set_json", lambda k, v: saved.update({k: v}))
    monkeypatch.setattr(scan_estimate, "_mention_rows", lambda: 1000)
    scan_estimate._remember_scan_walls([{"file": "card-audit.json", "outcome": "ok", "wall_s": 3.0}])
    got = saved[plan.SCAN_WALLS_KEY]
    assert got["card-audit.json"]["wall_s"] == 3.0 and got["benchmark.json"]["wall_s"] == 9.0, "a build that ran one scan keeps the others' times"

    def boom(*_a, **_k):
        raise RuntimeError("locked")

    monkeypatch.setattr("src.config.kv_store.kv_set_json", boom)
    scan_estimate._remember_scan_walls([{"file": "card-audit.json", "outcome": "ok", "wall_s": 3.0}])  # must not raise


def test_the_route_reports_the_estimate_and_what_it_was_scaled_by(monkeypatch):
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda _k: {"card-audit.json": {"wall_s": 100.0, "rows": 1000, "at": "x"}})
    monkeypatch.setattr(scan_estimate, "_mention_rows", lambda: 2000)
    body = json.loads(scan_estimate.all_diagnostics_estimate().body)
    assert body["mention_rows"] == 2000 and body["quick"]["budget_s"] == plan.SCAN_BUDGET_S
    assert body["thorough"]["from_this_machine"] == 1 and body["thorough"]["pauses_collection"] is True


def test_the_route_answers_when_the_store_cannot_be_read(monkeypatch):
    def boom(_k):
        raise RuntimeError("locked")

    monkeypatch.setattr("src.config.kv_store.kv_get_json", boom)
    monkeypatch.setattr(scan_estimate, "_mention_rows", lambda: None)
    body = json.loads(scan_estimate.all_diagnostics_estimate().body)
    assert body["thorough"]["from_this_machine"] == 0 and body["mention_rows"] is None


def test_the_job_remembers_after_the_window_not_inside_it():
    import inspect

    from src.api.diagnostics import bundle

    src = inspect.getsource(bundle._all_diagnostics_build)
    assert src.index("_os.replace(part_path, final_path)") < src.index("_remember_scan_walls(results)")


def test_the_panel_states_the_thorough_cost_before_it_is_chosen():
    """The Thorough note exists in the page, is hidden until needed, and is
    painted from the estimate route (source-level: no browser here)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app-diagnostics.js").read_text(encoding="utf-8")
    assert 'id="diag-thorough-note"' in html
    assert "/api/diagnostics/all-job/estimate" in js
    assert "paintThoroughNote" in js
    assert "addEventListener(\"change\"" in js
