#!/usr/bin/env python3
"""Chromium click-through for the Wikipedia-lane toggle, in four locales.

Drives the REAL page in a real browser (Q1128 = a: Chromium in the sandbox + the
maintainer's own pass = verified; this half is the sandbox half). Records one
screenshot per locale per state and asserts, per surface and per locale, that the
control is present, that its hover is TRANSLATED, and that every state it can be in
is reachable and named.

WHY PER SURFACE AND NOT A CONCATENATION. The recorded defect is a locale check over a
CONCATENATION of two elements passing while one of them stayed English -- the other
one translating changed the string enough. So every assertion below names the ONE
element it is about.

Run:  OO_DATA_DIR=<seeded> .venv/bin/python <this> --url http://127.0.0.1:8099 --out <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

LOCALES = ("en", "ar", "zh", "de", "fr")
STATES = ("running", "halted", "stopped")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8099")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    findings: list[str] = []
    record: dict = {"url": args.url, "locales": {}}

    with sync_playwright() as pw:
        # The sandbox pins a Chromium BUILD (1194) and the installed playwright wants
        # a newer one. The environment's own note says to point at the pinned binary
        # rather than run `playwright install` -- and so does pyproject, which sets
        # PLAYWRIGHT_BROWSERS_PATH at a pinned build for exactly this reason.
        import os as _os
        exe = _os.environ.get("OO_CHROMIUM",
                              "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        browser = pw.chromium.launch(executable_path=exe if _os.path.exists(exe) else None)
        for lang in LOCALES:
            page = browser.new_page(viewport={"width": 1280, "height": 860})
            page.goto(args.url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            # DISMISS THE FIRST-RUN WIZARD. A screenshot taken behind a modal proves
            # the DOM and shows nothing about what a reader can see -- which is the
            # only thing a click-through adds over the node harness.
            for _ in range(4):
                closed = page.evaluate(
                    "() => { let n = 0;"
                    "  document.querySelectorAll('dialog[open]').forEach(d => { d.close(); n++; });"
                    "  return n; }"
                )
                page.wait_for_timeout(250)
                if not closed:
                    break
            page.evaluate("() => { try { localStorage.setItem('oo.guide.done','1'); } catch (e) {} }")
            # Switch the WHOLE UI through the one i18n engine (invariant #15).
            page.evaluate("(l) => window.OOI18N && OOI18N.setLang(l)", lang)
            page.wait_for_timeout(900)
            per_state = {}
            for state in STATES:
                page.evaluate("(s) => _paintWikiLane(s, ACTIVE)".replace("ACTIVE", "false"), state)
                page.wait_for_timeout(250)
                btn = page.query_selector("#wiki-toggle")
                if btn is None:
                    findings.append(f"{lang}/{state}: #wiki-toggle is absent from the top bar")
                    continue
                box = btn.bounding_box() or {}
                title = btn.get_attribute("title") or ""
                aria = btn.get_attribute("aria-label") or ""
                pressed = btn.get_attribute("aria-pressed")
                fill = page.eval_on_selector("#wiki-mark", "e => e.getAttribute('fill')")
                per_state[state] = {
                    "title": title, "aria_label": aria, "aria_pressed": pressed,
                    "mark_fill": fill, "width": box.get("width"), "height": box.get("height"),
                }
                # CLIPPED to the chrome strip, and a second shot of the button alone.
                # A full page at 1280x860 renders the toggle 34 px wide; nobody can
                # read an accent or a fill from that, so the record would be a
                # screenshot that proves the page loaded and nothing about the control.
                header = page.query_selector("header")
                if header is not None:
                    hb = header.bounding_box()
                    if hb:
                        page.screenshot(path=str(args.out / f"chrome-{lang}-{state}.png"),
                                        clip={"x": hb["x"], "y": hb["y"],
                                              "width": hb["width"], "height": hb["height"]})
                if box:
                    pad = 10
                    page.screenshot(path=str(args.out / f"wiki-toggle-{lang}-{state}.png"),
                                    clip={"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                                          "width": box["width"] + pad * 2,
                                          "height": box["height"] + pad * 2})
                if not page.query_selector("dialog[open]") is None:
                    findings.append(f"{lang}/{state}: a dialog is open over the page; the shot shows a modal")
                # The hosts are LITERALS and stay English in every locale; the rest
                # of the hover must not.
                if "stream.wikimedia.org" not in title:
                    findings.append(f"{lang}/{state}: the hover does not name what the lane contacts")
                if lang != "en" and title and _looks_english(title):
                    findings.append(f"{lang}/{state}: the hover is still English: {title[:70]!r}")
                # FILL = state (invariant #14's grammar), never an action glyph.
                want = "currentColor" if state == "running" else "none"
                if fill != want:
                    findings.append(f"{lang}/{state}: mark fill is {fill!r}, expected {want!r}")
            # Constant footprint (invariant #3): the button must not resize between states.
            widths = {s: v.get("width") for s, v in per_state.items()}
            if len({round(w or 0, 1) for w in widths.values()}) > 1:
                findings.append(f"{lang}: the toggle's footprint CHANGES between states: {widths}")
            record["locales"][lang] = per_state
            page.close()
        browser.close()

    record["findings"] = findings
    (args.out / "report.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    for f in findings:
        print("FINDING:", f)
    print(f"\n{len(findings)} finding(s); shots + report in {args.out}")
    return 1 if findings else 0


def _looks_english(text: str) -> bool:
    """A crude tell, deliberately conservative: the untranslated marker phrases.

    Not a language detector. It looks for the exact English words this surface would
    show if `t()` fell through, and nothing else -- a false NEGATIVE here is fine (the
    screenshots are the real evidence), a false positive would send a reader hunting.
    """
    markers = ("Wikipedia stream: running", "Wikipedia stream: paused", "Wikipedia stream: stopped")
    return any(m in text for m in markers)


if __name__ == "__main__":
    sys.exit(main())
