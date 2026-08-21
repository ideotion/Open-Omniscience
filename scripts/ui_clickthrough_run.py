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
import re
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
# STATE D (2026-08-20 matrix session, T2): a FRESH instance the import drill runs against —
# the post-import screen's CONTENT path needs a real import to render, and importing into
# state C mid-walk would mutate the corpus every other check depends on. The artifact is
# built beforehand by the app's OWN volume-backup engine over the --mini seed corpus
# (scripts/ui_clickthrough_seed.py --mini + src.backup.artifact.write_volume_backup); its
# folder + passphrase arrive via env so the runner never hardcodes a machine path.
STATE_D_URL = "http://127.0.0.1:8003"
IMPORT_ARTIFACT_DIR = os.environ.get("OO_UIWALK_IMPORT_ARTIFACT", "")
IMPORT_ARTIFACT_PASS = os.environ.get("OO_UIWALK_IMPORT_PASS", "")

# All 17 concrete themes (2026-08-20, T4 — the 2026-08-13 run sampled 5 of the stated >=9
# floor; the contrast checks are cheap, so the full set runs; "system" follows the OS and
# resolves to one of these, so it is not a separate palette to measure).
THEMES_TO_CHECK = [
    "ink", "slate", "midnight", "arctic", "cyber", "forest", "aubergine", "garnet",
    "solar", "sepia", "terminal", "contrast", "light", "mist", "dawn", "mint", "paper",
]
LOCALES_TO_CHECK = ["en", "fr", "ar", "zh"]  # the brief's own stated minimum (2026-08-13 brief §6)
# The five locales where text-transform:uppercase is a NO-OP (the recorded panel-h2
# lesson) — the T7 uppercase-reliance audit runs across exactly these.
UPPERCASE_NOOP_LOCALES = ["ar", "zh", "ja", "hi", "bn"]
BREAKPOINTS = [(375, 900), (768, 1000), (1024, 900), (1440, 950)]

AXE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "vendor" / "axe-core" / "axe.min.js"
LOCALES_DIR = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"


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


def _wait_for_server(url: str, *, timeout_s: float = 20.0) -> bool:
    # A bounded HTTP readiness poll before driving a state. Found live 2026-08-13: launching
    # all three uvicorn instances nearly simultaneously (the normal setup shape for this
    # script's own three states) can leave one still mid-startup (catalog seeding, DB init)
    # when a walk immediately navigates to it -- the server answers something, but the SPA's
    # own client-side view-toggle JS (unlock.html's language -> legal -> create sequence) can
    # race that startup work and read as not-yet-visible at the walk's fixed settle timeouts.
    # Isolated re-verification against a WARM, already-launched state A (same code, same
    # server, no other concurrent launches) reproduced ZERO of that flakiness -- 100% verified
    # on every step -- confirming this is a harness readiness gap, not an app defect. A plain
    # HTTP poll (never a browser navigation) is cheap and keeps this mechanical/safe per the
    # fix policy; it does not touch the app itself.
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


