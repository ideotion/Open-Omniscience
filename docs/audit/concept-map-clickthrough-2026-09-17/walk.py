#!/usr/bin/env python3
"""Q510 + Q512 rendered — Chromium in the remote sandbox (`S04-07` PR 3).

Two surfaces the node suites cannot see: the mind map's Concept view (an SVG whose
geometry is measured in ``tests/concept_tree_node_test.js`` but whose LABELS have to
survive four scripts at a fixed canvas size) and the Watches panel's ring disclosure.

Q1128 = a's bar is Chromium in the sandbox PLUS the maintainer's own click-through; this
is the first half only.

Usage: OO_WALK_URL=http://127.0.0.1:8010 .venv/bin/python walk.py --out .

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


def walk_concept(page, lg: str, out: Path) -> dict:
    r: dict = {"locale": lg}
    page.goto(URL, wait_until="domcontentloaded")
    page.evaluate("(c) => { localStorage.setItem('oo.lang', c); "
                  "localStorage.removeItem('oo.an.tabs.v1'); }", lg)
    page.goto(f"{URL}/?analyze={TERM}", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    page.evaluate("() => { if (typeof _anSubtabs !== 'undefined' && _anSubtabs) "
                  "_anSubtabs.select('mindmap'); else anSelectTab('mindmap'); }")
    # WAIT for the surface, never a fixed delay: the first locale walked pays the cold
    # start (the graph and the concept map are two live queries), and a settle tuned on
    # the second locale measured an empty panel and called it "no Concept button".
    try:
        page.wait_for_selector("#an-mindmap button.ghost.tiny", timeout=45000)
    except Exception:  # noqa: BLE001 - recorded as absent, never papered over
        pass
    page.wait_for_timeout(1200)
    r["dir"] = page.evaluate("() => document.documentElement.getAttribute('dir') || 'ltr'")
    # The Concept BUTTON exists only when the term is in a ring the corpus carries more
    # than one form of -- so its presence is itself the first measurement.
    btns = page.query_selector_all("#an-mindmap button.ghost.tiny")
    r["view_buttons"] = [b.inner_text().strip() for b in btns]
    target = None
    for b in btns:
        # `concept:TRUE`, not merely "concept": the MAP button's handler is
        # `anMMset({cloud:false,concept:false})`, so a substring match on "concept"
        # clicks Map and the walk then measures the radial map while reporting it as the
        # Concept view -- which is exactly what the first run of this script did.
        if "concept:true" in (b.get_attribute("onclick") or "").replace(" ", ""):
            target = b
            break
    r["concept_button_present"] = target is not None
    if target is not None:
        target.click()
        page.wait_for_timeout(2000)
        r["arms"] = page.evaluate(
            "() => [...document.querySelectorAll('#an-mindmap svg text')]"
            ".map(e => e.textContent.trim())"
        )
        r["edges"] = page.evaluate(
            "() => document.querySelectorAll('#an-mindmap svg line').length"
        )
        r["omitted_line"] = page.evaluate(
            "() => { const d = [...document.querySelectorAll('#an-mindmap .hint.muted')];"
            " return d.length ? d[0].textContent.trim().slice(0, 160) : ''; }"
        )
        r["caption"] = page.evaluate(
            "() => { const d = [...document.querySelectorAll('#an-mindmap .hint.muted')];"
            " return d.length ? d[d.length - 1].textContent.trim().slice(0, 260) : ''; }"
        )
        # Labels drawn OUTSIDE the canvas are the failure this surface actually risks: an
        # SVG does not clip its text, so a long arm label simply leaves the picture.
        r["labels_outside_canvas"] = page.evaluate(
            "() => { const s = document.querySelector('#an-mindmap svg');"
            " if (!s) return null; const b = s.getBoundingClientRect(); let n = 0;"
            " s.querySelectorAll('text').forEach(e => { const r = e.getBoundingClientRect();"
            "   if (r.left < b.left - 1 || r.right > b.right + 1 || r.top < b.top - 1"
            "       || r.bottom > b.bottom + 1) n++; }); return n; }"
        )
        page.screenshot(path=str(out / f"concept-{lg}.png"))
    return r


def walk_watches(page, lg: str, out: Path) -> dict:
    """The watch row's ring disclosure — created through the real API, then read back."""
    r: dict = {"locale": lg}
    page.goto(URL, wait_until="domcontentloaded")
    page.evaluate("(c) => localStorage.setItem('oo.lang', c)", lg)
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.evaluate(
        "async () => { const r = await fetch('/api/watches');"
        " const d = await r.json();"
        " if (!(d.watches || []).some(w => w.query === 'climate'))"
        "   await fetch('/api/watches', {method: 'POST',"
        "     headers: {'Content-Type': 'application/json'},"
        "     body: JSON.stringify({name: 'Climate', query: 'climate',"
        "       threshold: 2, window_days: 30})}); }"
    )
    page.evaluate("() => showTab('insights')")
    page.wait_for_timeout(1200)
    page.evaluate("() => { if (typeof _insSubtabs !== 'undefined' && _insSubtabs) "
                  "_insSubtabs.select('watches'); else showInsightCat('watches'); }")
    page.wait_for_timeout(2500)
    try:
        page.wait_for_selector("#wt-list .card", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    r["rows"] = page.evaluate("() => document.querySelectorAll('#wt-list .card').length")
    r["ring_note"] = page.evaluate(
        "() => { const c = [...document.querySelectorAll('#wt-list .card')]"
        "   .find(x => x.textContent.includes('climate'));"
        " if (!c) return ''; const h = [...c.querySelectorAll('.hint')].pop();"
        " return h ? h.textContent.trim().slice(0, 200) : ''; }"
    )
    r["panel_caveat"] = page.evaluate(
        "() => { const d = [...document.querySelectorAll('#wt-list > .hint')];"
        " return d.length ? d[d.length - 1].textContent.trim().slice(0, 200) : ''; }"
    )
    page.screenshot(path=str(out / f"watches-{lg}.png"))
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"url": URL, "term": TERM, "concept": [], "watches": []}
    exe = os.environ.get("OO_WALK_CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe if Path(exe).exists() else None)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for lg in LOCALES:
            report["concept"].append(walk_concept(page, lg, out))
        for lg in ("en", "ar"):
            report["watches"].append(walk_watches(page, lg, out))
        browser.close()
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
