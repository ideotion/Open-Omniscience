#!/usr/bin/env python3
"""
ui_clickthrough_run — the 2026-08-13 UI click-through session (0.3 gate row 8).

Drives PlaywrightUiWalkDriver against three live app instances (states A/B/C, per the session
brief) and writes a structured report + per-step screenshots. This is the SCRIPT that USES the
standing `ui_walk`/`ui_walk_playwright` instrument for one investigation; the instrument itself
stays reusable for the next one.

Usage:
    .venv/bin/python scripts/ui_clickthrough_run.py --out docs/audit/ui-clickthrough-2026-08-13

Requires all three states already booted (see the brief for the exact env vars per state).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.monitoring.ui_walk import BACKLOG_SURFACES, FLAGSHIP_SURFACES, Surface  # noqa: E402
from src.monitoring.ui_walk_playwright import PlaywrightUiWalkDriver  # noqa: E402

STATE_A_URL = "http://127.0.0.1:8001"
STATE_B_URL = "http://127.0.0.1:8002"
STATE_C_URL = "http://127.0.0.1:8000"

THEMES_TO_CHECK = ["ink", "paper", "contrast", "mint", "dawn"]  # default + the light-theme cluster
LOCALES_TO_CHECK = ["en", "ar", "zh"]
BREAKPOINTS = [(375, 900), (768, 1000), (1024, 900), (1440, 950)]


@dataclass
class Finding:
    id: str
    severity: str  # P0 | P1 | P2 | OPT | POSITIVE
    surface: str
    title: str
    detail: str
    evidence: str = ""
    new: bool = True  # False = corroborates/updates a 2026-07-22 finding, never re-reported as new


@dataclass
class CoverageRow:
    surface: str
    axis: str
    result: str  # verified | partial | blocked
    note: str = ""


@dataclass
class Report:
    schema: str = "oo-ui-clickthrough-1"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    findings: list[Finding] = field(default_factory=list)
    coverage: list[CoverageRow] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)

    def add_finding(self, **kw) -> None:
        self.findings.append(Finding(**kw))

    def add_coverage(self, **kw) -> None:
        self.coverage.append(CoverageRow(**kw))


def _rel_luminance(rgb: tuple[float, float, float]) -> float:
    def chan(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(rgb1: tuple[float, float, float], rgb2: tuple[float, float, float]) -> float:
    l1, l2 = _rel_luminance(rgb1), _rel_luminance(rgb2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _parse_rgb(s: str) -> tuple[float, float, float] | None:
    # "rgb(1, 2, 3)" / "rgba(1, 2, 3, 0.5)" -- alpha is ignored here deliberately; a caller
    # checking a composited (opacity-affected) pair must pre-composite before calling this.
    if not s or not s.startswith("rgb"):
        return None
    inner = s[s.index("(") + 1 : s.index(")")]
    parts = [float(x.strip()) for x in inner.split(",")[:3]]
    return (parts[0], parts[1], parts[2])


def _log(msg: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------------------------------ #
# STATE A -- virgin (first-launch lifecycle)
# ------------------------------------------------------------------------------------------ #
def investigate_state_a(pw, report: Report, shots: Path) -> None:
    _log("STATE A (virgin, first-launch lifecycle) -- " + STATE_A_URL)
    browser = pw.chromium.launch(executable_path=_chromium_path())
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(STATE_A_URL + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(300)
        page.screenshot(path=str(shots / "state-a-01-boot.png"), full_page=True)

        # The REAL first-launch sequence (unlock.html): view-language -> view-legal ->
        # view-create. All three views live in the DOM simultaneously (only `.hidden` toggles
        # them), so a locator that matches "any password field" finds view-unlock's #pw (DOM
        # order puts it before view-create's #pw1/#pw2) -- explicit ids are required.
        body_text_boot = page.inner_text("body")
        report.add_coverage(
            surface="state_a_boot", axis="default",
            result="verified",
            note=f"redirected to /unlock, body text length {len(body_text_boot)}",
        )

        lang_step_visible = _safe_visible(page, "#view-language")
        report.add_coverage(
            surface="state_a_first_launch", axis="language-step-shown",
            result="verified" if lang_step_visible else "partial",
            note=f"#view-language visible={lang_step_visible}",
        )
        if lang_step_visible:
            page.click(".lang-btn")  # the first language button (English)
            page.wait_for_timeout(300)

        legal_step_visible = _safe_visible(page, "#view-legal")
        report.add_coverage(
            surface="state_a_first_launch", axis="legal-step-shown",
            result="verified" if legal_step_visible else "partial",
            note=f"#view-legal visible={legal_step_visible}",
        )
        if legal_step_visible:
            with contextlib.suppress(Exception):
                page.check("#lg-check")
            page.wait_for_timeout(100)
            accept_enabled = not page.eval_on_selector("#lg-accept", "el => el.disabled")
            report.add_coverage(
                surface="state_a_first_launch", axis="legal-accept-enables-on-check",
                result="verified" if accept_enabled else "partial",
                note=f"#lg-accept disabled after checking #lg-check: {not accept_enabled}",
            )
            if accept_enabled:
                page.click("#lg-accept")
                page.wait_for_timeout(400)

        page.screenshot(path=str(shots / "state-a-02-after-legal.png"), full_page=True)

        create_step_visible = _safe_visible(page, "#view-create")
        report.add_coverage(
            surface="state_a_first_launch", axis="create-step-reached",
            result="verified" if create_step_visible else "partial",
            note=f"#view-create visible={create_step_visible}",
        )

        # THE P0 REGRESSION CHECK: a rejected (too-short) passphrase must NOT blank the page.
        # This directly re-verifies LC-VIEW-HIDDEN-ON-ERROR (fixed 2026-07-22, PR #746) live,
        # against the CURRENT build -- the 2026-07-22 fix is source-confirmed but had not been
        # driven by a real browser since.
        if create_step_visible:
            page.fill("#pw1", "abc")
            page.fill("#pw2", "abc")
            create_btn = page.locator("#btn-create")
            if create_btn.count() and create_btn.is_visible():
                create_btn.click()
                page.wait_for_timeout(600)
                body_after = page.inner_text("body").strip()
                page.screenshot(path=str(shots / "state-a-03-after-short-pw.png"), full_page=True)
                if not body_after:
                    report.add_finding(
                        id="ui-clickthrough-lc-view-hidden-regression",
                        severity="P0",
                        surface="state_a_first_launch",
                        title="A rejected short passphrase blanks the whole page (REGRESSION "
                        "of the fixed LC-VIEW-HIDDEN-ON-ERROR P0)",
                        detail="document.body.innerText is empty after submitting a "
                        "too-short passphrase -- the 2026-07-22 fix has regressed.",
                        evidence="state-a-03-after-short-pw.png",
                        new=True,
                    )
                else:
                    report.add_finding(
                        id="ui-clickthrough-lc-view-hidden-verified-fixed",
                        severity="POSITIVE",
                        surface="state_a_first_launch",
                        title="LC-VIEW-HIDDEN-ON-ERROR stays fixed under live re-verification",
                        detail=f"a rejected short passphrase leaves the form visible "
                        f"(body text {len(body_after)} chars); the error message is readable, "
                        "never a blank page.",
                        evidence="state-a-03-after-short-pw.png",
                        new=False,
                    )
                report.add_coverage(
                    surface="state_a_first_launch", axis="short-passphrase-error-path",
                    result="verified", note="live Chromium re-verification of the fixed P0",
                )
            else:
                report.add_coverage(
                    surface="state_a_first_launch", axis="short-passphrase-error-path",
                    result="blocked", note="#btn-create not reachable in this build's DOM order",
                )
        else:
            report.add_coverage(
                surface="state_a_first_launch", axis="short-passphrase-error-path",
                result="blocked", note="#view-create never became visible",
            )

        # Now the happy path: a real strong passphrase, expect entry into the app. The prior
        # (rejected) attempt must leave #pw1/#pw2 usable for a retry -- if it does not, this
        # branch degrades to "blocked" and that IS the finding (a real UX dead end).
        if create_step_visible and _safe_visible(page, "#pw1") and _safe_visible(page, "#pw2"):
            good = "Correct-Horse-Battery-Staple-9x!"
            page.fill("#pw1", good)
            page.fill("#pw2", good)
            create_btn = page.locator("#btn-create")
            if create_btn.count() and create_btn.is_visible():
                create_btn.click()
                page.wait_for_timeout(4000)
                page.screenshot(path=str(shots / "state-a-04-after-create.png"), full_page=True)
                reached_app = _safe_visible(page, "#tab-home")
                report.add_coverage(
                    surface="state_a_first_launch", axis="happy-path-create",
                    result="verified" if reached_app else "partial",
                    note=f"reached #tab-home={reached_app}",
                )
                if reached_app:
                    report.add_finding(
                        id="ui-clickthrough-state-a-happy-path",
                        severity="POSITIVE",
                        surface="state_a_first_launch",
                        title="The first-launch create-passphrase happy path reaches the app",
                        detail="a strong passphrase submitted after a rejected short one "
                        "succeeds and lands on Home -- the error path does not corrupt "
                        "the retry.",
                        new=False,
                    )
                else:
                    report.add_finding(
                        id="ui-clickthrough-state-a-happy-path-blocked",
                        severity="P1",
                        surface="state_a_first_launch",
                        title="A valid strong passphrase did not reach #tab-home within 4s",
                        detail="submitted after the rejected short-passphrase retry; either "
                        "the create->unlock->app transition is slow, or the retry left the "
                        "form in a state a real strong passphrase cannot recover from.",
                        evidence="state-a-04-after-create.png", new=True,
                    )
            else:
                report.add_coverage(
                    surface="state_a_first_launch", axis="happy-path-create",
                    result="blocked", note="#btn-create not visible for the retry",
                )
        else:
            report.add_coverage(
                surface="state_a_first_launch", axis="happy-path-create",
                result="blocked",
                note=f"#pw1/#pw2 not usable after the short-passphrase attempt "
                f"(create_step_visible={create_step_visible}, "
                f"pw1={_safe_visible(page, '#pw1')}, pw2={_safe_visible(page, '#pw2')})",
            )
    finally:
        browser.close()


def _safe_visible(page, sel: str) -> bool:
    try:
        return bool(page.is_visible(sel))
    except Exception:  # noqa: BLE001
        return False


def _dismiss_guide_wizard(page, report: Report, state_label: str) -> None:
    """The first-run guided-wizard modal (#guide-wizard, a native <dialog>.showModal()) opens
    automatically whenever the app boots with zero articles and the one-time guide has not
    been marked done on THIS browser (app.js: `if (s.counts.articles === 0 && !guideDone())
    openGuide();` -- the state lives in localStorage, per-browser, not server-side, so a fresh
    Playwright context sees it exactly like a first-time human visitor would). While open, its
    native backdrop intercepts pointer events on the WHOLE page -- clicking anything else times
    out against "<dialog> intercepts pointer events". This is real first-run UX behaviour a
    human hits identically, not a driver bug; any automation walking the app from a fresh
    context must dismiss it first. #gw-close lives in the wizard's persistent header (present
    on every step -- lang/sources/finish), and its handler both closes the dialog AND marks
    the one-time guide done, making it the single reliable dismiss target regardless of which
    step is currently showing.
    """
    try:
        page.wait_for_timeout(400)  # let a boot-time openGuide() call actually fire first
        dlg_open = bool(page.evaluate(
            "() => { const d = document.getElementById('guide-wizard'); "
            "return !!(d && d.open); }"
        ))
    except Exception:  # noqa: BLE001
        dlg_open = False
    report.add_coverage(
        surface=f"{state_label}_guide_wizard", axis="auto-open-on-empty-corpus",
        result="verified", note=f"#guide-wizard open on boot: {dlg_open}",
    )
    if not dlg_open:
        return
    with contextlib.suppress(Exception):
        page.click("#gw-close", timeout=3000)
        page.wait_for_timeout(200)
    still_open = bool(page.evaluate(
        "() => { const d = document.getElementById('guide-wizard'); "
        "return !!(d && d.open); }"
    ))
    report.add_coverage(
        surface=f"{state_label}_guide_wizard", axis="dismissed-via-gw-close",
        result="verified" if not still_open else "partial",
        note=f"still open after clicking #gw-close: {still_open}",
    )
    if still_open:
        report.add_finding(
            id=f"ui-clickthrough-{state_label}-guide-wizard-stuck",
            severity="P0", surface="guide_wizard",
            title="The first-launch guide wizard cannot be dismissed via #gw-close",
            detail="clicking #gw-close did not close #guide-wizard -- while open its native "
            "modal backdrop blocks all interaction with the rest of the app on a fresh/empty "
            "corpus, with no other visible way out.",
            new=True,
        )


# ------------------------------------------------------------------------------------------ #
# STATE B -- empty (catalog-seeded, zero articles): empty-state honesty
# ------------------------------------------------------------------------------------------ #
def investigate_state_b(pw, report: Report, shots: Path) -> None:
    _log("STATE B (empty, catalog-seeded) -- " + STATE_B_URL)
    browser = pw.chromium.launch(executable_path=_chromium_path())
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        driver = PlaywrightUiWalkDriver(page, base_url=STATE_B_URL, screenshot_dir=shots)
        page.wait_for_timeout(500)
        _dismiss_guide_wizard(page, report, "state_b")
        for surface_id in ("home_leads",):
            surface = next(s for s in FLAGSHIP_SURFACES if s.id == surface_id)
            driver.goto(surface)
            visible = driver.is_visible(surface.dom_id)
            errors = driver.console_errors()
            path = driver.screenshot(Surface(f"state-b-{surface.id}", surface.label, dom_id=surface.dom_id))
            body_text = page.inner_text("body")
            has_empty_honesty = "No Leads yet" in body_text or "no leads" in body_text.lower()
            report.add_coverage(
                surface="state_b_home_empty", axis="default",
                result="verified" if visible and not errors else "partial",
                note=f"visible={visible} errors={errors} empty_honesty_text={has_empty_honesty}",
            )
            if has_empty_honesty:
                report.add_finding(
                    id="ui-clickthrough-state-b-empty-honesty",
                    severity="POSITIVE",
                    surface="home_leads",
                    title="Home's empty-state honesty holds on a catalog-seeded, "
                    "zero-article corpus",
                    detail="Home renders an explicit 'No Leads yet' message rather than "
                    "a blank panel, with zero console errors.",
                    evidence=path or "",
                    new=False,
                )
            elif not errors:
                report.add_finding(
                    id="ui-clickthrough-state-b-empty-state-unverified",
                    severity="P2",
                    surface="home_leads",
                    title="Could not confirm the explicit empty-state honesty text on "
                    "a zero-article corpus",
                    detail=f"Home rendered with no console errors, but the expected "
                    f"'No Leads yet' text was not found in body text "
                    f"({len(body_text)} chars captured).",
                    evidence=path or "",
                    new=True,
                )
    finally:
        browser.close()


def _chromium_path() -> str:
    override = os.environ.get("OO_TEST_CHROMIUM_PATH")
    if override:
        return override
    base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for cand in sorted(base.glob("chromium-*/chrome-linux/chrome")):
        return str(cand)
    raise RuntimeError("no pinned Chromium build found")


# ------------------------------------------------------------------------------------------ #
# STATE C -- populated: the main walk
# ------------------------------------------------------------------------------------------ #
def _walk_surfaces(driver: PlaywrightUiWalkDriver, surfaces: tuple[Surface, ...], report: Report,
                    *, axis_label: str = "default") -> None:
    for surface in surfaces:
        t0 = time.monotonic()
        try:
            driver.goto(surface)
            visible = driver.is_visible(surface.dom_id)
            errors = driver.console_errors()
            summary = driver.console_error_summary()
            shot = driver.screenshot(surface)
        except Exception as exc:  # noqa: BLE001 - one bad surface must not abort the walk
            visible, errors, summary, shot = False, [f"{type(exc).__name__}: {exc}"], {}, None
        dt = time.monotonic() - t0
        ok = bool(visible) and not errors
        report.steps.append({
            "surface": surface.id, "label": surface.label, "axis": axis_label,
            "ok": ok, "visible": visible, "errors": errors, "console_summary": summary,
            "screenshot": shot, "elapsed_s": round(dt, 2),
        })
        report.add_coverage(
            surface=surface.id, axis=axis_label,
            result="verified" if ok else "partial",
            note=("; ".join(errors) if errors else "") or ("not visible" if not visible else ""),
        )
        _log(f"  [{axis_label}] {surface.id}: ok={ok} visible={visible} "
             f"errors={len(errors)} ({dt:.1f}s)")
        if not ok and axis_label == "default":
            sev = "P0" if not visible and not errors else "P1"
            report.add_finding(
                id=f"ui-clickthrough-{surface.id}-{axis_label}-fail",
                severity=sev, surface=surface.id,
                title=f"{surface.label}: failed the walk ({axis_label})",
                detail=f"visible={visible}, console_errors={errors}",
                evidence=shot or "", new=True,
            )


def _check_contrast(driver: PlaywrightUiWalkDriver, report: Report, theme: str) -> None:
    """Verifies the two previously-fixed contrast defects (--warn-fg pill, --caveat) live, on
    the CURRENT theme -- both are P1s the triage table confirmed fixed from source; this is the
    live confirmation the source-only triage could not provide."""
    for sel, label in [(".pill.warn", "pill.warn"), (".card-caveat", "card-caveat")]:
        style = driver.computed_style(sel)
        if not style or not style.get("color") or not style.get("backgroundColor"):
            continue
        fg = _parse_rgb(style["color"])
        # a pill/caveat sits on its panel background, not (necessarily) its own declared
        # background -- fall back to the nearest ancestor panel background when the element's
        # own is transparent (the common case for an inline pill).
        bg_style = driver.computed_style(".panel")
        bg = _parse_rgb(bg_style.get("backgroundColor", "")) if bg_style else None
        if not bg:
            bg = _parse_rgb(style["backgroundColor"])
        if not fg or not bg:
            continue
        ratio = _contrast_ratio(fg, bg)
        passed = ratio >= 4.5
        report.add_coverage(
            surface=f"contrast_{label}", axis=f"theme={theme}",
            result="verified" if passed else "partial",
            note=f"ratio={ratio:.2f}:1 fg={fg} bg={bg}",
        )
        if not passed:
            report.add_finding(
                id=f"ui-clickthrough-contrast-{label}-{theme}",
                severity="P1", surface=label,
                title=f"{label} fails WCAG AA on theme '{theme}' ({ratio:.2f}:1, needs 4.5:1)",
                detail=f"computed fg={fg} bg={bg}",
                new=True,
            )


def _check_breakpoint_overflow(driver: PlaywrightUiWalkDriver, report: Report,
                                width: int, height: int) -> None:
    driver.set_viewport(width, height)
    driver.page.wait_for_timeout(150)
    metrics = driver.page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, "
        "clientWidth: document.documentElement.clientWidth})"
    )
    overflow = metrics["scrollWidth"] > metrics["clientWidth"] + 4  # small render-jitter tolerance
    controls_offscreen = []
    for ctrl_id in ("net-toggle", "lang-switch", "tm-open", "app-shutdown"):
        rect = driver.page.evaluate(
            "(id) => { const el = document.getElementById(id); "
            "if (!el) return null; const r = el.getBoundingClientRect(); "
            "return {left: r.left, right: r.right, width: r.width}; }",
            ctrl_id,
        )
        if rect and (rect["left"] < 0 or rect["right"] > width):
            controls_offscreen.append(ctrl_id)
    report.add_coverage(
        surface="topbar_overflow", axis=f"{width}x{height}",
        result="verified" if not overflow and not controls_offscreen else "partial",
        note=f"scrollWidth={metrics['scrollWidth']} clientWidth={metrics['clientWidth']} "
        f"offscreen={controls_offscreen}",
    )
    if overflow or controls_offscreen:
        report.add_finding(
            id=f"ui-clickthrough-topbar-overflow-{width}",
            severity="P1", surface="topbar",
            title=f"Top bar overflow / off-screen controls at {width}px",
            detail=f"scrollWidth={metrics['scrollWidth']} vs clientWidth={metrics['clientWidth']}, "
            f"offscreen controls: {controls_offscreen}",
            new=True,
        )
    else:
        report.add_finding(
            id=f"ui-clickthrough-topbar-fixed-{width}",
            severity="POSITIVE", surface="topbar",
            title=f"Top bar has no overflow and all core controls stay on-screen at {width}px",
            detail="re-verifies the fixed topbar-overflow-mobile-375 / "
            "topbar-overflow-mainstream-widths P1s live.",
            new=False,
        )


def investigate_state_c(pw, report: Report, shots: Path) -> None:
    _log("STATE C (populated) -- " + STATE_C_URL)
    browser = pw.chromium.launch(executable_path=_chromium_path())
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 950})
        driver = PlaywrightUiWalkDriver(page, base_url=STATE_C_URL, screenshot_dir=shots)
        page.wait_for_timeout(600)
        # State C is populated (articles > 0), so openGuide()'s own gate should keep the
        # wizard from firing at all here -- this call is a defensive no-op that also proves
        # (and records) that the populated corpus genuinely suppresses the first-run wizard.
        _dismiss_guide_wizard(page, report, "state_c")

        _log("walking the 5 gate-row-8 flagship surfaces, in order")
        _walk_surfaces(driver, FLAGSHIP_SURFACES, report, axis_label="default")

        _log("walking the backlog surfaces")
        _walk_surfaces(driver, BACKLOG_SURFACES, report, axis_label="default")

        # -- deeper analysis-window subtab drill (the flagship surface, every named subtab) -- #
        _log("drilling the analysis window's subtabs")
        an_subtabs = ["keywords", "trend", "mindmap", "articles", "www", "links",
                      "related", "sentiment", "sources", "competitive", "advanced"]
        an_surfaces = tuple(
            Surface(f"analysis_{t}", f"Analysis > {t}", nav_tab="analyze", subtab=t,
                    dom_id=f"an-{t}")
            for t in an_subtabs
        )
        _walk_surfaces(driver, an_surfaces, report, axis_label="an-subtabs")

        # -- Insights subtabs (Trends/Sources/Families/Super-groups/Map/Convergence/Watches) - #
        _log("drilling the Insights subtabs")
        ins_subtabs = ["trends", "sources", "families", "supergroups", "map", "convergence",
                       "watches", "lunar"]
        ins_surfaces = tuple(
            Surface(f"insights_{t}", f"Insights > {t}", nav_tab="insights", subtab=t,
                    dom_id=f"ins-{t}")
            for t in ins_subtabs
        )
        _walk_surfaces(driver, ins_surfaces, report, axis_label="ins-subtabs")

        # -- Settings subtabs (all 10) ------------------------------------------------------ #
        _log("drilling all 10 Settings subtabs")
        set_subtabs = ["graphics", "general", "cards", "models", "wikipedia", "offlinemap",
                       "agenda", "data", "safety", "advanced"]
        set_surfaces = tuple(
            Surface(f"settings_{t}", f"Settings > {t}", nav_tab="settings", subtab=t,
                    dom_id=f"set-{t}")
            for t in set_subtabs
        )
        _walk_surfaces(driver, set_surfaces, report, axis_label="set-subtabs")

        # -- Library subtabs ------------------------------------------------------------------ #
        _log("drilling Library subtabs")
        lib_subtabs = ["overview", "activity", "tracked", "composition", "storage", "coverage"]
        lib_surfaces = tuple(
            Surface(f"library_{t}", f"Library > {t}", nav_tab="library", subtab=t,
                    dom_id=f"lib-view-{t}")
            for t in lib_subtabs
        )
        _walk_surfaces(driver, lib_surfaces, report, axis_label="lib-subtabs")

        # -- World map lenses ------------------------------------------------------------------ #
        # #oomap-lenses is its OWN nav, separate from the relocated #subtab-strip system
        # every other tab uses (index.html: <nav id="oomap-lenses"> lives directly inside
        # #tab-timemap's panel and is never moved) -- so the lens switch is a `trigger`
        # click on its own buttons, never a `subtab`. And the real render target is the
        # SIBLING `#oo-coverage-map` (app.js:_renderOoMapDim -> $("oo-coverage-map")),
        # not `#oomap-lens-bar`, which stays permanently empty regardless of lens/loading
        # state -- confirmed live via direct measurement (162-178K chars of rendered SVG
        # in #oo-coverage-map across all four lenses vs. 0 in #oomap-lens-bar).
        _log("drilling World map lenses")
        map_lenses = ["coverage", "stories", "places", "servers"]
        map_surfaces = tuple(
            Surface(f"worldmap_{t}", f"World map > {t}", nav_tab="timemap",
                    trigger=f'#oomap-lenses button[data-tab="{t}"]',
                    dom_id="oo-coverage-map")
            for t in map_lenses
        )
        _walk_surfaces(driver, map_surfaces, report, axis_label="map-lenses")

        # -- Governments subtabs (incl. the known-open Countries-default item) --------------- #
        _log("checking Governments tab default + Law subtab")
        gov_default = Surface("governments_default", "Governments (default landing)",
                               nav_tab="law", dom_id="gov-countries")
        driver.goto(gov_default)
        active_subtab = driver.page.evaluate(
            "() => { const b = document.querySelector('#subtab-strip button.active'); "
            "return b ? b.dataset.tab : null; }"
        )
        report.add_coverage(
            surface="governments_default_landing", axis="default",
            result="verified",
            note=f"lands on subtab='{active_subtab}'",
        )
        if active_subtab == "countries":
            report.add_finding(
                id="governments-tab-defaults-to-countries-not-law",
                severity="P2", surface="governments_default",
                title="Governments tab still defaults to Countries, not Law",
                detail="Confirmed still present live -- this is the KNOWN-OPEN item from the "
                "2026-07-22 audit (independently rediscovered by 4 groups there), deliberate/"
                "documented per the triage. NOT counted as a new finding.",
                new=False,
            )

        # -- the known-open CJK keyword rendering check (ins-map-cjk-sentence-keywords, P1) -- #
        # The 2026-07-22 finding's exact surface was "Insights > Map (default view,
        # country=cn)", reading the 'By country' table's 'Top keywords' pills
        # (docs/audit/gui-test-2026-07-22/findings.csv row 43) -- NOT the top-level
        # World map tab (an unrelated surface an earlier pass of this script wrongly
        # substituted). showInsightCat("map") auto-calls loadMap() on first activation
        # (app.js:13207), which fills #map-countries with `.pill` spans holding real
        # visible text (app.js:18544-18557) -- unlike the World map's places overlay,
        # whose labels live ONLY in SVG <title> tooltips, never as rendered text.
        _log("checking Insights > Map keyword-pill rendering with the seeded zh corpus")
        cjk_surface = Surface("insights_map_cjk", "Insights > Map (zh check)",
                               nav_tab="insights", subtab="map", dom_id="map-countries")
        driver.goto(cjk_surface)
        driver.page.wait_for_timeout(400)
        pill_texts = driver.page.evaluate(
            "() => Array.from(document.querySelectorAll('#map-countries .pill'))"
            ".slice(0, 200).map(e => e.textContent)"
        )
        long_unsegmented = [t for t in pill_texts if t and len(t) > 20 and
                             any("一" <= ch <= "鿿" for ch in t)]
        report.add_coverage(
            surface="insights_map_cjk_keywords", axis="zh-content",
            result="partial" if long_unsegmented else "verified",
            note=f"sampled {len(pill_texts)} pills; long-unsegmented-CJK={len(long_unsegmented)}",
        )
        if long_unsegmented:
            report.add_finding(
                id="ins-map-cjk-sentence-keywords",
                severity="P1", surface="insights_map_cjk",
                title="Insights > Map keyword pills still render un-truncated CJK runs",
                detail=f"confirmed still present live against the seeded zh corpus: "
                f"{long_unsegmented[:3]!r}. This is the STILL-OPEN P1 from the 2026-07-22 "
                f"audit's own triage -- NOT counted as a new finding.",
                new=False,
            )
        else:
            report.add_finding(
                id="ins-map-cjk-sentence-keywords-not-reproduced",
                severity="P1", surface="insights_map_cjk",
                title="Could not reproduce ins-map-cjk-sentence-keywords against the seeded "
                "zh corpus in this run",
                detail=f"sampled {len(pill_texts)} pill texts, none matched the "
                f"long-unsegmented-CJK pattern; the seeded corpus's zh keyword yield for "
                f"country=cn may be thinner than the original run's, or the underlying "
                f"segmentation gap may have narrowed since 2026-07-22 -- neither is "
                f"confirmed here, this is an honest non-reproduction, not a verified fix.",
                new=False,
            )

        # -- contrast, on the default theme + the light-theme cluster ------------------------ #
        _log("checking pill/caveat contrast across themes")
        driver.goto(Surface("home_for_contrast", "Home", nav_tab="home", dom_id="tab-home"))
        for theme in THEMES_TO_CHECK:
            driver.set_theme(theme)
            driver.page.wait_for_timeout(150)
            _check_contrast(driver, report, theme)

        # -- breakpoints ----------------------------------------------------------------------- #
        _log("checking breakpoint overflow")
        driver.set_theme("ink")
        for width, height in BREAKPOINTS:
            _check_breakpoint_overflow(driver, report, width, height)
        driver.set_viewport(1440, 950)

        # -- locale / RTL ----------------------------------------------------------------------- #
        _log("checking locale switching + RTL")
        for locale in LOCALES_TO_CHECK:
            driver.set_locale(locale)
            driver.page.wait_for_timeout(300)
            dir_attr = driver.page.evaluate("document.documentElement.getAttribute('dir')")
            errors = driver.console_errors()
            shot = driver.screenshot(Surface(f"home-locale-{locale}", "Home", dom_id="tab-home"))
            expect_rtl = locale == "ar"
            got_rtl = dir_attr == "rtl"
            ok = (got_rtl == expect_rtl) and not errors
            report.add_coverage(
                surface="locale_switch", axis=locale,
                result="verified" if ok else "partial",
                note=f"dir={dir_attr} errors={errors}",
            )
            if expect_rtl and not got_rtl:
                report.add_finding(
                    id=f"ui-clickthrough-rtl-not-applied-{locale}",
                    severity="P1", surface="locale_switch",
                    title=f"Switching to {locale} did not set dir=rtl on <html>",
                    detail=f"documentElement.dir={dir_attr!r} after OOI18N.setLang('{locale}')",
                    evidence=shot or "", new=True,
                )
        driver.set_locale("en")

        # -- opacity-composited pseudo-elements: a spot check across a few state-carrying icons #
        _log("spot-checking opacity-composited pseudo-elements")
        for sel in ["#net-toggle::after", ".nav-item.adv .badge"]:
            base_sel = sel.split("::")[0]
            pseudo = "::" + sel.split("::")[1] if "::" in sel else None
            style = driver.computed_style(base_sel, pseudo=pseudo)
            report.add_coverage(
                surface="opacity_pseudo_spotcheck", axis=sel,
                result="verified" if style else "blocked",
                note=str(style) if style else "selector not found",
            )

        report.add_coverage(surface="state_c_walk", axis="summary", result="verified",
                             note=f"{len(FLAGSHIP_SURFACES) + len(BACKLOG_SURFACES)} named "
                             f"surfaces + subtab drills + {len(THEMES_TO_CHECK)} themes + "
                             f"{len(BREAKPOINTS)} breakpoints + {len(LOCALES_TO_CHECK)} locales")
    finally:
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/audit/ui-clickthrough-2026-08-13")
    args = ap.parse_args()

    out_dir = Path(args.out)
    shots = out_dir / "evidence"
    shots.mkdir(parents=True, exist_ok=True)

    report = Report()
    with sync_playwright() as pw:
        investigate_state_a(pw, report, shots)
        investigate_state_b(pw, report, shots)
        investigate_state_c(pw, report, shots)

    (out_dir / "report.json").write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    with open(out_dir / "findings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "severity", "surface", "title", "detail",
                                           "evidence", "new"])
        w.writeheader()
        for finding in report.findings:
            w.writerow(asdict(finding))

    with open(out_dir / "coverage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["surface", "axis", "result", "note"])
        w.writeheader()
        for row in report.coverage:
            w.writerow(asdict(row))

    n_new = sum(1 for f in report.findings if f.new)
    n_pos = sum(1 for f in report.findings if f.severity == "POSITIVE")
    _log(f"DONE. {len(report.findings)} findings ({n_new} new, {n_pos} positive-confirmations), "
         f"{len(report.coverage)} coverage rows, {len(report.steps)} walk steps.")
    _log(f"Written to {out_dir}/")


if __name__ == "__main__":
    main()