# ------------------------------------------------------------------------------------------ #
# STATE A -- virgin (first-launch lifecycle)
# ------------------------------------------------------------------------------------------ #
def investigate_state_a(pw, report: Report, shots: Path) -> None:
    _log("STATE A (virgin, first-launch lifecycle) -- " + STATE_A_URL)
    browser = pw.chromium.launch(executable_path=_chromium_path())
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(STATE_A_URL + "/", wait_until="domcontentloaded")
        # A bounded wait for the client-side view-toggle JS to settle on ITS first view,
        # rather than a fixed sleep -- found live 2026-08-13: under contention from other
        # concurrently-launched app instances, a fixed 300ms could fire before unlock.html's
        # own init script had finished picking between view-language/view-legal/view-create/
        # view-unlock, reading a real (later-visible) view as absent. `:visible` here is
        # Playwright's own extension, not a bare CSS selector -- it excludes `.hidden`
        # elements by construction, so this never forces a view open early, it only waits
        # for whichever one the app itself is about to show.
        with contextlib.suppress(Exception):
            page.wait_for_selector(
                "#view-language:visible, #view-legal:visible, #view-create:visible, "
                "#view-unlock:visible, #view-open:visible",
                timeout=5000,
            )
        page.wait_for_timeout(150)
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
            with contextlib.suppress(Exception):
                page.wait_for_selector("#view-legal:visible", timeout=3000)
            page.wait_for_timeout(150)

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
                with contextlib.suppress(Exception):
                    page.wait_for_selector("#view-create:visible", timeout=3000)
                page.wait_for_timeout(150)

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
            # Wait for the SPA's first real Home render, bounded — the first full-matrix
            # run read body text at 689 chars (mid-first-render) and filed a P2 for an
            # empty-state message that WAS there 2s later (live-confirmed 2026-08-20:
            # 2602 chars with "No Leads yet — that's expected on a young corpus"). The
            # recorded harness rule: wait on content, never a fixed sleep.
            with contextlib.suppress(Exception):
                page.wait_for_function(
                    "() => (document.body.innerText || '').length > 1500", timeout=15000,
                )
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
    live confirmation the source-only triage could not provide.

    The warn-pill selector EXCLUDES #llm: the AI pill carries `pill warn` classes but its
    state rules override the colour per state (`#llm.ai-off -> var(--err)`-family), so a bare
    `.pill.warn` querySelector grabs the pill FIRST and measures the STATE colour while the
    finding id names the --warn-fg token -- the first full-matrix run filed exactly that
    lookalike (a "pill.warn fails on solar" P1 whose fg was solar's --err). The pill's own
    state label is a real, separate claim and gets its own check below, against the pill's
    OWN opaque tinted background (never the .panel fallback -- the pill does not sit on a
    panel)."""
    for sel, label in [(".pill.warn:not(#llm)", "pill.warn"), (".card-caveat", "card-caveat")]:
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
    # -- the AI pill's own state label, measured as itself (its background is the rule's
    # opaque 8%-err tint, so the element's own computed backgroundColor is the true ground)
    style = driver.computed_style("#llm.ai-off")
    if style and style.get("color") and style.get("backgroundColor"):
        fg = _parse_rgb(style["color"])
        bg = _parse_rgb(style["backgroundColor"])
        if fg and bg:
            ratio = _contrast_ratio(fg, bg)
            report.add_coverage(
                surface="contrast_ai-pill-off-label", axis=f"theme={theme}",
                result="verified" if ratio >= 4.5 else "partial",
                note=f"ratio={ratio:.2f}:1 fg={fg} bg={bg}",
            )
            if ratio < 4.5:
                report.add_finding(
                    id=f"ui-clickthrough-contrast-ai-pill-off-{theme}",
                    severity="P2", surface="ai_pill",
                    title=f"The AI pill's ai-off label fails AA on theme '{theme}' "
                    f"({ratio:.2f}:1) — state stays carried by the bar + title",
                    detail=f"computed fg={fg} bg={bg}", new=True,
                )


def _check_breakpoint_overflow(driver: PlaywrightUiWalkDriver, report: Report,
                                width: int, height: int, *, surface_label: str = "",
                                force_activity: bool = True) -> None:
    # 2026-08-20 (T1): the 375px overflow's real mechanism was the status CLUSTER's
    # nowrap min-content, present exactly WHILE THE ACTIVITY CHIP IS VISIBLE — an idle
    # page read clean, which is why the 2026-08-13 measurement looked like a bar-wide
    # cumulative overflow and why any breakpoint check that races the chip's visibility
    # is a coin flip. The chip is forced visible via ITS OWN toggle attribute (the exact
    # DOM state the app produces during an in-flight fetch), so the WORST case is what
    # gets measured, deterministically. Recorded in the coverage note, never silently.
    driver.set_viewport(width, height)
    if force_activity:
        driver.page.evaluate(
            "() => { const a = document.getElementById('activity'); if (a) a.hidden = false; }"
        )
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
    surface_id = f"topbar_overflow{('_' + surface_label) if surface_label else ''}"
    report.add_coverage(
        surface=surface_id, axis=f"{width}x{height}",
        result="verified" if not overflow and not controls_offscreen else "partial",
        note=f"scrollWidth={metrics['scrollWidth']} clientWidth={metrics['clientWidth']} "
        f"offscreen={controls_offscreen}"
        + (" (activity chip forced visible via its own toggle attribute)" if force_activity else ""),
    )
    suffix = f"-{surface_label}" if surface_label else ""
    if overflow or controls_offscreen:
        report.add_finding(
            id=f"ui-clickthrough-topbar-overflow-{width}{suffix}",
            severity="P1", surface="topbar",
            title=f"Page overflow / off-screen controls at {width}px{' on ' + surface_label if surface_label else ''}",
            detail=f"scrollWidth={metrics['scrollWidth']} vs clientWidth={metrics['clientWidth']}, "
            f"offscreen controls: {controls_offscreen}",
            new=True,
        )
    else:
        report.add_finding(
            id=f"ui-clickthrough-topbar-fixed-{width}{suffix}",
            severity="POSITIVE", surface="topbar",
            title=f"No page overflow and all core controls on-screen at {width}px"
            + (f" on {surface_label}" if surface_label else ""),
            detail="the T1 phone-top-bar collapse verified live (activity chip forced "
            "visible — the measured worst case).",
            new=False,
        )


# ------------------------------------------------------------------------------------------ #
# 2026-08-20 matrix additions (T2/T3/T5/T6/T7): the drills below extend the standing runner.
# Every drill degrades to an honest partial/blocked coverage row rather than aborting the walk,
# and none fabricates a pass for a state this sandbox cannot reach (no GPU, no LLM backend, no
# egress -- airplane mode stays engaged throughout).
# ------------------------------------------------------------------------------------------ #

def _get_json(url: str, *, attempts: int = 6):
    """Loopback JSON GET with a bounded 429 retry. The first full-matrix run's reader
    drill was BLOCKED by a single `HTTP Error 429: Too Many Requests` — this harness's
    own browser polls the same single-instance server (the app's slowapi limits are a
    feature under test, not noise), so a sidecar API probe racing them is expected to
    hit the limiter occasionally and must wait it out rather than report a blocked
    surface. Bounded (never a poll loop); anything but a 429 raises immediately."""
    import json as _json
    import urllib.error
    import urllib.request

    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - loopback only
                return _json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and i < attempts - 1:
                time.sleep(2.0)
                continue
            raise
    raise RuntimeError("unreachable")


def drill_reader(driver: PlaywrightUiWalkDriver, report: Report, shots: Path) -> int | None:
    """T3: the Reader — the 2026-08-13 report's single largest named-surface gap. A
    standalone server-rendered page (never the SPA), reached via the url grammar with an
    article id discovered from the corpus under test. Returns that id (the a11y pass
    reuses it) or None when discovery/rendering blocked."""
    from src.monitoring.ui_walk import reader_surface

    _log("T3: drilling the Reader (standalone page)")
    # Discover an article id from the PAGE first: the walk's own browser has been polling
    # this single-instance server for minutes, so a sidecar API GET can meet the app's
    # rate limiter mid-window even with the bounded _get_json retry (both callers share
    # 127.0.0.1 — the second full-matrix run lost the whole reader drill to one 429 that
    # outlived a 12s backoff). A reader link already rendered in the DOM costs zero
    # requests and is the same href a real user clicks.
    article_id = None
    try:
        driver.goto(Surface("reader_discovery", "Analysis > articles", nav_tab="analyze",
                            subtab="articles", dom_id="an-articles"))
        driver.page.wait_for_timeout(800)
        href = driver.page.evaluate(
            "() => { const a = document.querySelector('a[href*=\"/api/articles/\"]'); "
            "return a ? a.getAttribute('href') : null; }"
        )
        if href:
            import re as _re
            m = _re.search(r"/api/articles/(\d+)/", href)
            if m:
                article_id = int(m.group(1))
    except Exception:  # noqa: BLE001, S110 - the API fallback below reports the failure
        pass
    if article_id is None:
        try:
            art = _get_json(STATE_C_URL + "/api/articles?limit=1")["results"][0]
            article_id = art["id"]
        except Exception as exc:  # noqa: BLE001
            report.add_coverage(surface="reader", axis="default", result="blocked",
                                note=f"could not discover an article id: {exc}")
            return None
    surface = reader_surface(article_id)
    driver.goto(surface)
    visible = driver.is_visible(surface.dom_id)
    errors = driver.console_errors()
    shot = driver.screenshot(surface)
    report.add_coverage(
        surface="reader", axis="default",
        result="verified" if visible and not errors else "partial",
        note=f"article_id={article_id} visible={visible} errors={errors}",
    )
    if not (visible and not errors):
        report.add_finding(
            id="ui-clickthrough-reader-default-fail", severity="P1", surface="reader",
            title="The Reader's Read pane did not render", detail=f"visible={visible}, errors={errors}",
            evidence=shot or "", new=True,
        )
        return article_id
    # -- the two-class provenance groups (the informed-consent headings) ---------------- --- #
    groups = driver.page.evaluate(
        "() => Array.from(document.querySelectorAll('.mgrp h3')).map(h => h.textContent.trim())"
    )
    has_source = any("From the source" in g for g in groups)
    has_deduced = any("Deduced by this app" in g for g in groups)
    has_ai = any("AI-derived" in g for g in groups)
    report.add_coverage(
        surface="reader", axis="provenance-classes",
        result="verified" if has_source and has_deduced else "partial",
        note=f"groups={groups!r} (the AI-derived third class renders only when ai_keyword rows "
        f"exist for the article; absent here = honest, not a defect: present={has_ai})",
    )
    # -- every tab, individually -------------------------------------------------------- --- #
    tabs = driver.page.evaluate(
        "() => Array.from(document.querySelectorAll('.rtab')).map(b => b.dataset.rtab)"
    )
    for tab in tabs:
        try:
            driver.page.click(f'.rtab[data-rtab="{tab}"]')
            pane = f"rp-{tab}"
            with contextlib.suppress(Exception):
                driver.page.wait_for_function(
                    "id => { const el = document.getElementById(id); "
                    "return !!(el && !el.hidden && el.innerHTML.trim().length > 0); }",
                    arg=pane, timeout=4000,
                )
            pane_visible = driver.is_visible(pane)
            text = driver.page.evaluate(
                "(id) => { const el = document.getElementById(id); "
                "return el ? el.innerText.trim().slice(0, 60) : ''; }", pane,
            )
            errs = driver.console_errors()
            report.add_coverage(
                surface="reader", axis=f"tab-{tab}",
                result="verified" if pane_visible and not errs else "partial",
                note=f"pane visible={pane_visible} errors={errs} first-words={text!r}",
            )
        except Exception as exc:  # noqa: BLE001
            report.add_coverage(surface="reader", axis=f"tab-{tab}", result="partial",
                                note=f"{type(exc).__name__}: {exc}")
    # Loaded-language is the brief-named pane (data-rtab=subjectivity) — call it out.
    if "subjectivity" in tabs:
        report.add_finding(
            id="ui-clickthrough-reader-covered", severity="POSITIVE", surface="reader",
            title="The Reader (tabs, provenance classes, Loaded-language) is now walked — "
            "the 2026-08-13 report's largest named-surface gap closes",
            detail=f"{len(tabs)} tabs drilled individually; the two-class provenance headings "
            "render; the Loaded-language pane renders.",
            evidence=shot or "", new=True,
        )
    return article_id


def drill_worldmap_lens_controls(driver: PlaywrightUiWalkDriver, report: Report) -> None:
    """T5a: the World map's IN-PANEL sub-controls, one level below the 4 lenses the
    2026-08-13 run walked — dimension picker, granularity, Places overlay, Signals layer +
    its focus slider. The controls live inside the map host (never #subtab-strip)."""
    _log("T5a: drilling World-map in-panel lens sub-controls")
    driver.goto(Surface("worldmap_for_controls", "World map", nav_tab="timemap",
                        dom_id="oo-coverage-map"))
    with contextlib.suppress(Exception):
        driver.page.wait_for_function(
            "() => { const el = document.getElementById('oo-coverage-map'); "
            "return !!(el && el.innerHTML.length > 1000); }", timeout=8000,
        )
    page = driver.page

    def _map_len() -> int:
        return page.evaluate(
            "() => (document.getElementById('oo-coverage-map') || {innerHTML:''}).innerHTML.length"
        )

    # dimension picker (present when >1 dimensions -- the coverage lens)
    dims = page.evaluate(
        "() => Array.from(document.querySelectorAll('[data-oomap-dim]'))"
        ".map(b => b.dataset.oomapDim)"
    )
    for dim in dims:
        before = _map_len()
        try:
            page.click(f'[data-oomap-dim="{dim}"]:visible')
            page.wait_for_timeout(500)
            after = _map_len()
            errs = driver.console_errors()
            report.add_coverage(
                surface="worldmap_controls", axis=f"dimension-{dim}",
                result="verified" if after > 0 and not errs else "partial",
                note=f"map innerHTML {before}->{after} errors={errs}",
            )
        except Exception as exc:  # noqa: BLE001
            report.add_coverage(surface="worldmap_controls", axis=f"dimension-{dim}",
                                result="partial", note=str(exc)[:120])
    if not dims:
        report.add_coverage(surface="worldmap_controls", axis="dimension-picker",
                            result="blocked", note="no [data-oomap-dim] buttons rendered")
    # granularity: continent then back to country
    for gran in ("continent", "country"):
        try:
            page.click(f'[data-oomap-gran="{gran}"]:visible')
            page.wait_for_timeout(400)
            pressed = page.evaluate(
                f"() => {{ const b = document.querySelector('[data-oomap-gran=\"{gran}\"]');"
                f" return b ? b.getAttribute('aria-pressed') : null; }}"
            )
            report.add_coverage(
                surface="worldmap_controls", axis=f"granularity-{gran}",
                result="verified" if pressed == "true" else "partial",
                note=f"aria-pressed={pressed} map_len={_map_len()}",
            )
        except Exception as exc:  # noqa: BLE001
            report.add_coverage(surface="worldmap_controls", axis=f"granularity-{gran}",
                                result="partial", note=str(exc)[:120])
    # Places overlay: the deduced-places caveat must ARRIVE with the layer (informed consent)
    try:
        page.click("[data-oomap-places]:visible")
        page.wait_for_timeout(700)
        tab_text = page.evaluate("() => document.getElementById('tab-timemap').innerText")
        caveat_on = ("never confirmed" in tab_text) or ("deduced" in tab_text.lower())
        report.add_coverage(
            surface="worldmap_controls", axis="places-overlay",
            result="verified" if caveat_on else "partial",
            note=f"deduced-places caveat visible with the layer: {caveat_on}",
        )
        page.click("[data-oomap-places]:visible")  # toggle back off
        page.wait_for_timeout(300)
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="worldmap_controls", axis="places-overlay",
                            result="partial", note=str(exc)[:120])
    # Signals layer + the in-map focus slider, driven by KEYBOARD (the real user path --
    # setting .value from script would bypass the app's own input handling)
    try:
        page.click("[data-oomap-signals]:visible")
        page.wait_for_timeout(700)
        slider_present = bool(page.locator("[data-oomap-focus]:visible").count())
        report.add_coverage(
            surface="worldmap_controls", axis="signals-layer",
            result="verified" if slider_present else "partial",
            note=f"focus slider rendered with the layer: {slider_present}",
        )
        if slider_present:
            before = _map_len()
            page.focus("[data-oomap-focus]")
            for _ in range(5):
                page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(500)
            errs = driver.console_errors()
            report.add_coverage(
                surface="worldmap_controls", axis="signals-focus-slider",
                result="verified" if not errs else "partial",
                note=f"5x ArrowLeft on the slider; map innerHTML {before}->{_map_len()} "
                f"errors={errs}",
            )
        page.click("[data-oomap-signals]:visible")
        page.wait_for_timeout(300)
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="worldmap_controls", axis="signals-layer",
                            result="partial", note=str(exc)[:120])


