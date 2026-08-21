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
targets, not guesses. **Re-verified 2026-08-13 against the current tree** (the UI moved twice
since this module was written -- the 2026-07-31 Settings restructure and the 2026-08-11/12
Advanced-subtab foldout move -- confirming the module's own warning that a surface's anchor can
go stale between sessions). **A SECOND re-verification the SAME day (this time by actually
driving a real browser, not just grepping for a DOM id) found the first pass had NOT gone far
enough**: ``#tab-analyze`` and Settings' panel both exist as DOM ids, but NEITHER has a
``.nav-item[data-tab=...]`` sidebar button to reach them any more -- the sidebar carries only
home/insights/timemap/law/agenda/indices/library (confirmed via ``grep 'class="nav-item"'``);
Settings opens via a dedicated gear button in the sidebar footer
(``button[onclick="showTab('settings')"]``), and the analysis window has NO static click target
at all -- it is reached exclusively by spawning a search (``openAnalysisFor(query)``, the same
function a keyword-chip click or the omnibar's Enter invokes; ``_anSpawn`` dedupes by query so
repeated calls with the same ``search_query`` reuse one tab rather than accumulating). A driver
that assumed ``nav_tab`` always means "click a sidebar nav-item" would silently time out on
these two -- exactly the lesson CLAUDE.md's own record keeps naming ("re-derive a defect's
mechanism from the code before patching what a report names"; here, the DOM-id check alone was
the shallow pass a real click-through was needed to catch):
  * Home/Leads          -> nav tab "home" (``#tab-home``, the Leads carousel + briefing feed)
  * the analysis window -> nav tab "analyze" (``#tab-analyze``), opened via
    ``openAnalysisFor(surface.search_query)`` -- NOT a nav-item click (see above)
  * the post-import screen -> the current import-summary render target (``#ux-imp-summary``,
    ``app.js:_renderImportSummary``), reached via Settings -> Data & backup -> the "Import..."
    button (``openUnifiedImport()``) which opens the top-level ``<dialog id="ux-import">`` (NOT
    nested under the Library tab, which is where an earlier session guessed it lived -- the
    dialog was deliberately moved to top level in the 2026-07-31 restructure because a
    ``<dialog>`` inside a ``display:none`` ancestor never renders even via ``showModal()``, per
    that PR's own comment at index.html). The DEDICATED post-import redesign (CLAUDE.md
    "POST-IMPORT RESULTS SCREEN") is itself still PENDING, so this anchors the surface that
    exists today and must be re-pointed again when that redesign ships.
  * source management   -> Settings subtab "advanced", section "sources" (``#src-table``). The
    "Sources" panel moved off its own top-level Settings subtab into a folded
    ``<details data-adv="sources">`` inside Advanced on 2026-07-31/08-11 (invariant #8:
    acquisition plumbing folds away); the previous ``#set-sources`` anchor no longer exists as a
    DOM id at all.
  * the one-button diagnostics panel -> Settings subtab "advanced", section "diagnostics"
    (``#diagnostics-panel`` -- the id itself is unchanged, but it moved from being a direct
    child of a top-level Settings subtab into the same folded-``<details>`` grammar as sources,
    on 2026-08-11 per that commit's own comment: "move all diagnostics from the data / backup
    subtab into a new section in the advanced subtab").
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
    """One surface to visit. The fields are the concrete anchors a real driver needs to reach
    it inside the SPA's nested nav grammar (top-level tab -> relocated subtab strip -> a folded
    Settings->Advanced ``<details>`` section -> an optional trigger click to open a dialog), so
    a real driver drops in without guessing at selectors. Only ``id``/``label``/``dom_id`` are
    required; everything else defaults to "not needed for this surface".

    ``nav_tab``        the tab identifier this surface lives under. For most tabs this IS a
                        ``.nav-item[data-tab]`` value (home/insights/timemap/law/agenda/indices/
                        library); "analyze" and "settings" are special-cased by a real driver
                        (neither has a sidebar nav-item any more -- see the module docstring)
                        but keep the SAME identifier here since it still names which tab/panel
                        is being reached. Leave empty when ``url`` is used instead (a surface
                        reached by direct navigation, e.g. the standalone reader or /tasks).
    ``search_query``    for ``nav_tab="analyze"`` ONLY: the query passed to
                        ``openAnalysisFor(query)``, the function that actually opens the
                        analysis window (there is no other click path). Empty string (the
                        default) opens the window unfiltered -- the whole seeded corpus,
                        never dependent on one language's vocabulary matching.
    ``subtab``          a ``data-tab`` value inside the RELOCATED ``#subtab-strip`` for this
                        ``nav_tab`` (``_relocateSubtabs`` in app.js moves the tab's own
                        ``ooSubtabs`` nav container into that one shared strip on every
                        ``showTab`` -- so a real driver always looks there, never at the
                        subtab's original nested location).
    ``advanced_section`` a Settings->Advanced ``data-adv`` value: the ``<details>`` foldout to
                        expand (folded-must-not-mean-fetched, so a real driver must click its
                        ``<summary>`` before the section's content is visible at all).
    ``trigger``          an optional CSS selector to click AFTER navigating (e.g. an "Import..."
                        button that opens a top-level ``<dialog>``).
    ``url``             an absolute path to navigate to directly instead of clicking the SPA
                        nav (the standalone reader, ``/tasks``).
    """

    id: str
    label: str
    dom_id: str
    nav_tab: str = ""
    search_query: str = ""
    subtab: str = ""
    advanced_section: str = ""
    trigger: str = ""
    url: str = ""
    note: str = ""


# Gate-row-8 order, verbatim (CLAUDE.md, "THE 0.3 CLOSE GATE", row 8).
FLAGSHIP_SURFACES: tuple[Surface, ...] = (
    Surface("home_leads", "Home / Leads", nav_tab="home", dom_id="tab-home"),
    Surface("analysis_window", "The analysis window", nav_tab="analyze", dom_id="tab-analyze"),
    Surface(
        "post_import_screen",
        "The post-import screen",
        nav_tab="settings",
        subtab="data",
        trigger='button[onclick="openUnifiedImport()"]',
        dom_id="ux-import",
        note=(
            "dom_id is the import DIALOG, deliberately: #ux-imp-summary (the 2026-08-13 "
            "anchor) is empty by construction until an import completes, and Playwright "
            "reads an empty zero-size div as not-visible, so anchoring there fails the "
            "reachability walk on every state that has not just imported (the 2026-08-13 "
            "run's recorded P0 was exactly this surface). This flagship row claims "
            "REACHABILITY; the real post-import CONTENT is claimed by the state-D import "
            "fixture walk (investigate_state_d_import), which runs a genuine volume-backup "
            "import and asserts the redesigned summary's own markers"
        ),
    ),
    Surface(
        "source_management",
        "Source management",
        nav_tab="settings",
        subtab="advanced",
        advanced_section="sources",
        dom_id="src-table",
        note="Settings > Advanced > Sources (folded; moved off its own subtab 2026-07-31/08-11)",
    ),
    Surface(
        "diagnostics_panel",
        "The one-button diagnostics panel",
        nav_tab="settings",
        subtab="advanced",
        advanced_section="diagnostics",
        dom_id="diagnostics-panel",
        note="Settings > Advanced > Diagnostics (folded; moved off Data & backup 2026-08-11)",
    ),
)


# Backlog surfaces from the click-through brief's coverage table (2026-08-13), each anchored the
# same way -- named because the brief calls them out by role, not because this is exhaustive.
# Deeper drilling (e.g. every analysis/settings subtab) is done by the walk script building
# ad-hoc Surface instances from the same `nav_tab`/`subtab`/`advanced_section` grammar; this
# tuple only fixes the coordinates for surfaces that need something beyond a plain subtab click.
BACKLOG_SURFACES: tuple[Surface, ...] = (
    Surface(
        "export_import_dialog",
        "Export / Import (unified dialog)",
        nav_tab="settings",
        subtab="data",
        trigger='button[onclick="openUnifiedExport()"]',
        dom_id="ux-export",
        note="the compartmented-export ask -- verify articles are no longer a forced checkbox",
    ),
    Surface(
        "world_map_server_ips",
        "World map -- Server IPs lens",
        nav_tab="timemap",
        # #oomap-lenses is its own nav, separate from the relocated #subtab-strip
        # mechanism every other tab uses -- so the lens switch is a `trigger` click on
        # its own button, never a `subtab`. The real render target is the sibling
        # `#oo-coverage-map`, not `#oomap-lens-bar` (which stays permanently empty).
        trigger='#oomap-lenses button[data-tab="servers"]',
        dom_id="oo-coverage-map",
        note="the Server-IP choropleth layer -- never rendered per the ledger's backlog list",
    ),
    Surface(
        "governments_law",
        "Governments -> Law",
        nav_tab="law",
        subtab="law",
        dom_id="gov-law",
        note="known-open item: the tab defaults to Countries, not Law, on every fresh load",
    ),
    Surface(
        "settings_ai",
        "Settings -> AI (the pill's third state, backend panel, roster install)",
        nav_tab="settings",
        subtab="models",
        dom_id="set-models",
    ),
    Surface(
        "settings_cards",
        "Settings -> Cards (the 37 Lead producers, safe ranges)",
        nav_tab="settings",
        subtab="cards",
        dom_id="set-cards",
    ),
    Surface(
        "keyword_supergroups",
        "Settings -> Advanced -> Keywords (group/super-group curation, the concept map)",
        nav_tab="settings",
        subtab="advanced",
        advanced_section="keywords",
        # `#kx-keywords` is a DRILL-DOWN target -- loadKeywordExplorer() (the section's
        # first loader) explicitly clears it and leaves it empty until the user clicks
        # a facet chip (kxShowTag), so checking it reports a false "not visible" on a
        # perfectly healthy section -- found live 2026-08-13, confirmed via a direct
        # DOM dump: `#kx-facets` (591 chars of real facet chips) and `#sgc-list` (the
        # super-group curation cards -- "the concept map" this Surface's own label
        # names) both render substantial real content on the SAME open, only
        # `#kx-keywords` stays at 0 chars by design. `#sgc-list` is the anchor that
        # actually matches the label.
        dom_id="sgc-list",
    ),
    Surface(
        "agenda_month",
        "Agenda -- month grid, glyphs, deduced events",
        nav_tab="agenda",
        subtab="month",
        dom_id="agenda-month",
    ),
    Surface(
        "task_manager",
        "Task manager -- Active / Queue / System / Schedule",
        url="/tasks",
        dom_id="tm-tabs",
        note="a standalone static page (not the SPA nav) -- its own tm-tabs use data-panel",
    ),
    Surface(
        "bulletin",
        "Bulletin -- review screen + the Settings section",
        nav_tab="settings",
        subtab="advanced",
        advanced_section="bulletin",
        dom_id="bulletin-panel",
    ),
)


def reader_surface(article_id: int) -> Surface:
    """The standalone offline READER for one article — the 2026-08-13 report's single
    largest named-surface gap (§4 row 13: "not covered at all"). The reader is a
    server-rendered page at ``/api/articles/{id}/view``, NOT part of the SPA, so it is
    reached via the ``url`` navigation path (the same grammar ``/tasks`` uses), never a
    ``nav_tab`` click. A Surface cannot carry the article id statically (ids are
    per-corpus), so this is a FACTORY the walk script calls with a real id discovered
    from the corpus under test — consistent with the ad-hoc-Surface convention the
    subtab drills already use.

    ``dom_id`` anchors on ``rp-read`` — the Read pane (``src/api/main.py`` renders the
    tab bar as ``.rtab[data-rtab=...]`` buttons over ``#rp-<key>`` panes; ``read`` is
    the default-active pane, so it is the one that must be non-empty on load). The tab
    DRILL (every ``data-rtab``, the two-class provenance groups ``.mgrp`` /
    ``.mgrp.deduced`` / ``.mgrp.ai-derived``, the Loaded-language pane) is the walk
    script's job, same as every other sub-capability drill."""
    return Surface(
        "reader",
        "Reader — tabs, provenance classes, Loaded-language",
        url=f"/api/articles/{article_id}/view",
        dom_id="rp-read",
        note=(
            "standalone server-rendered page (never the SPA nav); the id comes from the "
            "corpus under test at run time via this factory"
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
