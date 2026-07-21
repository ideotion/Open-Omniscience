"""
ui_walk — the browser click-through walk harness SKELETON (planning §6, gate row 8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS IS: gate row 8 of the 0.3 CLOSE GATE (CLAUDE.md §"THE 0.3 CLOSE GATE") needs either
the AppVM ``ui_walk`` runner STANDING or a defined hand click-through of the flagship surfaces
before "browser-unverified, needs click-through" can retire. The companion runbook
(``docs/design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md`` §6.4) specs ``ui_walk`` as: boot
the app, walk every tab/subtab, take a per-surface screenshot + console-error dump. That runner
needs a headless browser (the runbook leans Firefox/Gecko: ``firefox --headless --screenshot``
is its own smoke check) and, for the full loop, the maintainer's AppVM — both browser-gated and
VM-gated, absent from this non-VM session (see the SAME caveat already recorded at
``recursive_loop.py``, ``kpi.py`` K12, and the ``/recursive-loop`` endpoint docstring).

WHAT THIS MODULE IS: the reusable INSTRUMENT the runbook says the first VM session should build
— defining WHAT a walk visits and HOW a pass/fail is recorded — with the actual browser-driving
mechanism behind an injectable ``UiWalkDriver`` interface, so the control flow (visit each
flagship surface, catch+record per-step failures, never abort the whole walk on one bad step,
shape the report) can be proven correct on a fake driver TODAY, and a real driver (Playwright's
Firefox channel, or a thin ``firefox --headless`` wrapper — the build-time decision this module
does NOT make) can be dropped in later without touching this control flow.

WHAT THIS MODULE IS NOT (read before treating gate row 8 as satisfied):
  * NOT a real browser session. ``run_ui_walk()`` with no driver uses ``UnconnectedDriver``,
    which fails every step with an honest "not connected" error — never a fabricated pass.
  * NOT the AppVM runner (R3). No VM orchestration, no Ollama, no self-observation loop here.
  * NOT proof of anything "standing". Only a real driver run — from the AppVM per the runbook's
    safety lines (§6.3), or a maintainer's manual click-through — retires gate row 8.

The five flagship surfaces (CLAUDE.md gate row 8, verbatim order) are anchored to the actual
``src/static/index.html`` single-page-app structure so a future real driver has concrete
targets, not guesses:
  * Home/Leads          -> nav tab "home" (``#tab-home``, the Leads carousel + briefing feed)
  * the analysis window -> nav tab "analyze" (``#tab-analyze``)
  * the post-import screen -> the current import-summary render target (``#ux-imp-summary``,
    ``app.js:_renderImportSummary``); the DEDICATED post-import redesign is itself still
    PENDING (CLAUDE.md "POST-IMPORT RESULTS SCREEN"), so this anchors the surface that exists
    today and must be re-pointed when that redesign ships.
  * source management   -> Settings subtab "sources" (``#set-sources``)
  * the one-button diagnostics panel -> Settings subtab "data" (``#diagnostics-panel``)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

_LOG = logging.getLogger(__name__)

SCHEMA = "oo-ui-walk-1"


@dataclass(frozen=True)
class Surface:
    """One flagship surface to visit. ``nav_tab``/``dom_id`` are the concrete anchors a real
    driver would use (a data-tab click, then a visibility check on the DOM id) — kept here so a
    real driver drops in without this module guessing at selectors."""

    id: str
    label: str
    nav_tab: str
    dom_id: str
    note: str = ""


# Gate-row-8 order, verbatim (CLAUDE.md, "THE 0.3 CLOSE GATE", row 8).
FLAGSHIP_SURFACES: tuple[Surface, ...] = (
    Surface("home_leads", "Home / Leads", nav_tab="home", dom_id="tab-home"),
    Surface("analysis_window", "The analysis window", nav_tab="analyze", dom_id="tab-analyze"),
    Surface(
        "post_import_screen",
        "The post-import screen",
        nav_tab="library",
        dom_id="ux-imp-summary",
        note=(
            "anchors the CURRENT import-summary render target (app.js:_renderImportSummary); "
            "the dedicated post-import redesign (CLAUDE.md) is still pending -- re-point this "
            "surface's dom_id when that ships"
        ),
    ),
    Surface(
        "source_management",
        "Source management",
        nav_tab="settings",
        dom_id="set-sources",
        note="Settings > Sources subtab",
    ),
    Surface(
        "diagnostics_panel",
        "The one-button diagnostics panel",
        nav_tab="settings",
        dom_id="diagnostics-panel",
        note="Settings > Data & backup subtab",
    ),
)


class UiWalkDriver(Protocol):
    """The seam a real browser plugs into. No implementation lives in this module: a real
    driver (Playwright's Firefox channel, or a thin ``firefox --headless`` wrapper -- a
    build-time decision this scaffold does not make) implements this and is passed to
    ``run_ui_walk``/``walk``. Every method may raise; the walker catches per-step and never lets
    one bad surface abort the rest."""

    def goto(self, surface: Surface) -> None:
        """Navigate to ``surface`` (e.g. click its nav tab, wait for the DOM id to appear)."""
        ...

    def is_visible(self, dom_id: str) -> bool:
        """Whether ``dom_id`` is present and actually rendered (not ``hidden``/``display:none``)."""
        ...

    def console_errors(self) -> list[str]:
        """Console errors observed since the last ``goto`` (empty list if none / not supported)."""
        ...

    def screenshot(self, surface: Surface) -> str | None:
        """Capture a per-surface screenshot; return its path (or None if unsupported)."""
        ...


class UnconnectedDriver:
    """The DEFAULT driver: honestly refuses every step rather than fabricating a pass. This is
    what ``run_ui_walk()`` uses when no real driver is injected -- the expected state until a real
    browser (AppVM per the runbook, or a maintainer session) supplies one."""

    engine = "unconnected"

    def goto(self, surface: Surface) -> None:
        raise RuntimeError(
            "ui_walk driver not connected -- needs a real UiWalkDriver "
            "(Playwright/Firefox or an AppVM `firefox --headless` wrapper per "
            "docs/design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md section 6.4), not built here"
        )

    def is_visible(self, dom_id: str) -> bool:
        raise RuntimeError("ui_walk driver not connected")

    def console_errors(self) -> list[str]:
        raise RuntimeError("ui_walk driver not connected")

    def screenshot(self, surface: Surface) -> str | None:
        raise RuntimeError("ui_walk driver not connected")


@dataclass
class StepResult:
    surface: str
    label: str
    ok: bool
    console_errors: list[str] = field(default_factory=list)
    screenshot: str | None = None
    error: str | None = None


def walk(driver: UiWalkDriver, surfaces: tuple[Surface, ...] = FLAGSHIP_SURFACES) -> list[StepResult]:
    """Visit each surface with ``driver``, recording one ``StepResult`` per surface. Degrades
    loudly per step -- a raising/failing surface is recorded with its error and the walk
    continues to the rest (one bad surface must never hide the others)."""
    results: list[StepResult] = []
    for surface in surfaces:
        try:
            driver.goto(surface)
            visible = driver.is_visible(surface.dom_id)
            errors = driver.console_errors()
            shot = driver.screenshot(surface)
            ok = bool(visible) and not errors
            results.append(
                StepResult(
                    surface=surface.id,
                    label=surface.label,
                    ok=ok,
                    console_errors=list(errors),
                    screenshot=shot,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a raising step degrades, never aborts the walk
            results.append(
                StepResult(
                    surface=surface.id,
                    label=surface.label,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


def run_ui_walk(
    driver: UiWalkDriver | None = None, surfaces: tuple[Surface, ...] = FLAGSHIP_SURFACES
) -> dict:
    """Run the click-through walk and return a report shaped like the repo's other diagnostics
    reports (``schema`` + per-step detail + a counts-only ``summary``, no score/rating/grade
    key). With no driver (the default), every step fails with an honest "not connected" error --
    this function alone can NEVER report the runner as standing."""
    engine = getattr(driver, "engine", type(driver).__name__ if driver else "unconnected")
    results = walk(driver or UnconnectedDriver(), surfaces)
    passed = sum(1 for r in results if r.ok)
    failed = len(results) - passed
    _LOG.info("ui_walk: engine=%s passed=%d failed=%d", engine, passed, failed)
    return {
        "schema": SCHEMA,
        "engine": engine,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "steps": [
            {
                "surface": r.surface,
                "label": r.label,
                "ok": r.ok,
                "console_errors": r.console_errors,
                "screenshot": r.screenshot,
                "error": r.error,
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "all_green": (passed == len(results)) if results else False,
        },
        "caveat": (
            "This is the ui_walk HARNESS ONLY. With no real driver injected (the default), every "
            "step fails honestly with 'not connected' -- this report NEVER means the AppVM runner "
            "is standing or that any surface is browser-verified. A real UiWalkDriver "
            "(Playwright/Firefox or an AppVM `firefox --headless` wrapper) plus an actual "
            "AppVM/maintainer run are both still required to retire 0.3 gate row 8."
        ),
    }
