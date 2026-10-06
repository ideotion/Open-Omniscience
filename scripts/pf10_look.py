#!/usr/bin/env python3
"""
pf10_look -- the 390 px look at PF10 on every ``ooMap`` surface (0.5 gate row I).

PF10 = a: below 600 px the in-map control groups collapse into ONE in-map button that opens them.
The change shipped (PR #1253) with a Chromium check of the world-map tab only. This visits every tab
and subtab, finds each map host that carries the toggle (``[data-oomap-ctl]``), and records, per
surface and per theme given:

  * closed: the toggle is visible, the controls panel is hidden, and the share of the map the
    controls cover (the 2026-09-16 measure was 79 % with the groups open, 112 % with the worldview
    picker);
  * opened: ``aria-expanded`` flips to true, the panel is visible, and where it sits (over the map,
    or stacked below it);
  * every drop-down in the opened panel: another option is picked and the sweep's own judgement
    (held / effect) is recorded, exactly as ``csp_sweep.py`` does it;
  * closed again: the panel is hidden once more;
  * the console text, CSP violations included.

Run against a booted app:  .venv/bin/python scripts/pf10_look.py --url http://127.0.0.1:8011 --out DIR

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from csp_sweep import _INIT, sweep_selects  # noqa: E402

_HOSTS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  return [...document.querySelectorAll('[data-oomap-ctl]')].filter(vis).map((t, i) => (
    {i, label: (t.textContent || '').trim(), expanded: t.getAttribute('aria-expanded')}));
}
"""

_MEASURE = r"""
i => {
  const vis0 = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const t = [...document.querySelectorAll('[data-oomap-ctl]')].filter(vis0)[i];
  const host = t.closest('.oomap-host, .oomap, [data-oomap]') || t.parentElement.parentElement;
  const panel = host.querySelector('.oomap-panel');
  const svg = host.querySelector('svg, canvas');
  const r = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.x, y: b.y, w: b.width, h: b.height}; };
  const vis = e => !!e && getComputedStyle(e).display !== 'none' && (e.offsetWidth || e.offsetHeight) > 0;
  const map = r(svg), p = r(panel), tg = r(t);
  const inter = (a, b) => { if (!a || !b) return 0;
    const w = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
    const h = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)); return w * h; };
  const area = map ? map.w * map.h : 0;
  return {toggle_visible: vis(t), expanded: t.getAttribute('aria-expanded'), panel_visible: vis(panel),
          map: map, panel: p, toggle: tg,
          panel_covers_map_pct: area ? Math.round(100 * inter(p, map) / area) : null,
          toggle_covers_map_pct: area ? Math.round(100 * inter(tg, map) / area) : null,
          panel_below_map: !!(p && map && p.y >= map.y + map.h - 1)};
}
"""


def look(page, where: str, theme: str, out: list, console: list) -> None:
    hosts = page.evaluate(_HOSTS)
    for h in hosts:
        row = {"surface": where, "theme": theme, "toggle_text": h["label"]}
        try:
            row["closed"] = page.evaluate(_MEASURE, h["i"])
            tog = page.locator("[data-oomap-ctl]:visible").nth(h["i"])
            tog.scroll_into_view_if_needed(timeout=3000)
            tog.click(timeout=3000)
            page.wait_for_timeout(500)
            row["opened"] = page.evaluate(_MEASURE, h["i"])
            picks: list = []
            sweep_selects(page, f"{where} (map panel)", picks, console.append, set())
            row["panel_selects"] = [p for p in picks if "map panel" in p["where"]]
            tog.click(timeout=3000)
            page.wait_for_timeout(400)
            row["closed_again"] = page.evaluate(_MEASURE, h["i"])
            c, o, a = row["closed"], row["opened"], row["closed_again"]
            row["verdict"] = {
                "closed_hides_panel": bool(c["toggle_visible"] and not c["panel_visible"]),
                "open_flips_aria": o["expanded"] == "true",
                "open_shows_panel": bool(o["panel_visible"]),
                "closes_again": not a["panel_visible"] and a["expanded"] == "false",
            }
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        out.append(row)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--theme", action="append", default=None)
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    themes = a.theme or ["ink"]
    rows: list = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        ctx = b.new_context(viewport={"width": 390, "height": 844})
        ctx.add_init_script(_INIT)
        page = ctx.new_page()
        console: list[str] = []
        page.on("console", lambda m: console.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: console.append(f"[pageerror] {e}"))
        page.on("dialog", lambda d: d.dismiss())
        page.goto(a.url, wait_until="load")
        page.wait_for_timeout(1500)
        names = page.evaluate(
            "() => [...new Set([...document.querySelectorAll('[id^=\"tab-\"]')].map(e => e.id.slice(4)))]"
            ".filter(n => n !== 'search' && n !== 'analyze')")
        for theme in themes:
            page.evaluate("t => setTheme(t)", theme)
            for name in names:
                page.evaluate("n => showTab(n)", name)
                page.wait_for_timeout(1500)  # a map paints after its data arrives
                look(page, name, theme, rows, console)
                subs = page.evaluate(
                    "() => { document.querySelectorAll('[data-sweep-sub]').forEach(e => e.removeAttribute('data-sweep-sub'));"
                    " return [...document.querySelectorAll('.subtab-strip [data-tab]')].filter(b => b.offsetWidth || b.offsetHeight)"
                    ".map((b, i) => { b.setAttribute('data-sweep-sub', String(i)); return {i, t: b.dataset.tab}; }); }")
                for sub in subs:
                    try:
                        page.locator(f'[data-sweep-sub="{sub["i"]}"]').first.click(timeout=2000)
                        page.wait_for_timeout(1500)
                        look(page, f"{name} > {sub['t']}", theme, rows, console)
                    except Exception as exc:  # noqa: BLE001
                        rows.append({"surface": f"{name} > {sub['t']}", "theme": theme, "error": f"subtab: {str(exc)[:120]}"})
        csp = page.evaluate("() => window.__csp")
        b.close()
    (out_dir / "pf10-390.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    csp_console = [c for c in console if re.search(r"content security policy|refused to", c, re.I)]
    (out_dir / "pf10-390-console.txt").write_text(
        f"# CSP violation events: {json.dumps(csp)}\n# CSP lines in the console: {len(csp_console)}\n"
        + ("\n".join(console) if console else "(no console errors or warnings)") + "\n", encoding="utf-8")
    ok = [r for r in rows if "verdict" in r and all(r["verdict"].values())]
    print(f"{len(rows)} map surfaces with the toggle; {len(ok)} passed every check; csp events {len(csp)}")
    for r in rows:
        v = r.get("verdict")
        print(" ", r["surface"], "OK" if v and all(v.values()) else (r.get("error") or v))
    return 0 if len(ok) == len(rows) and not csp and not csp_console else 1


if __name__ == "__main__":
    sys.exit(main())
