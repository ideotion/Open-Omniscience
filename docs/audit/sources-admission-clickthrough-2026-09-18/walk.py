"""Chromium click-through of S04-12's three surfaces, in en / fr / ar (Q1128 = a).

Drives the PINNED Chromium at /opt/pw-browsers through Playwright. Real rendering, real
fonts, real JS -- the three things a node harness and a source test cannot see.

WHAT IS BEING CHECKED, and why each one needs a browser:
  * the HEADLINE COUNTS (Q1114) carry their predicate LABEL on screen, in each locale --
    the recorded finding on this very panel is that two English fragments sat inside the
    untranslatable ratchet's allowance, so the gate was green and could not have said
    otherwise;
  * the ADMISSION AUDIT offers Undo on the row that is still reversible and does NOT
    offer it on the row a later verdict replaced, with a translated reason instead;
  * the UNDO actually works when clicked -- the safety valve Q1101's flip rests on, driven
    with a real `page.click`, because a scripted `el.click()` is not a click;
  * the SHIPPED-VERDICT EDITOR renders in both of its states.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8213"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "out")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
LOCALES = ["en", "fr", "ar"]

OUT.mkdir(parents=True, exist_ok=True)
report: dict = {"base": BASE, "locales": {}, "console_errors": [], "page_errors": []}


def dismiss_wizard(page) -> bool:
    """The first-run wizard owns a fresh instance's screen. Dismissed through its OWN
    close control, not by removing the node -- a walk that deletes the blocker is testing
    a page no operator ever sees."""
    dlg = page.query_selector("#guide-wizard[open]")
    if not dlg:
        return False
    page.click("#gw-close")
    page.wait_for_selector("#guide-wizard[open]", state="detached", timeout=5000)
    return True


def open_panel(page) -> None:
    """Settings -> Advanced, where the Quality-gates panel really lives.

    NOT "Settings -> Sources": there is no such subtab (`#set-subtabs` is graphics /
    general / cards / AI / Wikipedia / OpenStreetMap / agenda / data / advanced). The
    S04-12 brief names one, which is exactly the kind of path a maintainer's own
    click-through would spend time looking for.
    """
    page.click("button[onclick=\"showTab('settings')\"]")
    page.wait_for_selector("#set-subtabs", state="visible", timeout=15000)
    page.click("#set-subtabs button[data-tab='advanced']")
    # AND THEN EXPAND "Quality gates": the panel lives inside a COLLAPSED
    # `<details class="adv-sec" data-adv="qualification">`, and its loader is wired to
    # that section opening (`app-shell.js`'s adv-section map). Nothing renders until an
    # operator expands it -- a real step on the path, and one worth naming in the record.
    page.click("details[data-adv='qualification'] > summary")
    page.wait_for_selector("#qual-admission", state="visible", timeout=15000)
    # Wait for the CONTROL, never for a duration: a fixed settle tuned on one locale
    # reports "not there" in another, which is a fail indistinguishable from absence.
    page.wait_for_function(
        "() => { const e = document.getElementById('qual-admission');"
        " return e && !/Loading/.test(e.textContent); }", timeout=20000)
    page.wait_for_function(
        "() => { const e = document.getElementById('qual-overlay');"
        " return e && !/Loading/.test(e.textContent); }", timeout=20000)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    for lang in LOCALES:
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.on("console", lambda m: report["console_errors"].append(m.text)
                if m.type == "error" else None)
        page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
        page.goto(BASE, wait_until="networkidle")
        rec_wizard = dismiss_wizard(page)
        # THE ENGINE THE INVARIANT NAMES (#15): one call switches the whole UI. Awaited
        # before anything is read, because the boot half of the frozen-locale class is a
        # race between the locale fetch and the panel's own.
        page.evaluate("async (l) => { await window.OOI18N.ready;"
                      " await window.OOI18N.setLang(l); }", lang)
        page.wait_for_timeout(400)
        open_panel(page)
        page.wait_for_timeout(600)

        rows = page.evaluate("""() => {
          const host = document.getElementById('qual-admission');
          return Array.from(host.querySelectorAll('.row')).map(r => ({
            text: r.innerText.replace(/\\s+/g, ' ').trim(),
            hasUndoButton: !!r.querySelector('button[data-undo]'),
          }));
        }""")
        state = page.eval_on_selector("#qual-state", "e => e.innerText").strip()
        overlay = page.eval_on_selector("#qual-overlay", "e => e.innerText").strip()
        audit_txt = page.eval_on_selector("#qual-admission", "e => e.innerText").strip()

        rec = {
            "first_run_wizard_dismissed": rec_wizard,
            "headline_state": state,
            "admission_rows": rows,
            "overlay_text": overlay,
            "audit_text": audit_txt,
            "dir": page.evaluate("() => ({"
                                 " attr: document.documentElement.getAttribute('dir'),"
                                 " lang: document.documentElement.lang,"
                                 " computed: getComputedStyle(document.body).direction })"),
        }

        # The panel sits below the fold once "Quality gates" is expanded, so bring the
        # element on screen before clipping to it -- a clip computed against a rect that
        # is off-screen is not a tighter screenshot, it is no screenshot at all.
        page.locator("#qual-state").scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / f"quality-gates-{lang}.png"), full_page=False)
        page.locator("#qual-admission").scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        page.locator("#qual-admission").screenshot(
            path=str(OUT / f"admission-audit-{lang}.png"))
        page.locator("#qual-overlay").scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        page.locator("#qual-overlay").screenshot(
            path=str(OUT / f"shipped-verdicts-{lang}.png"))

        # --- the UNDO, driven as a REAL click, once, AFTER every locale ---------- #
        if lang == LOCALES[-1]:
            before = page.evaluate(
                "async () => (await (await fetch('/api/sources/admission/audit?limit=25'))"
                ".json())")
            page.locator("#qual-admission").scroll_into_view_if_needed()
            page.click("#qual-admission button[data-undo]")
            page.wait_for_function(
                "() => document.querySelectorAll('#qual-admission button[data-undo]')"
                ".length === 0", timeout=15000)
            after = page.evaluate(
                "async () => (await (await fetch('/api/sources/admission/audit?limit=25'))"
                ".json())")
            page.locator("#qual-admission").screenshot(
                path=str(OUT / f"admission-after-undo-{lang}.png"))
            rec["undo_click"] = {
                "undone_before": before["undone_total"],
                "undone_after": after["undone_total"],
                "collecting_before": before["collecting"],
                "collecting_after": after["collecting"],
            }

        report["locales"][lang] = rec
        ctx.close()
    browser.close()

(OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
print(json.dumps(report, indent=2, ensure_ascii=False)[:6000])