def drill_task_manager_panels(driver: PlaywrightUiWalkDriver, report: Report) -> None:
    """T5c: the standalone task manager's sub-panels, each individually. The 2026-08-13
    report's §8 names four (Active/Queue/System/Schedule) from the ledger's own wording;
    the CURRENT page carries five (#tm-tabs data-panel: processes/performance/queue/
    schedule/history) — the anchor is followed, the rename recorded, never re-litigated."""
    _log("T5c: drilling the task manager's sub-panels")
    driver.goto(Surface("task_manager_panels", "Task manager", url="/tasks", dom_id="tm-tabs"))
    page = driver.page
    panels = page.evaluate(
        "() => Array.from(document.querySelectorAll('#tm-tabs button[data-panel]'))"
        ".map(b => b.dataset.panel)"
    )
    report.add_coverage(
        surface="task_manager", axis="panel-inventory",
        result="verified",
        note=f"current panels={panels!r} (the ledger's Active/Queue/System/Schedule naming "
        "predates the current page; anchors followed, rename recorded)",
    )
    for panel in panels:
        try:
            page.click(f'#tm-tabs button[data-panel="{panel}"]')
            page.wait_for_timeout(500)
            visible = page.evaluate(
                f"() => {{ const p = document.getElementById('p-{panel}'); "
                f"return !!(p && !p.hidden && p.offsetHeight >= 0); }}"
            )
            others_hidden = page.evaluate(
                f"() => Array.from(document.querySelectorAll('.tm-panel'))"
                f".filter(p => p.id !== 'p-{panel}').every(p => p.hidden)"
            )
            text = page.evaluate(
                f"() => {{ const p = document.getElementById('p-{panel}'); "
                f"return p ? p.innerText.trim().slice(0, 60) : ''; }}"
            )
            report.add_coverage(
                surface="task_manager", axis=f"panel-{panel}",
                result="verified" if visible and others_hidden else "partial",
                note=f"visible={visible} others_hidden={others_hidden} first-words={text!r}",
            )
        except Exception as exc:  # noqa: BLE001
            report.add_coverage(surface="task_manager", axis=f"panel-{panel}",
                                result="partial", note=str(exc)[:120])


