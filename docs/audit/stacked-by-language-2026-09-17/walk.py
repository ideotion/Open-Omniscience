#!/usr/bin/env python3
"""Q502's stacked bands and Q417's aggregate hover, rendered — Chromium (`S04-07` PR 5).

Q1128 = a's bar is *Chromium in the sandbox + the maintainer's own click-through*; this is
the first half only, and the honest stamp is "Chromium-verified (remote sandbox) · awaiting
human UX pass".

WHY A RENDERED PAGE AND NOT THE NODE SUITES. ``tests/stacked_series_node_test.js`` drives
the stack's arithmetic, its five refusals and its two-dimensional hit test as real code,
and ``tests/term_bars_hover_node_test.js`` drives the hover string. Neither can see the
three things this slice actually risks:

  1. The stack is the FIRST thing ``ooChart`` draws that is not a line, and a canvas that
     paints nothing still passes every source assertion ever written about it. So the
     pixels are read back: the canvas must contain more than one band colour, and a
     blank one is a failure with a number attached.
  2. The hit test is verified as arithmetic in node against a y-projection this file
     writes. Here it runs against the REAL projection ``draw()`` built, at the real
     device-pixel ratio, from a real pointer event -- which is the only place the two
     can disagree.
  3. An RTL or CJK locale clipping the legend, the totals line or the long caveat, and
     the i18n walker leaving one of the ten new strings in English on screen although
     its key is in all twelve files.

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


def _open_trend(page, lg: str) -> None:
    """Land on the analysis window's Trend subtab in `lg`, from a clean tab workspace."""
    page.goto(URL, wait_until="domcontentloaded")
    page.evaluate("(c) => localStorage.setItem('oo.lang', c)", lg)
    # A tab persisted by the previous locale would re-seed its own lens and view mode,
    # and this walk would be measuring the run before it.
    page.evaluate("() => localStorage.removeItem('oo.an.tabs.v1')")
    page.goto(f"{URL}/?analyze={TERM}", wait_until="domcontentloaded")
    page.wait_for_selector("#an-subtabs button[data-tab='trend']", timeout=30000)
    page.evaluate("() => { if (window._anSubtabs) _anSubtabs.select('trend'); else anSelectTab('trend'); }")
    # The Trend tab fetches; WAIT for the mode row rather than settling for a fixed
    # delay, or the first locale walked reports an empty panel as the result.
    page.wait_for_selector("#an-trend-chart canvas", timeout=60000)


def _canvas_bands(page) -> dict:
    """Read the PIXELS back. A canvas that painted nothing satisfies every source test.

    Counts distinct opaque colours over a coarse grid. A stack of N languages paints at
    least two band fills plus the axis ink; a blank canvas returns 0 and a single-colour
    one returns 1, and both are failures with a number attached rather than a feeling.
    """
    return page.evaluate(
        """() => {
          const cv = document.querySelector('#an-trend-chart canvas');
          if (!cv) return {error: 'no canvas'};
          const ctx = cv.getContext('2d');
          const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
          const seen = new Map();
          for (let y = 0; y < cv.height; y += 3) {
            for (let x = 0; x < cv.width; x += 3) {
              const i = (y * cv.width + x) * 4;
              if (d[i + 3] < 24) continue;
              const k = (d[i] >> 4) + ',' + (d[i + 1] >> 4) + ',' + (d[i + 2] >> 4);
              seen.set(k, (seen.get(k) || 0) + 1);
            }
          }
          // Ink that covers a real AREA, so antialiasing along one line cannot be
          // mistaken for a second band.
          const solid = [...seen.entries()].filter(([, n]) => n >= 40);
          return {w: cv.width, h: cv.height, distinct: seen.size, area_colours: solid.length,
                  painted: [...seen.values()].reduce((a, b) => a + b, 0)};
        }"""
    )


def _hover_readout(page, frac_x: float, frac_y: float) -> str:
    """Point at (frac of plot width, frac of plot height) and read the live readout.

    This is the assertion the node suite cannot make: the pick runs against the
    projection `draw()` actually built, at the real device-pixel ratio.
    """
    box = page.evaluate(
        """() => { const cv = document.querySelector('#an-trend-chart canvas');
           const r = cv.getBoundingClientRect();
           return {x: r.left, y: r.top, w: r.width, h: r.height}; }"""
    )
    page.mouse.move(box["x"] + box["w"] * frac_x, box["y"] + box["h"] * frac_y)
    page.wait_for_timeout(250)
    # `ooChart` appends its readout as the LAST `.hint` inside the host (the totals line
    # this view prints is a SIBLING of the host, not a child, so it cannot be mistaken
    # for it). Read by structure rather than by a class name of its own, because the
    # toolkit gives it none.
    return page.evaluate(
        """() => { const hs = document.querySelectorAll('#an-trend-chart .hint');
           return hs.length ? hs[hs.length - 1].textContent.trim() : ''; }"""
    )


