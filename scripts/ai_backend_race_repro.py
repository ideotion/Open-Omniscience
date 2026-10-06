#!/usr/bin/env python3
"""
ai_backend_race_repro -- the Settings "AI backend" drop-down reverting under a slow load, in Chromium.

The row I walk found ``#ai-backend-select`` flipping back to its stored value (12 REVERTED rows of
the 45-run sweep). The cause is a race: ``loadAiBackendPanel`` writes the select from the server's
stored value, and a load that STARTED before the operator's pick answers after it. This script
reproduces both shapes against ONE booted app by serving each VARIANT of ``app-ai-tools.js`` to the
page through a Playwright route, so "before" and "after" run the same browser, app and delays:

  * ``one-pick``  -- the first ``GET /api/llm/backend`` (a load already in flight) answers 1.2 s late,
                     the operator picks another backend meanwhile. The select is read every 250 ms
                     for 3.5 s; every reading must be the pick.
  * ``two-picks`` -- two picks in the same tick, the second save held back 0.8 s, so the reload that
                     follows the first save reads the server BEFORE the second save landed. After the
                     picks settle the select must show the SECOND pick.

Variants are ``label=path`` pairs (``git show <commit>:src/static/app-ai-tools.js > file`` makes one);
without any, only the served file is run. The backend setting is put back to its starting value.

Run:  .venv/bin/python scripts/ai_backend_race_repro.py --url http://127.0.0.1:8012 \\
          --variant main=/tmp/main.js --variant picks-only=/tmp/ae85fdaf.js --variant fixed=src/static/app-ai-tools.js

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

_DELAYS = r"""
([delayBackendLoads, delayPutAt]) => {
  const of = window.fetch; let loads = 0, puts = 0;
  window.fetch = async (u, o) => {
    const url = String(u), method = ((o && o.method) || 'GET').toUpperCase();
    if (url.includes('/api/settings') && method === 'PUT' && delayPutAt.includes(++puts))
      await new Promise(r => setTimeout(r, 800));
    const r = await of(u, o);
    if (url.includes('/api/llm/backend') && method === 'GET' && delayBackendLoads.includes(++loads))
      await new Promise(r2 => setTimeout(r2, 1200));
    return r;
  };
}
"""


def run_variant(browser, url: str, label: str, js: str | None) -> dict:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    if js is not None:
        body = Path(js).read_text(encoding="utf-8")
        page.route("**/static/app-ai-tools.js*", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=body))
    page.goto(url, wait_until="load")
    page.wait_for_timeout(1500)
    page.evaluate("showTab('settings')")
    page.wait_for_timeout(300)
    page.evaluate("() => { const b = document.querySelector('[data-tab=models]'); if (b) b.click(); }")
    page.evaluate("document.querySelectorAll('#set-models details').forEach(d => d.open = true)")
    page.evaluate("loadAiBackendPanel()")
    page.wait_for_selector("#ai-backend-select", timeout=5000)
    sel = page.locator("#ai-backend-select")
    opts = sel.evaluate("e => [...e.options].map(o => o.value)")
    start = page.evaluate("async () => (await (await fetch('/api/llm/backend')).json()).stored_override || 'auto'")
    others = [v for v in opts if v != start]
    out: dict = {"variant": label, "options": opts, "stored_at_start": start}

    # one pick, a load already in flight
    page.evaluate(_DELAYS, [[1], []])
    page.evaluate("void loadAiBackendPanel()")
    page.wait_for_timeout(100)
    pick = others[0]
    sel.select_option(pick)
    seen = []
    for _ in range(14):
        page.wait_for_timeout(250)
        seen.append(sel.input_value())
    out["one_pick"] = {"picked": pick, "readings": seen, "held": all(v == pick for v in seen)}
    page.close()

    # two picks in one tick, the second save held back
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    if js is not None:
        page.route("**/static/app-ai-tools.js*", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=body))
    page.goto(url, wait_until="load")
    page.wait_for_timeout(1500)
    page.evaluate("showTab('settings')")
    page.wait_for_timeout(300)
    page.evaluate("() => { const b = document.querySelector('[data-tab=models]'); if (b) b.click(); }")
    page.evaluate("document.querySelectorAll('#set-models details').forEach(d => d.open = true)")
    page.evaluate("loadAiBackendPanel()")
    page.wait_for_selector("#ai-backend-select", timeout=5000)
    sel = page.locator("#ai-backend-select")
    cur = sel.input_value()
    others = [v for v in opts if v != cur]
    p1, p2 = others[0], others[1] if len(others) > 1 else others[0]
    page.evaluate(_DELAYS, [[], [2]])
    page.evaluate(
        "([a, b]) => { const s = document.getElementById('ai-backend-select');"
        " s.value = a; void setAiBackend(a); s.value = b; void setAiBackend(b); }", [p1, p2])
    seen = []
    for _ in range(16):
        page.wait_for_timeout(250)
        seen.append(sel.input_value())
    stored = page.evaluate("async () => (await (await fetch('/api/llm/backend')).json()).stored_override || 'auto'")
    out["two_picks"] = {"picked": [p1, p2], "readings": seen, "stored_after": stored,
                        "held_second_pick_throughout": all(v == p2 for v in seen), "stored_is_second_pick": stored == p2}
    page.evaluate("v => api('/api/settings', {method: 'PUT', body: JSON.stringify({llm_backend: v})})", start)
    page.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--variant", action="append", default=[], help="label=path of an app-ai-tools.js to serve")
    a = ap.parse_args()
    if not a.url.startswith(("http://127.0.0.1", "http://localhost")):
        raise SystemExit("refusing a non-loopback --url")
    variants = [(v.split("=", 1)[0], v.split("=", 1)[1]) for v in a.variant] or [("served", None)]
    results = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for label, js in variants:
            results.append(run_variant(b, a.url, label, js))
        b.close()
    print(json.dumps(results, indent=1))
    last = results[-1]
    return 0 if last["one_pick"]["held"] and last["two_picks"]["held_second_pick_throughout"] and last["two_picks"]["stored_is_second_pick"] else 1


if __name__ == "__main__":
    sys.exit(main())