def drill_settings_ai_pill(driver: PlaywrightUiWalkDriver, report: Report) -> None:
    """T5b: the AI pill's states + the Settings->AI backend/roster panels. On this GPU-less,
    backend-less sandbox the pill's real state is ai-off — the ai-starting and serving
    states are honestly BLOCKED (forcing the class would fabricate a state the machine
    never reached). What IS verifiable live: the ai-off diagonal bar actually renders
    (the 2026-08-12 ::after inheritance-leak fix — full-pill inset, gradient background),
    and which roster/install panel the machine draws (the 2026-08-09 panel-ordering
    lesson: only the SERVING backend's panel, with its honest prerequisite line)."""
    _log("T5b: drilling the AI pill + Settings AI panels")
    page = driver.page
    # Wait (bounded) for the pill's state class to be PAINTED before classifying: the
    # SPA sets ai-off/ai-starting only once its AI status poll answers, so a bare
    # "pill warn" read too early is UNPAINTED, not "serving" — the second full-matrix
    # run's else-branch filed exactly that misread ("serving" on a backend-less
    # sandbox), which is the `.get(key, 0)` family: a default standing in for a state
    # nobody established.
    # The painted vocab (app.js paintAiPill): "pill ai-starting" | "pill ok ai-busy" |
    # "pill ok" (serving idle — NO ai- class) | "pill warn ai-off". The static markup's
    # initial "pill warn" carries none of those, which is what the wait discriminates.
    with contextlib.suppress(Exception):
        page.wait_for_function(
            "() => /(ai-off|ai-starting|ai-busy|\\bok\\b)/"
            ".test(document.getElementById('llm').className)",
            timeout=12000,
        )
    pill_classes = page.evaluate("() => document.getElementById('llm').className")
    if not re.search(r"ai-off|ai-starting|ai-busy|\bok\b", pill_classes):
        # Still the static initial: the SPA reads /api/llm/health ONCE at boot and never
        # retries, so when THIS WALK's own request storm 429s that one call the pill
        # stays unpainted for the page's whole life (a fresh page paints ai-off in ~2s —
        # verified live). Nudge via the SPA's OWN entry point (loadLlmHealth — the exact
        # function boot calls), which paints whatever the probe REALLY answers; never a
        # class edit (that would fabricate a state).
        with contextlib.suppress(Exception):
            page.evaluate("() => (typeof loadLlmHealth === 'function') && loadLlmHealth()")
            page.wait_for_function(
                "() => /(ai-off|ai-starting|ai-busy|\\bok\\b)/"
                ".test(document.getElementById('llm').className)",
                timeout=8000,
            )
        pill_classes = page.evaluate("() => document.getElementById('llm').className")
    if "ai-off" in pill_classes:
        state = "ai-off"
    elif "ai-starting" in pill_classes:
        state = "ai-starting"
    elif "ai-busy" in pill_classes or re.search(r"\bok\b", pill_classes):
        state = "serving"
    else:
        state = "unpainted"
    report.add_coverage(
        surface="settings_ai_pill", axis="live-state",
        result="verified" if state != "unpainted" else "partial",
        note=f"class={pill_classes!r} -> {state}"
        + ("" if state != "unpainted" else " (the status poll never painted a state "
           "class within 12s — an honest unknown, never read as serving)"),
    )
    if state == "ai-off":
        after = driver.computed_style("#llm.ai-off", pseudo="::after")
        # the decisive numbers: the ::after must span the pill (inset 0 -> width ==
        # pill width), never the 4x4 hover-convention dot it silently inherited before
        # the 2026-08-12 fix.
        pill_w = page.evaluate(
            "() => Math.round(document.getElementById('llm').getBoundingClientRect().width)"
        )
        after_w = (after or {}).get("width", "")
        report.add_coverage(
            surface="settings_ai_pill", axis="ai-off-diagonal-bar",
            result="verified" if after and after_w not in ("4px", "") else "partial",
            note=f"::after width={after_w!r} vs pill width={pill_w}px (pre-fix leak was a "
            f"4px dot); computed={ {k: after.get(k) for k in ('width','height','opacity')} if after else None }",
        )
        if after and after_w == "4px":
            report.add_finding(
                id="ai-pill-diagonal-bar-inheritance-regression", severity="P1",
                surface="settings_ai_pill",
                title="The AI pill's ai-off ::after reads 4px again — the 2026-08-12 "
                "inheritance-leak fix has regressed",
                detail=f"computed ::after={after!r}", new=True,
            )
    for unreachable in ("ai-starting", "serving"):
        if state != unreachable:
            report.add_coverage(
                surface="settings_ai_pill", axis=f"state-{unreachable}",
                result="blocked",
                note="unreachable without a local backend on this sandbox — recorded "
                "honestly, never forced via a class edit (that would fabricate a state)",
            )
    # the Settings > AI panel: which install/roster host renders, and does it name the
    # prerequisite rather than offering a decoy?
    driver.goto(Surface("settings_ai_panels", "Settings > AI", nav_tab="settings",
                        subtab="models", dom_id="set-models"))
    page.wait_for_timeout(1200)
    text = page.evaluate("() => document.getElementById('set-models').innerText.slice(0, 4000)")
    names_prereq = ("install" in text.lower() or "not installed" in text.lower()
                    or "backend" in text.lower())
    report.add_coverage(
        surface="settings_ai_panels", axis="backend-panel",
        result="verified" if names_prereq else "partial",
        note=f"panel names its prerequisite/backend state: {names_prereq} "
        f"(len={len(text)})",
    )


def drill_bulletin(driver: PlaywrightUiWalkDriver, report: Report, shots: Path) -> None:
    """T5d: the Bulletin — its Settings section AND the review screen. On this hardware the
    gate refuses (no dedicated GPU / no Apple Silicon), which is itself the surface under
    test: the refusal must render honestly. The review screen is then reached the REAL way
    an operator on such hardware reaches it — the explicit llm_allow_impractical_hw
    override (a shipped, deliberate control), then a Layer-A generate over the small
    synthetic corpus (deterministic SQL; narration stays off with no backend, which the
    edition's own self-description must reflect). The override is flipped BACK afterwards
    so no later check runs under a mutated setting."""
    _log("T5d: drilling the Bulletin (gate -> override -> generate -> review)")
    page = driver.page
    driver.goto(Surface("bulletin_gate", "Bulletin", nav_tab="settings", subtab="advanced",
                        advanced_section="bulletin", dom_id="bulletin-panel"))
    page.wait_for_timeout(1200)
    gate_text = page.evaluate(
        "() => { const g = document.getElementById('bulletin-gate'); "
        "return g ? g.innerText.trim() : ''; }"
    )
    controls_hidden = page.evaluate(
        "() => { const c = document.getElementById('bulletin-controls'); "
        "return !c || c.hidden; }"
    )
    report.add_coverage(
        surface="bulletin", axis="hardware-gate",
        result="verified" if gate_text else "partial",
        note=f"gate says: {gate_text[:120]!r}; controls hidden={controls_hidden}",
    )
    flipped = False
    try:
        # the REAL override path: the shipped setting, via the same loopback PUT the
        # Settings checkbox performs (the checkbox lives in the async-rendered AI panel;
        # calling the page's OWN setAllowImpracticalHw is the same function it wires).
        page.evaluate("() => setAllowImpracticalHw(true)")
        flipped = True
        page.wait_for_timeout(1200)
        # re-open the bulletin section so the gate re-checks
        driver.goto(Surface("bulletin_gate2", "Bulletin", nav_tab="settings", subtab="advanced",
                            advanced_section="bulletin", dom_id="bulletin-panel"))
        with contextlib.suppress(Exception):
            page.wait_for_function(
                "() => { const c = document.getElementById('bulletin-controls'); "
                "return !!(c && !c.hidden); }", timeout=8000,
            )
        controls_now = not page.evaluate(
            "() => { const c = document.getElementById('bulletin-controls'); "
            "return !c || c.hidden; }"
        )
        report.add_coverage(
            surface="bulletin", axis="override-reveals-controls",
            result="verified" if controls_now else "partial",
            note=f"llm_allow_impractical_hw=true reveals the controls: {controls_now}",
        )
        if controls_now:
            gen_btn = page.locator("#bulletin-controls button", has_text="Generate")
            if not gen_btn.count():
                gen_btn = page.locator("#bulletin-controls button").first
            gen_btn.first.click()
            with contextlib.suppress(Exception):
                page.wait_for_function(
                    "() => { const l = document.getElementById('bulletin-list'); "
                    "return !!(l && l.querySelector('button, a')); }", timeout=60000,
                )
            page.wait_for_timeout(800)
            list_text = page.evaluate(
                "() => (document.getElementById('bulletin-list')||{innerText:''}).innerText.slice(0,200)"
            )
            report.add_coverage(
                surface="bulletin", axis="generate-edition",
                result="verified" if list_text.strip() else "partial",
                note=f"list after generate: {list_text[:100]!r}",
            )
            # open the newest edition's review screen
            opened = False
            for label in ("Review", "Open", "View"):
                btn = page.locator("#bulletin-list button", has_text=label)
                if btn.count():
                    btn.first.click()
                    opened = True
                    break
            if not opened:
                first = page.locator("#bulletin-list button")
                if first.count():
                    first.first.click()
                    opened = True
            with contextlib.suppress(Exception):
                page.wait_for_function(
                    "() => { const r = document.getElementById('bulletin-review'); "
                    "return !!(r && r.innerText.trim().length > 40); }", timeout=15000,
                )
            review_text = page.evaluate(
                "() => (document.getElementById('bulletin-review')||{innerText:''}).innerText"
            )
            shot = driver.screenshot(Surface("bulletin_review", "Bulletin review",
                                             dom_id="bulletin-review"))
            report.add_coverage(
                surface="bulletin", axis="review-screen",
                result="verified" if len(review_text.strip()) > 40 else "partial",
                note=f"review length={len(review_text.strip())} opened={opened}",
            )
            if len(review_text.strip()) > 40:
                report.add_finding(
                    id="ui-clickthrough-bulletin-review-covered", severity="POSITIVE",
                    surface="bulletin",
                    title="The Bulletin review screen renders live for the first time "
                    "(reached via the real override + generate path)",
                    detail="hardware gate refuses honestly on this sandbox; the explicit "
                    "llm_allow_impractical_hw override reveals the controls; a Layer-A "
                    "generate over the synthetic corpus produced an edition whose review "
                    "screen renders per-section content.",
                    evidence=shot or "", new=True,
                )
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="bulletin", axis="review-screen", result="partial",
                            note=f"{type(exc).__name__}: {str(exc)[:120]}")
    finally:
        if flipped:
            with contextlib.suppress(Exception):
                page.evaluate("() => setAllowImpracticalHw(false)")
                page.wait_for_timeout(600)
            report.add_coverage(surface="bulletin", axis="override-restored",
                                result="verified",
                                note="llm_allow_impractical_hw flipped back to false — no "
                                "later check runs under a mutated setting")


