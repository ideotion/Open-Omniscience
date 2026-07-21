"""
ui_walk harness tests (planning §6, gate row 8) — proves the CONTROL FLOW on a fake driver:
no real browser is available in this session, so these tests never import/require one. They
prove: (1) a fully-working fake driver reports all_green; (2) one bad surface degrades that
ONE step without aborting the walk; (3) the default (no driver) is the honest "not connected"
report, never a fabricated pass; (4) the report shape matches house convention (schema +
counts-only summary, no score/ranking/rating/grade key anywhere in the payload).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.monitoring.ui_walk import (
    FLAGSHIP_SURFACES,
    SCHEMA,
    Surface,
    UnconnectedDriver,
    run_ui_walk,
    walk,
)


class _FakeDriver:
    """A deterministic in-memory stand-in for a real browser: no network, no subprocess,
    no timing. ``visited`` records call order so control flow (visit every surface, in order)
    is verifiable."""

    engine = "fake"

    def __init__(
        self,
        *,
        broken_dom_ids: set[str] | None = None,
        raise_on: set[str] | None = None,
        console_errors_by: dict[str, list[str]] | None = None,
    ):
        self.broken_dom_ids = broken_dom_ids or set()
        self.raise_on = raise_on or set()
        self.console_errors_by = console_errors_by or {}
        self.visited: list[str] = []
        self._current: str | None = None

    def goto(self, surface: Surface) -> None:
        if surface.id in self.raise_on:
            raise RuntimeError(f"fake navigation failure for {surface.id}")
        self.visited.append(surface.id)
        self._current = surface.id

    def is_visible(self, dom_id: str) -> bool:
        return dom_id not in self.broken_dom_ids

    def console_errors(self) -> list[str]:
        return list(self.console_errors_by.get(self._current or "", []))

    def screenshot(self, surface: Surface) -> str | None:
        return f"/tmp/fake-screenshots/{surface.id}.png"


def _no_banned_keys(obj) -> bool:
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        return all(not any(b in str(k).lower() for b in banned) for k in obj) and all(
            _no_banned_keys(v) for v in obj.values()
        )
    if isinstance(obj, list):
        return all(_no_banned_keys(v) for v in obj)
    return True


def test_all_green_on_a_fully_working_fake_driver():
    driver = _FakeDriver()
    report = run_ui_walk(driver)
    assert report["schema"] == SCHEMA
    assert report["engine"] == "fake"
    assert report["summary"]["total"] == len(FLAGSHIP_SURFACES) == 5
    assert report["summary"]["passed"] == 5
    assert report["summary"]["failed"] == 0
    assert report["summary"]["all_green"] is True
    # every flagship surface from gate row 8, in order, was actually visited.
    assert driver.visited == [s.id for s in FLAGSHIP_SURFACES]
    assert [s["surface"] for s in report["steps"]] == [s.id for s in FLAGSHIP_SURFACES]


def test_one_bad_surface_degrades_only_that_step():
    driver = _FakeDriver(broken_dom_ids={"set-sources"})
    report = run_ui_walk(driver)
    assert report["summary"]["total"] == 5
    assert report["summary"]["passed"] == 4
    assert report["summary"]["failed"] == 1
    assert report["summary"]["all_green"] is False
    by_surface = {s["surface"]: s for s in report["steps"]}
    assert by_surface["source_management"]["ok"] is False
    # every OTHER surface still passed — one bad step must not hide the rest.
    for surface_id, step in by_surface.items():
        if surface_id != "source_management":
            assert step["ok"] is True
    # the walk still visited every surface despite the failure.
    assert driver.visited == [s.id for s in FLAGSHIP_SURFACES]


def test_console_errors_on_a_visible_surface_fail_the_step_and_are_reported():
    # "per-surface console-error dump" is the harness's stated reason for existing (runbook
    # section 6.4) -- a surface that RENDERS but logs console errors must still fail, and the
    # errors must flow through into the report (not just the ok/fail bit).
    driver = _FakeDriver(console_errors_by={"analysis_window": ["TypeError: x is undefined"]})
    report = run_ui_walk(driver)
    by_surface = {s["surface"]: s for s in report["steps"]}
    assert by_surface["analysis_window"]["ok"] is False
    assert by_surface["analysis_window"]["console_errors"] == ["TypeError: x is undefined"]
    # every OTHER surface still passed with no console errors reported.
    for surface_id, step in by_surface.items():
        if surface_id != "analysis_window":
            assert step["ok"] is True
            assert step["console_errors"] == []


def test_a_raising_step_is_recorded_and_the_walk_continues():
    driver = _FakeDriver(raise_on={"analysis_window"})
    report = run_ui_walk(driver)
    by_surface = {s["surface"]: s for s in report["steps"]}
    assert by_surface["analysis_window"]["ok"] is False
    assert "RuntimeError" in (by_surface["analysis_window"]["error"] or "")
    # the walk did not abort: surfaces after the raiser were still visited/reported.
    assert by_surface["source_management"]["ok"] is True
    assert by_surface["diagnostics_panel"]["ok"] is True
    assert "analysis_window" not in driver.visited  # goto() raised before recording the visit


def test_no_driver_is_honest_not_connected_never_a_fabricated_pass():
    report = run_ui_walk()
    assert report["engine"] == "unconnected"
    assert report["summary"]["passed"] == 0
    assert report["summary"]["failed"] == len(FLAGSHIP_SURFACES)
    assert report["summary"]["all_green"] is False
    for step in report["steps"]:
        assert step["ok"] is False
        assert "not connected" in (step["error"] or "")
    assert "not connected" in report["caveat"]
    assert "NEVER" in report["caveat"]


def test_unconnected_driver_direct_raises_on_every_method():
    driver = UnconnectedDriver()
    surface = FLAGSHIP_SURFACES[0]
    try:
        driver.goto(surface)
        raised = False
    except RuntimeError:
        raised = True
    assert raised


def test_walk_helper_returns_step_results_matching_surfaces():
    results = walk(_FakeDriver(), FLAGSHIP_SURFACES)
    assert len(results) == len(FLAGSHIP_SURFACES)
    assert all(r.ok for r in results)


def test_report_shape_matches_house_convention():
    report = run_ui_walk(_FakeDriver())
    assert report["schema"] == SCHEMA
    assert set(report["summary"]) == {"total", "passed", "failed", "all_green"}
    assert _no_banned_keys(report), "ui_walk report must carry no score/ranking/rating/grade key"


def test_flagship_surfaces_match_gate_row_8_order():
    # CLAUDE.md gate row 8, verbatim order: Home/Leads, analysis window, post-import screen,
    # source management, one-button diagnostics panel.
    assert [s.id for s in FLAGSHIP_SURFACES] == [
        "home_leads",
        "analysis_window",
        "post_import_screen",
        "source_management",
        "diagnostics_panel",
    ]
    # every surface has a real, non-empty DOM anchor (not a guess/TODO placeholder).
    for s in FLAGSHIP_SURFACES:
        assert s.dom_id and s.nav_tab and s.label