def walk_locale(page, lg: str, out: Path) -> dict:
    r: dict = {"locale": lg}
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))
    _open_trend(page, lg)
    r["dir"] = page.evaluate("() => document.documentElement.getAttribute('dir') || 'ltr'")
    r["lang_applied"] = page.evaluate("() => (window.OOI18N && OOI18N.current()) || '?'")

    # --- the view is offered at all -------------------------------------------------
    modes = page.query_selector_all("#an-trend button.ghost.tiny, #an-trend-body button.ghost.tiny")
    if not modes:
        modes = page.query_selector_all("#an-trend-chart ~ * button")
    bylang = page.evaluate(
        """() => { const bs = [...document.querySelectorAll('button')]
             .filter(b => /anTrendSetMode\\('bylang'\\)/.test(b.getAttribute('onclick') || ''));
           return bs.length ? bs[0].textContent.trim() : null; }"""
    )
    r["bylang_button_label"] = bylang
    r["bylang_offered"] = bylang is not None
    if not r["bylang_offered"]:
        r["errors"] = errs[:5]
        return r
    # An English label on a translated page is the failure the i18n gates cannot see.
    r["bylang_label_is_english"] = (lg != "en" and bylang == "By language")

    # --- switch to it ---------------------------------------------------------------
    page.evaluate("() => anTrendSetMode('bylang')")
    page.wait_for_selector("#an-trend-chart canvas", timeout=30000)
    page.wait_for_timeout(700)
    r["pixels"] = _canvas_bands(page)
    r["refusal"] = page.evaluate(
        "() => { const e = document.getElementById('an-trend-chart');"
        " return (e && e.dataset && e.dataset.stackRefusal) || null; }"
    )
    r["refusal_line"] = page.evaluate(
        "() => { const e = document.getElementById('an-trend-refusal');"
        " return e ? e.textContent.trim() : null; }"
    )
    # The totals line and the caveat, read back as the reader sees them.
    r["totals_line"] = page.evaluate(
        "() => { const e = document.querySelector('#an-trend-chart + .hint');"
        " return e ? e.textContent.trim().slice(0, 300) : ''; }"
    )
    r["caveat_line"] = page.evaluate(
        "() => { const e = document.querySelector('#an-trend-chart ~ .card-caveat');"
        " return e ? e.textContent.trim().slice(0, 400) : ''; }"
    )
    r["caveat_is_english"] = (lg != "en" and r["caveat_line"].startswith("Bands are mention counts"))

    # --- the hit test, against the projection `draw()` actually built ----------------
    # Two points at the SAME x and different heights. If the pick were time-only they
    # would report the same band, which is the defect this slice fixed.
    r["hover_low"] = _hover_readout(page, 0.55, 0.92)
    r["hover_high"] = _hover_readout(page, 0.55, 0.30)
    r["hover_separates_bands"] = bool(
        r["hover_low"] and r["hover_high"] and r["hover_low"] != r["hover_high"]
    )

    # --- overflow at this width, in this direction ----------------------------------
    r["overflow_px"] = page.evaluate(
        "() => { const e = document.getElementById('an-trend') || document.body;"
        " return Math.max(0, e.scrollWidth - e.clientWidth); }"
    )
    page.screenshot(path=str(out / f"stacked-{lg}.png"), full_page=False)
    r["errors"] = errs[:5]
    return r