def drill_agenda_provenance(driver: PlaywrightUiWalkDriver, report: Report) -> None:
    """T5e: the Agenda's computed glyphs (moons/seasons, each carrying method+accuracy in
    its title) and the deduced-event provenance pills — the seeded corpus carries a
    3-article/2-source future date precisely so this drill has something to exhibit (an
    untested path is not a pass; the specimen was added rather than the check skipped)."""
    _log("T5e: drilling Agenda glyphs + deduced-event provenance")
    page = driver.page
    driver.goto(Surface("agenda_glyphs", "Agenda month", nav_tab="agenda", subtab="month",
                        dom_id="agenda-month"))
    with contextlib.suppress(Exception):
        page.wait_for_function(
            "() => { const m = document.getElementById('agenda-month'); "
            "return !!(m && m.innerHTML.length > 500); }", timeout=8000,
        )
    glyphs = page.evaluate(
        """() => {
          const moons = Array.from(document.querySelectorAll('.ag-moon'));
          const seasons = Array.from(document.querySelectorAll('.ag-season'));
          const titled = (els) => els.filter(e => (e.getAttribute('title') || '').length > 10).length;
          return {moons: moons.length, moons_titled: titled(moons),
                  seasons: seasons.length, seasons_titled: titled(seasons)};
        }"""
    )
    report.add_coverage(
        surface="agenda_glyphs", axis="month-grid",
        result="verified" if glyphs["moons"] > 0 else "partial",
        note=f"{glyphs} (titles carry method+accuracy — the informed-consent hover)",
    )
    # deduced events: the list view renders agRow with the warn pill
    try:
        page.click('#subtab-strip button[data-tab="list"]:visible')
        with contextlib.suppress(Exception):
            page.wait_for_function(
                "() => Array.from(document.querySelectorAll('#agenda-list .pill.warn'))"
                ".some(p => p.textContent.includes('deduced'))", timeout=8000,
            )
        page.wait_for_timeout(400)
        ded = page.evaluate(
            """() => {
              const pills = Array.from(document.querySelectorAll('.pill.warn'))
                .filter(p => p.textContent.includes('deduced'));
              const rows = pills.map(p => (p.closest('div') || {textContent:''}).textContent.slice(0, 80));
              return {n: pills.length, sample: rows.slice(0, 2),
                      titled: pills.filter(p => (p.getAttribute('title')||'').length > 10).length};
            }"""
        )
        report.add_coverage(
            surface="agenda_deduced", axis="list-view-pills",
            result="verified" if ded["n"] > 0 else "partial",
            note=f"deduced-pill n={ded['n']} titled={ded['titled']} sample={ded['sample']!r} "
            "(seeded specimen: 3 articles / 2 sources naming 2026-10-12)",
        )
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="agenda_deduced", axis="list-view-pills",
                            result="partial", note=str(exc)[:120])


def a11y_pass(driver: PlaywrightUiWalkDriver, report: Report, reader_article_id: int | None) -> None:
    """T6: the a11y axis — vendored axe-core over representative surfaces, a keyboard-only
    traversal with focus-visibility read per stop, and the prefers-contrast emulation pass
    (the app.css G-3 block measured live rather than re-read from source)."""
    from src.monitoring.ui_walk import reader_surface

    _log("T6: a11y axis (axe / keyboard / focus / prefers-contrast)")
    axe_source = AXE_PATH.read_text(encoding="utf-8")
    page = driver.page
    axe_surfaces: list[tuple[str, Surface]] = [
        ("home", Surface("axe_home", "Home", nav_tab="home", dom_id="tab-home")),
        ("settings-models", Surface("axe_set", "Settings AI", nav_tab="settings",
                                    subtab="models", dom_id="set-models")),
        ("agenda", Surface("axe_agenda", "Agenda", nav_tab="agenda", subtab="month",
                           dom_id="agenda-month")),
        ("analysis", Surface("axe_an", "Analysis", nav_tab="analyze", dom_id="tab-analyze")),
        ("tasks", Surface("axe_tasks", "Task manager", url="/tasks", dom_id="tm-tabs")),
    ]
    if reader_article_id is not None:
        axe_surfaces.append(("reader", reader_surface(reader_article_id)))
    for label, surface in axe_surfaces:
        try:
            driver.goto(surface)
            page.wait_for_timeout(600)
            result = driver.run_axe(axe_source)
            violations = result.get("violations", [])
            serious = [v for v in violations if v.get("impact") in ("serious", "critical")]
            report.add_coverage(
                surface=f"a11y_axe_{label}", axis="axe-core-4.13",
                result="verified" if not serious else "partial",
                note=f"{len(violations)} violations ({len(serious)} serious/critical): "
                + "; ".join(f"{v['id']}[{v['impact']}]x{v['nodes']}" for v in violations[:8]),
            )
            for v in serious:
                report.add_finding(
                    id=f"a11y-{label}-{v['id']}",
                    severity="P1" if v["impact"] == "critical" else "P2",
                    surface=label,
                    title=f"axe {v['impact']}: {v['id']} on {label} ({v['nodes']} nodes)",
                    detail=f"{v['help']} — targets: {v['targets']!r}",
                    new=True,
                )
        except Exception as exc:  # noqa: BLE001
            report.add_coverage(surface=f"a11y_axe_{label}", axis="axe-core-4.13",
                                result="blocked", note=f"{type(exc).__name__}: {str(exc)[:100]}")
    # -- keyboard-only traversal + focus visibility (home + the reader) ------------------- #
    kb_surfaces = [("home", axe_surfaces[0][1])]
    if reader_article_id is not None:
        kb_surfaces.append(("reader", reader_surface(reader_article_id)))
    for label, surface in kb_surfaces:
        try:
            driver.goto(surface)
            page.wait_for_timeout(400)
            chain = driver.keyboard_traversal(max_tabs=40)
            not_indicated = [c for c in chain
                             if c.get("tag") != "body" and not c.get("focus_indicated")]
            distinct = {f"{c.get('tag')}#{c.get('id')}" for c in chain if c.get("tag") != "body"}
            trapped = len(chain) >= 6 and len(distinct) <= 1
            report.add_coverage(
                surface=f"a11y_keyboard_{label}", axis="tab-traversal",
                result="verified" if not trapped and len(distinct) >= 3 else "partial",
                note=f"{len(chain)} stops, {len(distinct)} distinct, focus-not-indicated="
                f"{len(not_indicated)} "
                f"{[(c.get('tag'), c.get('id') or c.get('cls')) for c in not_indicated[:4]]!r}",
            )
            if not_indicated:
                report.add_finding(
                    id=f"a11y-keyboard-focus-not-indicated-{label}", severity="P2",
                    surface=label,
                    title=f"{len(not_indicated)} keyboard focus stops on {label} carry no "
                    "visible focus indicator",
                    detail="specimens: "
                    f"{[(c.get('tag'), c.get('id'), c.get('cls')) for c in not_indicated[:6]]!r}",
                    new=True,
                )
            if trapped:
                report.add_finding(
                    id=f"a11y-keyboard-trap-{label}", severity="P1", surface=label,
                    title=f"Keyboard focus appears trapped on {label}",
                    detail=f"chain={chain[:6]!r}", new=True,
                )
        except Exception as exc:  # noqa: BLE001
            report.add_coverage(surface=f"a11y_keyboard_{label}", axis="tab-traversal",
                                result="blocked", note=str(exc)[:120])
    # -- prefers-contrast: the G-3 block, measured live under emulation ------------------- #
    try:
        driver.goto(axe_surfaces[0][1])
        page.wait_for_timeout(400)
        probe = """
        () => {
          const hint = document.querySelector('.hint, .muted');
          const icon = document.querySelector('.icon-btn');
          return {
            hint_color: hint ? getComputedStyle(hint).color : null,
            icon_border: icon ? getComputedStyle(icon).borderTopWidth : null,
          };
        }
        """
        base = page.evaluate(probe)
        driver.emulate_contrast("more")
        page.wait_for_timeout(300)
        more = page.evaluate(probe)
        driver.emulate_contrast(None)
        page.wait_for_timeout(200)
        changed = (base.get("hint_color") != more.get("hint_color")) or (
            base.get("icon_border") != more.get("icon_border"))
        report.add_coverage(
            surface="a11y_prefers_contrast", axis="emulated-more",
            result="verified" if changed else "partial",
            note=f"base={base} more={more} — the app.css (prefers-contrast: more) block "
            f"{'applies' if changed else 'did NOT measurably change the probed styles'}",
        )
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="a11y_prefers_contrast", axis="emulated-more",
                            result="blocked", note=str(exc)[:120])


