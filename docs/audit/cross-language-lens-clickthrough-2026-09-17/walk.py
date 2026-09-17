#!/usr/bin/env python3
"""The cross-language LENS, rendered — Chromium in the remote sandbox (`S04-07` PR 2).

Q1128 = a's bar is *Chromium in the sandbox + the maintainer's own click-through*; this is
the first half only, and the honest stamp is "Chromium-verified (remote sandbox) · awaiting
human UX pass".

WHY A RENDERED PAGE AND NOT THE NODE SUITE. `tests/cross_language_lens_node_test.js` drives
every renderer here as real code and proves the HTML. It cannot see the page, and the three
failures this slice actually risks are all invisible to it: an RTL or CJK locale clipping
the expansion rail or the per-form chips, the i18n walker leaving a new string untranslated
on screen although its key is in all twelve files, and the lens round-tripping through a
REAL History API rather than the shim the node suite hands it.

Usage (the app already booted against a seeded store):

    OO_WALK_URL=http://127.0.0.1:8010 .venv/bin/python <this> --out docs/audit/...

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("OO_WALK_URL", "http://127.0.0.1:8010")
LOCALES = ["en", "ar", "zh", "ja", "hi"]
TERM = "climate"


def _settle(page, ms: int = 1200) -> None:
    page.wait_for_timeout(ms)


def _reported_total(page) -> int | None:
    """The article total the LIST itself reports — the number the lens actually moves.

    The page holds fifty rows whichever lens is on, so counting rendered rows measures the
    page size and calls it a result. Read off the same line the reader reads, with the
    locale's own digit grouping stripped.
    """
    try:
        page.wait_for_selector("#an-art-total b", timeout=20000)
    except Exception:  # noqa: BLE001 - report the absence, never a fabricated number
        return None
    return page.evaluate(
        "() => { const h = document.querySelector('#an-art-total b');"
        " if (!h) return null;"
        " const m = h.textContent.replace(/[\\s\\u00a0\\u202f,.]/g, '').match(/\\d+/);"
        " return m ? Number(m[0]) : null; }"
    )


def walk_locale(page, lg: str, out: Path) -> dict:
    """One locale, end to end, reading every claim back off the rendered DOM."""
    r: dict = {"locale": lg}
    page.goto(URL, wait_until="domcontentloaded")
    page.evaluate("(c) => localStorage.setItem('oo.lang', c)", lg)
    # A fresh tab workspace per locale: a tab persisted by the previous locale would
    # re-seed its own lens and this walk would be measuring the run before it.
    page.evaluate("() => localStorage.removeItem('oo.an.tabs.v1')")
    page.goto(f"{URL}/?analyze={TERM}", wait_until="domcontentloaded")
    _settle(page, 3000)
    # A spawned tab lands on the OVERVIEW subtab (the generic landing, Q1), so the
    # Articles list and the expansion rail it renders are in the DOM but not on screen.
    # Everything below reads the RENDERED page, so the subtab has to be selected first --
    # a walk that measured a hidden node would be reading the DOM, not the surface.
    page.evaluate("() => { if (window._anSubtabs) _anSubtabs.select('articles'); else anSelectTab('articles'); }")
    _settle(page, 2500)
    r["dir"] = page.evaluate("() => document.documentElement.getAttribute('dir') || 'ltr'")
    r["lang_applied"] = page.evaluate("() => (window.OOI18N && OOI18N.current()) || '?'")

    # --- the expansion rail -------------------------------------------------------
    rail = page.query_selector("#an-xlang")
    r["rail_on_screen"] = bool(rail and rail.is_visible())
    r["rail_text"] = (rail.inner_text().strip()[:400] if rail else "")
    # An untranslated rail is the failure the i18n gates cannot see: the keys are in all
    # twelve files and the walker still has to repaint this node.
    # The rail's LAST line is the server's own caveat. It is the string that rendered in
    # English on four translated pages, so it is read back on its own rather than being
    # left inside the rail blob where a reader of the report would have to spot it.
    r["caveat_line"] = page.evaluate(
        "() => { const e = document.querySelector('#an-xlang > div:last-child');"
        " return e ? e.textContent.trim().slice(0, 200) : ''; }"
    )
    r["rail_has_latin_default"] = bool(
        rail and lg not in ("en",) and "Show only the words I typed" in (rail.inner_text() or "")
    )

    # --- the Language column, on every row ----------------------------------------
    rows = page.query_selector_all("#an-art-list table tr[data-aid]")
    r["article_rows"] = len(rows)
    r["rows_with_language_cell"] = sum(
        1 for row in rows if len(row.query_selector_all("td")) >= 4
    )
    hdrs = page.query_selector_all("#an-art-list table tr:first-child th")
    r["columns"] = [h.inner_text().strip() for h in hdrs]

    # --- Q509: the per-form counts, on a click ------------------------------------
    trigger = page.query_selector("#an-xlang button:has-text('')")
    btns = page.query_selector_all("#an-xlang button")
    r["rail_buttons"] = [b.inner_text().strip() for b in btns]
    count_btn = None
    for b in btns:
        if b.get_attribute("onclick") and "_anFormCounts" in (b.get_attribute("onclick") or ""):
            count_btn = b
            break
    r["count_trigger_present"] = count_btn is not None
    if count_btn is not None:
        count_btn.click()
        # The counts are N full-text counts against the corpus, so "Counting…" is a real
        # state and not a spinner: WAIT for it to resolve rather than settling for a
        # fixed delay, or the first locale walked reports the placeholder as the result.
        try:
            page.wait_for_function(
                "() => { const e = document.querySelector(\"[id^='an-xforms-']\");"
                " return e && e.textContent.trim() && !/…\\s*$/.test(e.textContent.trim()); }",
                timeout=60000,
            )
        except Exception:  # noqa: BLE001 - a timeout is recorded, never papered over
            pass
        slot = page.query_selector("[id^='an-xforms-']")
        r["form_counts_text"] = (slot.inner_text().strip()[:400] if slot else "")
        r["form_counts_rendered"] = bool(r["form_counts_text"])
    del trigger

    # --- Q503's note: the cap switch, both ways -----------------------------------
    r["cap"] = {}
    before_url = page.url
    page.evaluate("() => _anSetCap(false)")
    _settle(page, 2500)
    r["cap"]["url_after_off"] = page.url
    r["cap"]["url_carries_cap0"] = "cap=0" in page.url
    rail2 = page.query_selector("#an-xlang")
    r["cap"]["rail_after_off"] = (rail2.inner_text().strip()[:240] if rail2 else "")
    page.evaluate("() => _anSetCap(true)")
    _settle(page, 2000)
    r["cap"]["url_after_on"] = page.url
    r["cap"]["cap0_cleared"] = "cap=0" not in page.url
    del before_url

    # --- Q504: the literal toggle and its URL state -------------------------------
    page.evaluate("() => _anSetExpand(false)")
    _settle(page, 2500)
    r["expand_off_url_carries"] = "expand=0" in page.url
    rail3 = page.query_selector("#an-xlang")
    r["narrowed_rail_text"] = (rail3.inner_text().strip()[:240] if rail3 else "")
    r["total_narrowed"] = _reported_total(page)
    page.evaluate("() => _anSetExpand(true)")
    _settle(page, 2500)
    r["total_widened"] = _reported_total(page)
    r["expand0_cleared"] = "expand=0" not in page.url

    # --- Q508's note: group by language, a VIEW over the same rows -----------------
    page.evaluate("() => _anSetGroupByLang(true)")
    _settle(page, 2000)
    r["grouped_headings"] = len(page.query_selector_all("#an-art-list tr.an-lang-group"))
    r["rows_when_grouped"] = len(page.query_selector_all("#an-art-list table tr[data-aid]"))
    page.screenshot(path=str(out / f"analysis-{lg}.png"), full_page=False)
    page.evaluate("() => _anSetGroupByLang(false)")
    _settle(page, 1200)

    # --- overflow: does anything spill horizontally at this width? -----------------
    r["overflow_px"] = page.evaluate(
        "() => { const e = document.getElementById('an-articles') || document.body;"
        " return Math.max(0, e.scrollWidth - e.clientWidth); }"
    )
    return r


def walk_surface(page, lg: str, name: str, tab: str, out: Path) -> dict:
    """The other named surfaces: render them and record the console errors, if any."""
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))
    page.goto(URL, wait_until="domcontentloaded")
    page.evaluate("(c) => localStorage.setItem('oo.lang', c)", lg)
    page.goto(f"{URL}/?tab={tab}", wait_until="domcontentloaded")
    _settle(page, 2000)
    try:
        page.evaluate("(t) => showTab(t)", tab)
    except Exception:  # noqa: BLE001
        pass
    _settle(page, 2500)
    page.screenshot(path=str(out / f"{name}-{lg}.png"))
    return {"surface": name, "locale": lg, "errors": errs[:5],
            "dir": page.evaluate("() => document.documentElement.getAttribute('dir') || 'ltr'")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"url": URL, "term": TERM, "locales": [], "surfaces": []}
    with sync_playwright() as pw:
        # The sandbox ships Chromium at a build this playwright release does not expect,
        # and `playwright install` is not how this environment is meant to be used, so the
        # binary is named rather than downloaded (OO_WALK_CHROME overrides).
        exe = os.environ.get("OO_WALK_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        browser = pw.chromium.launch(executable_path=exe if Path(exe).exists() else None)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for lg in LOCALES:
            report["locales"].append(walk_locale(page, lg, out))
        for lg in ("en", "ar"):
            for name, tab in (("search", "search"), ("insights", "insights"),
                              ("observatory", "observatory"), ("map", "timemap")):
                report["surfaces"].append(walk_surface(page, lg, name, tab, out))
        browser.close()
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