def walk_aggregate_hover(page, lg: str, out: Path) -> dict:
    """Q417: the per-language breakdown on the Insights term-bar rows."""
    r: dict = {"locale": lg, "surface": "insights-trends"}
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))
    page.goto(URL, wait_until="domcontentloaded")
    page.evaluate("(c) => localStorage.setItem('oo.lang', c)", lg)
    page.goto(f"{URL}/?tab=insights", wait_until="domcontentloaded")
    # `?tab=` seeds the boot, but the subtab NAV is inside the panel and stays hidden
    # until the main tab is actually shown -- so the first version of this walk waited
    # thirty seconds on a button that was in the DOM the whole time.
    page.wait_for_function("() => typeof showTab === 'function'", timeout=30000)
    page.evaluate("() => showTab('insights')")
    page.wait_for_selector("#ins-subtabs button[data-tab='trends']", state="visible", timeout=30000)
    # CLICKED, not called: `_insSubtabs` is a module-level `let`, which in a classic
    # script is NOT a window property -- so a walk that reaches for `window._insSubtabs`
    # silently does nothing and then reports zero rows as if the surface were empty.
    page.click("#ins-subtabs button[data-tab='trends']")
    try:
        page.wait_for_selector("#trd-rising a.tb-label, #trd-top a.tb-label", timeout=60000)
    except Exception:  # noqa: BLE001 - recorded as zero rows, never papered over
        r["rows"] = 0
        r["errors"] = errs[:5]
        return r
    titles = page.evaluate(
        """() => [...document.querySelectorAll('#trd-rising a.tb-label, #trd-top a.tb-label')]
             .map(a => ({term: a.textContent.trim(), title: a.getAttribute('title') || ''}))"""
    )
    r["rows"] = len(titles)
    r["rows_with_breakdown"] = sum(1 for x in titles if _looks_like_breakdown(x["title"]))
    r["sample_with"] = next((x for x in titles if _looks_like_breakdown(x["title"])), None)
    r["sample_without"] = next((x for x in titles if not _looks_like_breakdown(x["title"])), None)
    # NEITHER extreme is the shipped behaviour: a breakdown on every row would train the
    # reader to ignore the one that means something, and none at all is the unread
    # payload this slice exists to surface.
    r["breakdown_is_selective"] = 0 < r["rows_with_breakdown"] < r["rows"]
    # THE BUBBLE ITSELF, through the ONE #oo-tip convention (invariant #17). These rows
    # also carry `data-kwstat`, so the keyword-stats handler fetches live stats and
    # OVERWRITES both the title and the bubble text -- which is how the first version of
    # this slice lost the breakdown after one hover. So the bubble is read back, on the
    # row that HAS a breakdown, and the breakdown must still be in it.
    #
    # `offsetParent` is not the visibility test here: `#oo-tip` is positioned `fixed`, and
    # a fixed element's offsetParent is null even when it is on screen. The first version
    # of this walk used it and reported an empty bubble that was in fact open and painted.
    target = None
    for handle in page.query_selector_all("#trd-rising a.tb-label, #trd-top a.tb-label"):
        if handle.get_attribute("data-oo-tip-extra"):
            target = handle
            break
    r["row_with_extra_found"] = target is not None
    row = target or page.query_selector("#trd-rising a.tb-label, #trd-top a.tb-label")
    if row:
        # `row.hover()` rather than a hand-computed `mouse.move`: it scrolls the row into
        # view and waits for it to be actionable. The hand-computed version read an empty
        # bubble on a row that was off screen, which reads as "the convention does not
        # fire" and is really "the pointer was somewhere else".
        row.scroll_into_view_if_needed()
        row.hover()
        # The stats are a real fetch, so WAIT for the bubble to stop saying "Loading…"
        # rather than settling for a delay that measures the placeholder.
        # The stats behind the bubble are a real fetch, so give it room and then read the
        # bubble's FULL state -- class, computed style and text together. An empty string
        # on its own cannot be told apart from "the convention did not fire", and this
        # walk has already produced one of those for a reason that was not the product.
        page.wait_for_timeout(3000)
        r["oo_tip"] = page.evaluate(
            """() => { const e = document.getElementById('oo-tip');
                 if (!e) return {present: false};
                 const cs = getComputedStyle(e);
                 return {present: true, show: e.classList.contains('show'),
                         display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
                         text: e.textContent.trim().slice(0, 500)}; }"""
        )
        tip = r["oo_tip"]
        r["oo_tip_text"] = tip.get("text", "") if tip.get("show") else ""
        r["oo_tip_carries_breakdown"] = bool(_looks_like_breakdown_text(r.get("oo_tip_text", "")))
        # ...and the same read on the KEYBOARD path, which is the half a mouse tooltip
        # cannot serve and the half invariant #17 exists for.
        row.focus()
        page.wait_for_timeout(900)
        r["oo_tip_on_focus"] = page.evaluate(
            "() => { const e = document.getElementById('oo-tip');"
            " return e && e.classList.contains('show') ? e.textContent.trim().slice(0, 500) : ''; }"
        )
        r["oo_tip_on_focus_carries_breakdown"] = bool(
            _looks_like_breakdown_text(r.get("oo_tip_on_focus", ""))
        )
    page.screenshot(path=str(out / f"aggregate-hover-{lg}.png"), full_page=False)
    r["errors"] = errs[:5]
    return r


def _looks_like_breakdown_text(text: str) -> bool:
    """The breakdown inside a composed bubble line, without matching an English sentence.

    The stats handler joins its own clauses with the same middot the breakdown uses, so
    the shape that identifies it is the LAST em-dash clause holding name+number pairs --
    the same rule as `_looks_like_breakdown`, applied to a longer string.
    """
    parts = text.split(" \u2014 ")
    return len(parts) >= 2 and "\u00b7" in parts[-1] and any(c.isdigit() for c in parts[-1])


def _looks_like_breakdown(title: str) -> bool:
    """A breakdown is the third em-dash clause; in `en` it is named, elsewhere it is not.

    Matching the English sentence would report zero on every translated page and read as
    a missing feature. What is language-independent is the SHAPE: a third clause holding
    a middot-separated list of name+number pairs.
    """
    parts = title.split(" \u2014 ")
    return len(parts) >= 3 and any(ch.isdigit() for ch in parts[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"url": URL, "term": TERM, "locales": [], "aggregate_hover": []}
    with sync_playwright() as pw:
        # The sandbox ships Chromium at a build this playwright release does not expect,
        # so the binary is named rather than downloaded (OO_WALK_CHROME overrides).
        exe = os.environ.get("OO_WALK_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        browser = pw.chromium.launch(executable_path=exe if Path(exe).exists() else None)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for lg in LOCALES:
            report["locales"].append(walk_locale(page, lg, out))
        for lg in ("en", "ar"):
            report["aggregate_hover"].append(walk_aggregate_hover(page, lg, out))
        browser.close()
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