def honesty_checks(driver: PlaywrightUiWalkDriver, report: Report, shots: Path) -> None:
    """T7: the five automatable §5 honesty-rule checks the 2026-08-13 run did not build
    (rules 3/4/6/7/8 of the brief's nine). Rule 5 (an untested path is not a pass) stays a
    discipline the whole report practices; rule 9 (adversarial screenshot critics) is a
    different posture entirely and stays explicitly out of scope."""
    import re as _re

    page = driver.page
    # -- (rule 3) a class with no rule is a lie the markup keeps telling ------------------ #
    _log("T7: class-with-no-rule sweep")
    try:
        union: dict[str, dict] = {}
        for surface in (
            Surface("sweep_home", "Home", nav_tab="home", dom_id="tab-home"),
            Surface("sweep_ins", "Insights", nav_tab="insights", dom_id="tab-insights"),
            Surface("sweep_set", "Settings", nav_tab="settings", subtab="advanced",
                    dom_id="set-advanced"),
            Surface("sweep_agenda", "Agenda", nav_tab="agenda", dom_id="tab-agenda"),
        ):
            driver.goto(surface)
            page.wait_for_timeout(500)
            for row in driver.undefined_classes():
                entry = union.setdefault(row["cls"], {"cls": row["cls"], "count": 0,
                                                      "example": row["example"]})
                entry["count"] = max(entry["count"], row["count"])
        rows = sorted(union.values(), key=lambda r: -r["count"])
        looks_presentational = [r for r in rows if _re.search(
            r"(small|big|large|tiny|bold|dim|mut|color|colour|txt|text|title|head|label|"
            r"note|hint|warn|err|ok|badge|pill|card|panel|row|col|grid|list)", r["cls"])]
        report.add_coverage(
            surface="honesty_class_no_rule", axis="sweep",
            result="verified",
            note=f"{len(rows)} used-but-unstyled class names across 4 surfaces "
            f"({len(looks_presentational)} presentational-looking); top: "
            + ", ".join(f"{r['cls']}x{r['count']}" for r in rows[:12]),
        )
        if looks_presentational:
            report.add_finding(
                id="honesty-class-with-no-rule-candidates", severity="P2", surface="app-wide",
                title=f"{len(looks_presentational)} used-but-unstyled class names LOOK "
                "presentational — triage candidates, not verdicts",
                detail="a class with no rule reads as styled in the markup (the recorded "
                'class="small" lesson); candidates: '
                + ", ".join(f"{r['cls']}x{r['count']} {r['example']}"
                            for r in looks_presentational[:15])
                + " — most unstyled names are legitimate JS/state hooks; each candidate "
                "needs a human read before any rule is added.",
                new=True,
            )
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="honesty_class_no_rule", axis="sweep",
                            result="blocked", note=str(exc)[:120])

    # -- (rule 4) greyscale, captured MID-interaction ------------------------------------- #
    # The recorded lesson: a greyscale screenshot captured after the interaction ended
    # tests nothing. The subject is the analysis Trend chart's drag interaction — the
    # capture happens while the mouse button is DOWN, and the judgment is PIXEL-level
    # (the band is canvas-drawn, invisible to any DOM query): band-region luminance vs
    # outside-region, against a null baseline of two outside regions.
    _log("T7: greyscale mid-interaction capture (the brush band, Insights explore chart)")
    try:
        # The ONE live brush-enabled chart is Insights explore's per-term trend
        # (#ins-trend-oo — the only ooChart caller passing opts.onSelectRange), and the
        # band draws only in brush MODE (the in-chart "Select a period" chip; a bare
        # drag PANS, per invariant #16). The second full-matrix run pointed this check
        # at the ANALYSIS trend with an empty query — no term, no canvas, and no brush
        # even with one. Reach the real thing: a top term via pickTerm (the exact
        # function every term link calls), the chip, then drag.
        term = ""
        with contextlib.suppress(Exception):
            top = _get_json(STATE_C_URL + "/api/insights/top?limit=1")
            terms = top.get("terms", top) if isinstance(top, dict) else top
            if terms:
                term = terms[0].get("term", "")
        driver.goto(Surface("grey_trend", "Insights", nav_tab="insights",
                            subtab="trends", dom_id="ins-trends"))
        if term:
            page.evaluate(
                "(t) => { if (typeof pickTerm === 'function') pickTerm(t); }", term)
        with contextlib.suppress(Exception):
            page.wait_for_function(
                "() => !!document.querySelector('#ins-trend-oo canvas')", timeout=10000)
        page.wait_for_timeout(600)
        box = page.evaluate(
            "() => { const c = document.querySelector('#ins-trend-oo canvas'); "
            "if (!c) return null; const r = c.getBoundingClientRect(); "
            "return {x: r.left, y: r.top, w: r.width, h: r.height}; }"
        )
        if not box or box["w"] < 100:
            report.add_coverage(surface="honesty_greyscale_middrag", axis="ins-trend-brush",
                                result="blocked",
                                note=f"no usable brush chart canvas (term={term!r}): {box}")
        else:
            # arm brush mode via its own visible chip (the real affordance)
            chip = page.locator("#ins-trend-oo button.chip", has_text="Select a period")
            if chip.count():
                chip.first.click()
                page.wait_for_timeout(150)
            page.evaluate("document.documentElement.style.filter = 'grayscale(1)'")
            y = box["y"] + box["h"] * 0.5
            x1, x2 = box["x"] + box["w"] * 0.30, box["x"] + box["w"] * 0.60
            page.mouse.move(x1, y)
            page.mouse.down()
            for i in range(1, 9):
                page.mouse.move(x1 + (x2 - x1) * i / 8, y)
                page.wait_for_timeout(30)
            shot_path = shots / "greyscale-middrag-brush.png"
            page.screenshot(path=str(shot_path))
            # release back at the start: a zero-width selection must not navigate away
            page.mouse.move(x1, y)
            page.mouse.up()
            page.evaluate("document.documentElement.style.filter = ''")
            from PIL import Image
            img = Image.open(shot_path).convert("L")
            scale = img.width / page.viewport_size["width"]

            def region_mean(cx1: float, cx2: float) -> float:
                px1, px2 = int(cx1 * scale), int(cx2 * scale)
                py1 = int((box["y"] + box["h"] * 0.30) * scale)
                py2 = int((box["y"] + box["h"] * 0.70) * scale)
                crop = img.crop((px1, py1, px2, py2))
                hist = crop.histogram()
                total = sum(hist)
                return sum(i * n for i, n in enumerate(hist)) / max(total, 1)

            band = region_mean(x1 + 8, x2 - 8)
            left_out = region_mean(box["x"] + 4, x1 - 8)
            right_out = region_mean(x2 + 8, box["x"] + box["w"] - 4)
            null_delta = abs(left_out - right_out)
            band_delta = abs(band - (left_out + right_out) / 2)
            visible = band_delta > max(4.0, null_delta * 2)
            report.add_coverage(
                surface="honesty_greyscale_middrag", axis="ins-trend-brush",
                result="verified" if visible else "partial",
                note=f"band luminance delta={band_delta:.1f} vs null={null_delta:.1f} "
                f"(band={band:.1f}, outside L/R={left_out:.1f}/{right_out:.1f}) — the "
                f"selection band {'IS' if visible else 'is NOT measurably'} visible without "
                "colour, measured from rendered pixels mid-drag",
            )
            if not visible:
                report.add_finding(
                    id="honesty-greyscale-brush-band-invisible", severity="P2",
                    surface="analysis_trend",
                    title="The trend chart's drag band is not measurably visible in "
                    "greyscale mid-interaction",
                    detail=f"band delta {band_delta:.1f} vs null {null_delta:.1f} at "
                    f"{shot_path.name}", evidence=str(shot_path.name), new=True,
                )
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            page.mouse.up()
            page.evaluate("document.documentElement.style.filter = ''")
        report.add_coverage(surface="honesty_greyscale_middrag", axis="ins-trend-brush",
                            result="blocked", note=f"{type(exc).__name__}: {str(exc)[:100]}")

    # -- (rule 6) RTL bidi isolates verified by rendered character x-position ------------- #
    _log("T7: RTL bidi-isolate check by rendered x positions")
    try:
        driver.set_locale("ar")
        page.wait_for_timeout(600)
        found_any = False
        for surface in (
            Surface("rtl_lib", "Library", nav_tab="library", subtab="overview",
                    dom_id="lib-view-overview"),
            Surface("rtl_home", "Home", nav_tab="home", dom_id="tab-home"),
            # The bulletin section's edition table renders a bare ISO date (the drill
            # that runs before this check generates an edition on state C) — the one
            # live raw-ISO specimen this seeded corpus exhibits: the app's shared
            # formatter localises dates everywhere else, so Library/Home/tasks carry
            # none (probed live 2026-08-20). A bare date is the WEAKER specimen class
            # (no punctuation-joined time+offset); the offset-joined class that
            # actually reorders is pinned by the hermetic driver test.
            Surface("rtl_bulletin", "Settings > Advanced > Bulletin", nav_tab="settings",
                    subtab="advanced", advanced_section="bulletin", dom_id="set-advanced"),
        ):
            driver.goto(surface)
            page.wait_for_timeout(800)
            # The found element is TAGGED with a probe attribute and addressed by it: a
            # selector DERIVED from tag/class ("td") resolves to the DOCUMENT's first
            # such element, not the specimen's — char_x_positions then reads the wrong
            # node and the whole check silently finds nothing (hit live: two visible
            # 2026-08-19 TDs present, "no specimen found" reported). The recorded
            # non-unique-needle trap, as a CSS selector.
            hit = page.evaluate(
                """() => {
                  document.querySelectorAll('[data-oo-rtl-probe]')
                    .forEach(e => e.removeAttribute('data-oo-rtl-probe'));
                  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                  let node;
                  while ((node = walker.nextNode())) {
                    const m = node.textContent.match(/\\d{4}-\\d{2}-\\d{2}[T ]?[\\d:]*/);
                    if (!m || m[0].length < 10) continue;
                    const el = node.parentElement;
                    if (!el || !(el.offsetWidth || el.offsetHeight)) continue;
                    el.setAttribute('data-oo-rtl-probe', '1');
                    return {sel: '[data-oo-rtl-probe="1"]', run: m[0].trim()};
                  }
                  return null;
                }"""
            )
            if not hit:
                continue
            xs = driver.char_x_positions(hit["sel"], hit["run"])
            if not xs:
                continue
            found_any = True
            monotonic = all(b > a for a, b in zip(xs, xs[1:], strict=False))
            report.add_coverage(
                surface="honesty_rtl_bidi", axis=f"{surface.id}",
                result="verified" if monotonic else "partial",
                note=f"run={hit['run']!r} in {hit['sel']} — per-char x "
                + ("monotonic (logical order preserved: isolates working)" if monotonic
                   else "REORDERED (a misread value)"),
            )
            if not monotonic:
                report.add_finding(
                    id=f"honesty-rtl-bidi-reordered-{surface.id}", severity="P1",
                    surface=surface.id,
                    title=f"A date/timestamp run renders REORDERED under Arabic on {surface.id}",
                    detail=f"run={hit['run']!r} sel={hit['sel']} xs={[round(x) for x in xs]!r} — "
                    "punctuation-joined LTR values need U+2068…U+2069 isolates (the recorded "
                    "lesson: a misread date, not an ugly one)",
                    new=True,
                )
        if not found_any:
            report.add_coverage(
                surface="honesty_rtl_bidi", axis="specimen-search",
                result="blocked",
                note="no ISO date/timestamp text node found on the probed surfaces under ar — "
                "the check ran and found nothing to measure (recorded, never counted as a pass)",
            )
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="honesty_rtl_bidi", axis="specimen-search",
                            result="blocked", note=str(exc)[:120])

    # -- (rule 7) uppercase is a no-op in five of the twelve locales ---------------------- #
    _log("T7: uppercase-reliance audit across the five no-op locales")
    try:
        reliance: dict[str, list] = {}
        for locale in UPPERCASE_NOOP_LOCALES:
            driver.set_locale(locale)
            page.wait_for_timeout(500)
            driver.goto(Surface("caps_home", "Home", nav_tab="home", dom_id="tab-home"))
            page.wait_for_timeout(400)
            reliance[locale] = driver.uppercase_reliance_audit()
        counts = {k: len(v) for k, v in reliance.items()}
        specimens = {f"{r['tag']}#{r['id']}.{r['cls']}" for v in reliance.values() for r in v}
        report.add_coverage(
            surface="honesty_uppercase_noop", axis="ar-zh-ja-hi-bn",
            result="verified" if not specimens else "partial",
            note=f"case-ONLY-rank elements per locale: {counts}; distinct specimens: "
            + (", ".join(sorted(specimens)[:8]) if specimens else "none — every uppercase "
               "element also steps on size or weight, so hierarchy survives translation"),
        )
        if specimens:
            report.add_finding(
                id="honesty-uppercase-case-only-rank", severity="P2", surface="app-wide",
                title=f"{len(specimens)} elements carry rank by CASE ALONE — invisible in "
                "ar/zh/ja/hi/bn",
                detail=f"specimens: {sorted(specimens)[:10]!r}", new=True,
            )
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="honesty_uppercase_noop", axis="ar-zh-ja-hi-bn",
                            result="blocked", note=str(exc)[:120])

    # -- (rule 8) the i18n walker matches a text node EXACTLY ----------------------------- #
    _log("T7: i18n exact-text-node walker (fr)")
    try:
        import json as _json
        en_map = _json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
        fr_map = _json.loads((LOCALES_DIR / "fr.json").read_text(encoding="utf-8"))
        translatable = {v for k, v in en_map.items()
                        if isinstance(v, str) and fr_map.get(k) and fr_map[k] != v}
        driver.set_locale("fr")
        page.wait_for_timeout(700)
        remainders: dict[str, int] = {}
        for surface in (
            Surface("i18n_home", "Home", nav_tab="home", dom_id="tab-home"),
            Surface("i18n_set", "Settings", nav_tab="settings", subtab="general",
                    dom_id="set-general"),
            Surface("i18n_agenda", "Agenda", nav_tab="agenda", dom_id="tab-agenda"),
        ):
            driver.goto(surface)
            page.wait_for_timeout(700)
            for text in driver.visible_text_nodes():
                if text in translatable:
                    remainders[text] = remainders.get(text, 0) + 1
        report.add_coverage(
            surface="honesty_i18n_exact_node", axis="fr",
            result="verified" if not remainders else "partial",
            note=f"{len(remainders)} distinct keyed-in-fr strings still rendering as their "
            f"EXACT English value under fr (welded/frozen/unwalked nodes); specimens: "
            + "; ".join(list(remainders)[:8]),
        )
        if remainders:
            report.add_finding(
                id="honesty-i18n-english-remainder-fr", severity="P2", surface="app-wide",
                title=f"{len(remainders)} keyed strings render in English under fr — the "
                "exact-text-node symptom, measured in the DOM",
                detail="a node matching an en.json VALUE whose fr translation differs is "
                "chrome that failed to key at render (welded label:value, a frozen "
                "render-once surface, or a walker-unreachable attribute); corroborates the "
                "2026-07-28 GUI audit's i18n gap classes with rendered evidence: "
                + "; ".join(f"{t!r}x{n}" for t, n in list(remainders.items())[:10]),
                new=False,
            )
    except Exception as exc:  # noqa: BLE001
        report.add_coverage(surface="honesty_i18n_exact_node", axis="fr",
                            result="blocked", note=str(exc)[:120])
    finally:
        with contextlib.suppress(Exception):
            driver.set_locale("en")
            page.wait_for_timeout(400)


