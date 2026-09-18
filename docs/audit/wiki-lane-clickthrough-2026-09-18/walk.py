#!/usr/bin/env python3
"""Chromium click-through for S04-09's S4 and S5 surfaces, in four locales.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1128 = a's sandbox half. Walks the FOUR surfaces this slice added on screen -- the
first-run wizard, the reader's licence notice, the Home strip's own figure and the map
layer -- in `en`, `ar` (RTL), `zh` and `de`.

PER SURFACE AND PER LOCALE, NEVER OVER A CONCATENATION. The recorded defect is a locale
check over two elements' joined text passing while one stayed English, because the other
one translating changed the string enough. Every assertion below names the ONE element
it is about.

Run:  OO_DATA_DIR=<seeded> .venv/bin/python walk.py --url http://127.0.0.1:8099 --out <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

LOCALES = ("en", "ar", "zh", "de")

#: The English each surface shows if `t()` falls through. Deliberately the exact
#: strings, not a language detector: a false negative is fine (the screenshots are the
#: real evidence), a false positive sends a reader hunting.
ENGLISH_MARKERS = {
    "wizard_title": "Following Wikipedia as it changes",
    "wizard_editions": "Editions to follow",
    "wizard_budget": "Storage budget",
    "wizard_robots": "blanket-applying robots.txt would wrongly block legitimate API use",
    "reader_licence": "Wikipedia text, reused under a free licence.",
    "reader_history": "page history (the authors)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8099")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--article", default="1")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    findings: list[str] = []
    record: dict = {"url": args.url, "locales": {}}

    with sync_playwright() as pw:
        exe = os.environ.get("OO_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        browser = pw.chromium.launch(executable_path=exe if os.path.exists(exe) else None)
        for lang in LOCALES:
            per: dict = {}
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(args.url, wait_until="domcontentloaded")
            page.wait_for_timeout(1600)
            # A screenshot taken behind a modal proves the DOM and shows nothing about
            # what a reader can see -- which is the only thing a click-through adds.
            for _ in range(4):
                closed = page.evaluate(
                    "() => { let n = 0;"
                    "  document.querySelectorAll('dialog[open]').forEach(d => { d.close(); n++; });"
                    "  return n; }"
                )
                page.wait_for_timeout(200)
                if not closed:
                    break
            page.evaluate("() => { try { localStorage.setItem('oo.guide.done','1'); } catch (e) {} }")
            page.evaluate("(l) => window.OOI18N && OOI18N.setLang(l)", lang)
            page.wait_for_timeout(900)

            # ---------------- 1. The Home strip's own figure (Q714) ------------- #
            page.wait_for_timeout(1200)
            fig = page.query_selector("#home-wiki-figure")
            if fig is None:
                findings.append(f"{lang}/home: the lane's own figure is absent from the strip")
            else:
                text = (fig.text_content() or "").strip()
                title = fig.get_attribute("title") or ""
                per["home_figure"] = {"text": text, "title_len": len(title)}
                if not any(ch.isdigit() for ch in text):
                    findings.append(f"{lang}/home: the figure carries no number: {text!r}")
                if "{pages}" in text or "{changes}" in text:
                    findings.append(f"{lang}/home: a placeholder reached the screen: {text!r}")
                if lang != "en" and "pages" in text and "changes today" in text:
                    findings.append(f"{lang}/home: the figure is still English: {text!r}")
                strip = page.query_selector("#home-stats")
                if strip is not None:
                    box = strip.bounding_box()
                    if box:
                        page.screenshot(
                            path=str(args.out / f"home-strip-{lang}.png"),
                            clip={"x": box["x"], "y": box["y"],
                                  "width": box["width"], "height": min(box["height"], 200)},
                        )

            # ---------------- 2. The first-run wizard (Q725 + Q726) ------------- #
            page.evaluate("() => openWikiWizard && openWikiWizard()")
            page.wait_for_timeout(1400)
            dlg = page.query_selector("#wiki-wizard[open]")
            if dlg is None:
                findings.append(f"{lang}/wizard: the dialog did not open")
            else:
                boxes = page.query_selector_all("#wiki-wizard-editions input[type=checkbox]")
                hosts = (page.eval_on_selector("#wiki-wizard-hosts", "e => e.textContent") or "").strip()
                share = (page.eval_on_selector("#wiki-wizard-share", "e => e.textContent") or "").strip()
                budget = page.eval_on_selector("#wiki-wizard-budget", "e => e.value")
                # The WHOLE dialog, not just the scrolling body: the title lives in the
                # <h3> above it, and the first version of this walk read only the body
                # and reported the title as missing in every locale.
                body = page.eval_on_selector("#wiki-wizard", "e => e.textContent") or ""
                per["wizard"] = {
                    "editions": len(boxes),
                    "checked": sum(1 for b in boxes if b.is_checked()),
                    "hosts": hosts,
                    "share": share,
                    "budget": budget,
                }
                if len(boxes) != 12:
                    findings.append(f"{lang}/wizard: {len(boxes)} editions offered, expected 12")
                if per["wizard"]["checked"] != 12:
                    findings.append(f"{lang}/wizard: {per['wizard']['checked']} checked, expected all twelve")
                if budget != "20":
                    findings.append(f"{lang}/wizard: budget defaults to {budget!r}, expected '20'")
                # The hosts are LITERALS and must survive every translation verbatim:
                # a localized hostname is an unreachable address on a consent surface.
                for host in ("stream.wikimedia.org", "wikimedia.org"):
                    if host not in hosts:
                        findings.append(f"{lang}/wizard: the host line omits {host}: {hosts!r}")
                if not share or "{" in share:
                    findings.append(f"{lang}/wizard: the share line is empty or unfilled: {share!r}")
                for key in ("wizard_title", "wizard_editions", "wizard_budget", "wizard_robots"):
                    marker = ENGLISH_MARKERS[key]
                    if lang != "en" and marker in body:
                        findings.append(f"{lang}/wizard: {key} is still English")
                    if lang == "en" and marker not in body:
                        findings.append(f"en/wizard: {key} is missing from the dialog")
                box = dlg.bounding_box()
                if box:
                    page.screenshot(path=str(args.out / f"wizard-{lang}.png"),
                                    clip={"x": box["x"], "y": box["y"],
                                          "width": box["width"], "height": min(box["height"], 900)})
                page.evaluate("() => { const d = document.getElementById('wiki-wizard'); if (d) d.close(); }")
                page.wait_for_timeout(250)

            # ---------------- 3. The map layer (Q819 step 1) -------------------- #
            # The wired surface is the coverage map, which lives in the TIMEMAP tab and
            # renders lazily -- the first version of this walk asked for a tab called
            # "map" and found no control in any locale.
            try:
                page.evaluate("() => showTab && showTab('timemap', false)")
            except Exception:
                pass
            page.wait_for_timeout(3500)
            btn = page.query_selector("[data-oomap-wiki]")
            if btn is None:
                findings.append(f"{lang}/map: the Wikipedia layer control is absent")
            else:
                btn.click()
                page.wait_for_timeout(2200)
                markers = page.query_selector_all("[data-oomap-wikilayer] circle")
                filled = page.query_selector_all("[data-oomap-wikilayer] circle[fill^='var']")
                per["map"] = {"markers": len(markers), "filled": len(filled)}
                if len(markers) != 6:
                    findings.append(f"{lang}/map: {len(markers)} markers drawn, expected the 6 seeded")
                if len(filled) != 5:
                    findings.append(f"{lang}/map: {len(filled)} filled (QID) markers, expected 5")
                svg = page.query_selector("[data-oomap-wikilayer]")
                if svg is not None:
                    holder = page.query_selector(".oomap, #map-host, svg")
                    if holder is not None:
                        b = holder.bounding_box()
                        if b:
                            page.screenshot(path=str(args.out / f"map-layer-{lang}.png"),
                                            clip={"x": b["x"], "y": b["y"],
                                                  "width": b["width"], "height": min(b["height"], 600)})

            # ---------------- 4. The reader's licence notice (Q726) ------------- #
            reader = browser.new_page(viewport={"width": 1100, "height": 900})
            reader.goto(f"{args.url}/api/articles/{args.article}/view", wait_until="domcontentloaded")
            reader.wait_for_timeout(900)
            reader.evaluate("(l) => window.OOI18N && OOI18N.setLang(l)", lang)
            reader.wait_for_timeout(900)
            note = reader.query_selector(".licence")
            if note is None:
                findings.append(f"{lang}/reader: the licence notice is absent")
            else:
                text = reader.eval_on_selector(".licence", "e => e.textContent") or ""
                links = reader.eval_on_selector_all(
                    ".licence a", "els => els.map(e => ({href: e.href, cls: e.className}))"
                )
                per["reader"] = {"links": links, "chars": len(text)}
                if "CC BY-SA 4.0" not in text:
                    findings.append(f"{lang}/reader: the licence identifier is not shown")
                if not any("action=history" in (a["href"] or "") for a in links):
                    findings.append(f"{lang}/reader: no link to the page history -- that IS the attribution")
                for a in links:
                    if "ext" not in (a["cls"] or ""):
                        findings.append(f"{lang}/reader: an outbound link is not confirm-gated: {a['href']}")
                if lang != "en" and ENGLISH_MARKERS["reader_licence"] in text:
                    findings.append(f"{lang}/reader: the licence sentence is still English")
                if lang == "en" and ENGLISH_MARKERS["reader_history"] not in text:
                    findings.append("en/reader: the history link's label is missing")
                b = note.bounding_box()
                if b:
                    reader.screenshot(path=str(args.out / f"reader-licence-{lang}.png"),
                                      clip={"x": max(0, b["x"] - 8), "y": max(0, b["y"] - 8),
                                            "width": b["width"] + 16, "height": b["height"] + 16})
            reader.close()

            record["locales"][lang] = per
            page.close()
        browser.close()

    record["findings"] = findings
    (args.out / "report.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    for f in findings:
        print("FINDING:", f)
    print(f"\n{len(findings)} finding(s); shots + report in {args.out}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
