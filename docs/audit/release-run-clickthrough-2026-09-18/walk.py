"""Chromium click-through of the 0.4 release-run box (Settings -> Advanced -> Diagnostics),
in en / ar (Q1128 = a: Chromium in the sandbox + the maintainer's own pass).

Drives the PINNED Chromium at /opt/pw-browsers through Playwright. Real rendering, real
fonts, real JS -- what a node harness and a source test cannot see.

WHAT IS BEING CHECKED, and why each one needs a browser:
  * the box RENDERS inside the collapsed Diagnostics section once it is expanded, with
    every control, in both locales, and the section still fetches nothing on open;
  * the three CHECKBOXES escape the global `input { width:100% }` rule (the recorded
    2026-09-16 defect that stretched two checkboxes to ~350 px);
  * the SAFE controls answer honestly with no run in flight -- "Check now" reads the
    persisted record and says "Not running.", "Collect now" says no run is in progress --
    in the reader's own language;
  * the RUN button refuses BEFORE the consent popup when the fields are empty, so an
    accidental press never flips the network state;
  * RTL: `dir="rtl"` on the Arabic render, and zero page / console errors throughout.

The run itself (hours of backup, a subprocess restore, a >= 72 h soak) is NOT driven
here: it is the operator's, on their machine, and the report it writes is the record.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8231"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "out")
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
LOCALES = ["en", "ar"]

OUT.mkdir(parents=True, exist_ok=True)
report: dict = {"base": BASE, "locales": {}, "console_errors": [], "page_errors": []}


def dismiss_wizard(page) -> bool:
    dlg = page.query_selector("#guide-wizard[open]")
    if not dlg:
        return False
    page.click("#gw-close")
    page.wait_for_selector("#guide-wizard[open]", state="detached", timeout=5000)
    return True


def open_box(page) -> dict:
    """Settings -> Advanced -> expand "Diagnostics". The section is collapsed and, by its
    standing property, fetches nothing on expand; the request count is read to prove it."""
    page.click("button[onclick=\"showTab('settings')\"]")
    page.wait_for_selector("#set-subtabs", state="visible", timeout=15000)
    page.click("#set-subtabs button[data-tab='advanced']")
    page.wait_for_timeout(300)
    before = page.evaluate("() => performance.getEntriesByType('resource').length")
    page.click("details[data-adv='diagnostics'] > summary")
    page.wait_for_selector("#release-run-box", state="visible", timeout=15000)
    page.wait_for_timeout(500)
    after = page.evaluate("() => performance.getEntriesByType('resource').length")
    return {"resource_requests_before_expand": before, "resource_requests_after_expand": after}


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
        # THE ENGINE THE INVARIANT NAMES (#15): one call switches the whole UI; awaited
        # before anything is read (the boot half of the frozen-locale class is a race).
        page.evaluate("async (l) => { await window.OOI18N.ready;"
                      " await window.OOI18N.setLang(l); }", lang)
        page.wait_for_timeout(400)
        expand = open_box(page)

        controls = page.evaluate("""() => {
          const ids = ['rr-dest','rr-pass','rr-legacy','rr-hours','rr-newsletters','rr-probes','rr-row5',
                       'rr-run-btn','rr-run-million-btn','rr-status','rr-result'];
          const out = {};
          for (const id of ids) {
            const e = document.getElementById(id);
            out[id] = e ? { present: true, width: Math.round(e.getBoundingClientRect().width),
                            checked: e.type === 'checkbox' ? e.checked : null,
                            type: e.type || null, text: (e.innerText || '').trim().slice(0, 80) } : { present: false };
          }
          const box = document.getElementById('release-run-box');
          out.box_text_head = box ? box.innerText.replace(/\\s+/g, ' ').trim().slice(0, 160) : null;
          out.buttons = Array.from(box.querySelectorAll('button')).map(b => b.innerText.trim());
          return out;
        }""")

        page.locator("#release-run-box").scroll_into_view_if_needed()
        page.wait_for_timeout(250)
        page.locator("#release-run-box").screenshot(path=str(OUT / f"release-run-box-{lang}.png"))

        # --- the safe controls, with no run in flight ------------------------------ #
        page.click("#release-run-box button[onclick='releaseRunStatus(this)']")
        page.wait_for_function(
            "() => (document.getElementById('rr-status').textContent || '').trim().length > 0",
            timeout=15000)
        status_after_check = page.eval_on_selector("#rr-status", "e => e.textContent").strip()
        page.click("#release-run-box button[onclick='releaseRunCollect(this)']")
        page.wait_for_function(
            "(prev) => (document.getElementById('rr-status').textContent || '').trim() !== prev",
            arg=status_after_check, timeout=15000)
        status_after_collect = page.eval_on_selector("#rr-status", "e => e.textContent").strip()

        # --- the run button with EMPTY fields: refused before any consent popup ------ #
        # The network state is read BEFORE the press as well as after, because this
        # ephemeral instance boots ONLINE under OO_NO_SCHEDULER=1 (the boot-time airplane
        # engagement lives inside that same block); the claim is that the press CHANGED
        # nothing, not that the instance is offline.
        online_before = page.evaluate("async () => (await (await fetch('/api/system/network')).json()).online")
        page.click("#rr-run-btn")
        page.wait_for_timeout(600)
        status_after_empty_run = page.eval_on_selector("#rr-status", "e => e.textContent").strip()
        consent_open = page.evaluate("() => !!document.querySelector('#net-consent[open]')")
        online = page.evaluate("async () => (await (await fetch('/api/system/network')).json()).online")

        page.locator("#release-run-box").screenshot(path=str(OUT / f"release-run-box-after-checks-{lang}.png"))

        report["locales"][lang] = {
            "first_run_wizard_dismissed": rec_wizard,
            "expand": expand,
            "controls": controls,
            "status_after_check_now": status_after_check,
            "status_after_collect_now": status_after_collect,
            "status_after_empty_run": status_after_empty_run,
            "consent_popup_opened_on_empty_run": consent_open,
            "network_online_before_empty_run": online_before,
            "network_online_after_empty_run": online,
            "dir": page.evaluate("() => ({"
                                 " attr: document.documentElement.getAttribute('dir'),"
                                 " lang: document.documentElement.lang,"
                                 " computed: getComputedStyle(document.body).direction })"),
            "ui_lang": page.evaluate("() => window.OOI18N.current()"),
        }
        ctx.close()
    browser.close()

(OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: v for k, v in report.items() if k != "locales"}, ensure_ascii=False))
for lang, rec in report["locales"].items():
    print(lang, "| check:", rec["status_after_check_now"], "| collect:", rec["status_after_collect_now"],
          "| empty run:", rec["status_after_empty_run"], "| consent opened:", rec["consent_popup_opened_on_empty_run"],
          "| online before/after:", rec["network_online_before_empty_run"], rec["network_online_after_empty_run"],
          "| dir:", rec["dir"]["attr"],
          "| requests on expand:", rec["expand"])
    for cb in ("rr-newsletters", "rr-probes", "rr-row5"):
        c = rec["controls"][cb]
        print("   ", cb, "width", c["width"], "checked", c["checked"])