# ------------------------------------------------------------------------------------------ #
# STATE D -- the import fixture (T2): a real import through the real dialog on a FRESH
# instance, so the post-import screen's CONTENT path renders a real run's summary.
# ------------------------------------------------------------------------------------------ #
def investigate_state_d_import(pw, report: Report, shots: Path) -> None:
    _log("STATE D (import fixture) -- " + STATE_D_URL)
    if not IMPORT_ARTIFACT_DIR or not IMPORT_ARTIFACT_PASS:
        report.add_coverage(
            surface="post_import_content", axis="default", result="blocked",
            note="OO_UIWALK_IMPORT_ARTIFACT / OO_UIWALK_IMPORT_PASS not set — the import "
            "drill needs the pre-built volume-backup artifact (scripts/ui_clickthrough_seed.py "
            "--mini + write_volume_backup); recorded, never silently skipped",
        )
        return
    if not _wait_for_server(STATE_D_URL, timeout_s=30):
        report.add_coverage(surface="post_import_content", axis="default", result="blocked",
                            note=f"state D ({STATE_D_URL}) not answering")
        return
    browser = pw.chromium.launch(executable_path=_chromium_path())
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 950})
        page.on("dialog", lambda d: d.accept())  # arbitrate() is a native confirm()
        driver = PlaywrightUiWalkDriver(page, base_url=STATE_D_URL, screenshot_dir=shots)
        page.wait_for_timeout(1500)
        _dismiss_guide_wizard(page, report, "state_d")
        driver.goto(Surface("state_d_import_dialog", "Import dialog", nav_tab="settings",
                            subtab="data", trigger='button[onclick="openUnifiedImport()"]',
                            dom_id="ux-import"))
        page.fill("#ux-imp-src", IMPORT_ARTIFACT_DIR)
        page.click('button[onclick="_uxImScan(this)"]')
        page.wait_for_selector("#ux-i-corpus", timeout=20000)
        page.wait_for_timeout(300)
        if not page.evaluate("() => document.getElementById('ux-i-corpus').checked"):
            page.check("#ux-i-corpus")
        page.fill("#ux-imp-pass", IMPORT_ARTIFACT_PASS)
        report.add_coverage(surface="post_import_content", axis="scan-finds-corpus",
                            result="verified",
                            note=page.inner_text("#ux-imp-checklist").replace("\n", " ")[:120])
        page.click("#ux-imp-run")
        deadline = time.monotonic() + 180
        summary_text = ""
        while time.monotonic() < deadline:
            page.wait_for_timeout(1500)
            summary_text = page.evaluate(
                "() => (document.getElementById('ux-imp-summary')||{innerText:''}).innerText || ''"
            )
            if summary_text.strip():
                break
        shot = driver.screenshot(Surface("post_import_content", "Post-import screen",
                                         dom_id="ux-imp-summary"))
        if not summary_text.strip():
            report.add_coverage(surface="post_import_content", axis="default",
                                result="partial",
                                note="the import ran but #ux-imp-summary stayed empty within 180s")
            report.add_finding(
                id="post-import-summary-never-rendered", severity="P1",
                surface="post_import_content",
                title="A completed real import rendered no post-import summary",
                detail="state D import via the real dialog; queue reached a terminal state "
                "but the summary stayed empty.", evidence=shot or "", new=True,
            )
            return
        # -- content-level assertions: the 2026-07-20 post-import-redesign rulings, live -- #
        text = summary_text
        checks = [
            ("articles-first-headline", "grew by" in text and "articles" in text.lower()),
            ("labeled-all-types-rowsum", "database records, all types" in text),
            ("before-after-delta", "BEFORE" in text and "AFTER" in text),
            ("qualification-carried", "Qualified sources" in text or "Judged by" in text),
            ("work-induced-indexing", "index" in text.lower()),
            ("additive-statement", "replaced or deleted" in text),
        ]
        for axis, ok in checks:
            report.add_coverage(surface="post_import_content", axis=axis,
                                result="verified" if ok else "partial",
                                note="" if ok else f"expected marker absent; summary head: {text[:120]!r}")
        if all(ok for _, ok in checks):
            report.add_finding(
                id="post-import-redesign-renders-live", severity="POSITIVE",
                surface="post_import_content",
                title="The post-import results screen renders its full redesigned content "
                "from a REAL import — browser-verified for the first time",
                detail="Articles-first headline, the labeled all-types row-sum, the "
                "BEFORE/AFTER corpus delta, qualification carried (criteria version "
                "shown), the work-induced indexing note and the additive-restore statement "
                "all rendered from a real volume-backup import on a fresh instance.",
                evidence=shot or "", new=True,
            )
        report.add_coverage(surface="post_import_content", axis="default", result="verified",
                            note=f"summary length={len(text)}; first line: "
                            f"{text.splitlines()[0][:80]!r}")
    finally:
        browser.close()


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

        # -- T1 acceptance: the 375px walk across ALL FIVE flagship surfaces ------------------ #
        # The brief's T1 acceptance line is per-surface ("zero horizontal overflow on all
        # flagship surfaces"), not per-breakpoint-on-whatever-tab-is-open — so each flagship
        # surface is navigated to and THEN measured at 375px, activity chip forced visible
        # (the worst case the fix was built against).
        _log("T1 acceptance: 375px overflow walk across the 5 flagship surfaces")
        for surface in FLAGSHIP_SURFACES:
            try:
                # Navigate at DESKTOP width, then measure at 375. The first full run
                # navigated at whatever width the previous check left (375), and the
                # click grammar legitimately cannot run there: below 600px the sidebar
                # may collapse/off-canvas (invariant #2's own floor), so the settings
                # gear click times out. The user's own flow is the same — they navigate,
                # then the viewport is whatever it is; the claim under test is "the
                # surface, once open, does not overflow at 375", not "375px navigation".
                driver.set_viewport(1440, 950)
                driver.goto(surface)
                driver.page.wait_for_timeout(300)
                _check_breakpoint_overflow(driver, report, 375, 900,
                                           surface_label=surface.id)
            except Exception as exc:  # noqa: BLE001
                report.add_coverage(surface=f"breakpoint_375_{surface.id}", axis="width-375",
                                    result="blocked", note=f"{type(exc).__name__}: {exc}")
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

        # ==================== the 2026-08-20 matrix expansion (T3/T5/T6/T7) ================= #
        reader_article_id = drill_reader(driver, report, shots)            # T3
        drill_worldmap_lens_controls(driver, report)                       # T5a
        drill_task_manager_panels(driver, report)                          # T5c
        drill_settings_ai_pill(driver, report)                             # T5b
        drill_bulletin(driver, report, shots)                              # T5d
        drill_agenda_provenance(driver, report)                            # T5e
        a11y_pass(driver, report, reader_article_id)                       # T6
        honesty_checks(driver, report, shots)                              # T7

        report.add_coverage(surface="state_c_walk", axis="summary", result="verified",
                             note=f"{len(FLAGSHIP_SURFACES) + len(BACKLOG_SURFACES)} named "
                             f"surfaces + subtab drills + {len(THEMES_TO_CHECK)} themes + "
                             f"{len(BREAKPOINTS)} breakpoints (+ flagship-375 walk) + "
                             f"{len(LOCALES_TO_CHECK)} locales + reader/lens/a11y/honesty "
                             f"drills (T3/T5/T6/T7)")
    finally:
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/audit/ui-clickthrough-2026-08-20")
    args = ap.parse_args()

    out_dir = Path(args.out)
    shots = out_dir / "evidence"
    shots.mkdir(parents=True, exist_ok=True)

    report = Report()
    states = [("A", STATE_A_URL), ("B", STATE_B_URL), ("C", STATE_C_URL)]
    if IMPORT_ARTIFACT_DIR:
        states.append(("D", STATE_D_URL))
    for label, url in states:
        if not _wait_for_server(url):
            _log(f"WARNING: state {label} ({url}) did not answer within the readiness "
                 f"timeout -- proceeding anyway, but its results may read as false negatives.")
        else:
            _log(f"state {label} ({url}) is warm")

    with sync_playwright() as pw:
        investigate_state_a(pw, report, shots)
        investigate_state_b(pw, report, shots)
        investigate_state_c(pw, report, shots)
        investigate_state_d_import(pw, report, shots)  # T2 (self-skips without the env)

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
