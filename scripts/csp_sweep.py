#!/usr/bin/env python3
"""
csp_sweep -- the 0.5 row I closing sweep: every drop-down, every theme, three widths, console read.

The gate's own clause (RELEASE_0.5_GATE.md row I): the CSP change (``script-src 'self'``) is
Chromium-verified across the named themes at the widths of the 2026-09-09 axe sweep
(1440x900, 768x1024, 390x844). The coordinator's brief for the sweep: at each width and in each
theme, open every drop-down, pick an option, confirm it takes effect, and read the console for CSP
violations, keeping the console text per width and theme with the record.

WHAT "TAKES EFFECT" MEANS HERE, STATED SO THE RECORD CANNOT OVERSTATE IT. For each visible
``<select>`` the sweep picks an option other than the current one and then checks, 400 ms later:

  * ``held``    -- the select, READ BACK from where it is now (by its id, or its panel's id plus its
                   index), still shows the picked value. A handler that reverted it is a broken
                   binding (``REVERTED``); a select that is gone or was rebuilt with other options
                   cannot be read back, and is ``unread`` -- never counted as held. ``held`` shows
                   that the pick STUCK; it does not show the pick did anything.
  * ``effect``  -- what the pick visibly did beyond what the page does on its own in the same
                   400 ms (measured first as ``idle_net`` / ``idle_mut``): ``dom`` (more DOM
                   mutations than idle), ``net`` (more requests to this app than idle), ``ui`` (the
                   stored UI state or the theme/lang attribute changed), or ``none`` (nothing
                   observable: some selects are only READ by a later button, which is a different
                   fact from a dead binding and is reported as such).

The sweep refuses a non-loopback ``--url`` and a server that is online (``GET /api/system/network``
must say ``online:false``: boot the app WITHOUT ``OO_NO_SCHEDULER``, which skips the offline engage),
so a run can neither reach the internet nor claim it did not.

It then restores the original value, so the next select starts from the state it found.

Run against a booted app:  .venv/bin/python scripts/csp_sweep.py --url http://127.0.0.1:8011 --out DIR

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = {"1440x900": (1440, 900), "768x1024": (768, 1024), "390x844": (390, 844)}

# Installed into every page before its own scripts run: records CSP violations the browser
# reports (the console line is the second witness), and counts what a pick set in motion.
_INIT = r"""
// sessionStorage outlives a reload of the tab, so a pick that reloads the page (or the recovery
// ``goto`` after a tab error) cannot discard the violations seen before it.
try { window.__csp = JSON.parse(sessionStorage.getItem('__oo_csp') || '[]'); } catch (e) { window.__csp = []; }
document.addEventListener('securitypolicyviolation', e => {
  window.__csp.push({
    directive: e.violatedDirective, blocked: String(e.blockedURI || '').slice(0, 120),
    sample: String(e.sample || '').slice(0, 120), source: String(e.sourceFile || '').slice(-80),
    line: e.lineNumber || 0});
  try { sessionStorage.setItem('__oo_csp', JSON.stringify(window.__csp)); } catch (x) {}
});
window.__net = 0; window.__mut = 0;
(function () {
  const f = window.fetch;
  window.fetch = function () { window.__net++; return f.apply(this, arguments); };
  const o = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function () { window.__net++; return o.apply(this, arguments); };
  new MutationObserver(m => { window.__mut += m.length; }).observe(document, {
    subtree: true, childList: true, attributes: true, characterData: true});
})();
"""


def themes_from_source() -> list[str]:
    """The picker's own catalogue (``THEMES`` in app-shell.js), so the sweep never drifts from it."""
    src = (ROOT / "src" / "static" / "app-shell.js").read_text(encoding="utf-8")
    block = src.split("const THEMES = [", 1)[1].split("];", 1)[0]
    return re.findall(r'\{id:"([a-z0-9-]+)"', block)


_COLLECT = r"""
scope => {
  document.querySelectorAll('[data-sweep-i]').forEach(e => e.removeAttribute('data-sweep-i'));
  // A drop-down inside a collapsed <details> cannot be operated (the browser treats it as not
  // visible), so the foldouts of the view being swept are opened first, as a person would.
  document.querySelectorAll('details:not([open])').forEach(d => {
    if (d.offsetWidth || d.offsetHeight || d.getClientRects().length) d.open = true; });
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                    && getComputedStyle(el).visibility !== 'hidden';
  // A select is named by a PATH that survives a re-render of its panel: its own id, else the nearest
  // ancestor's id plus its index among that ancestor's selects. (A marker attribute was lost whenever the
  // panel redrew, and each lost marker cost a timeout.)
  return [...document.querySelectorAll(scope ? scope + ' select' : 'select')].filter(s => vis(s) && !s.disabled
        && s.options.length > 1 && !s.closest('#oo-tip,[hidden]')).map((s, i) => {
    let host = '', idx = 0;
    if (!s.id) {
      const h = s.parentElement && s.parentElement.closest('[id]');
      if (h) { host = h.id; idx = [...h.querySelectorAll('select')].indexOf(s); }
    }
    return {i, id: s.id || '', name: s.name || '', n: s.options.length, value: s.value, host, idx};
  });
}
"""

# Read a select back by its path: its value and option count, or null when it is not there.
_READ = r"""
([id, host, idx]) => {
  const s = id ? document.getElementById(id)
    : (document.getElementById(host) || document.createElement('i')).querySelectorAll('select')[idx];
  return s ? {value: s.value, n: s.options.length} : null;
}
"""

_SET = r"""
([id, host, idx, v]) => {
  const s = id ? document.getElementById(id)
    : (document.getElementById(host) || document.createElement('i')).querySelectorAll('select')[idx];
  if (!s) return false;
  s.value = v;
  s.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
}
"""

_STATE = r"""
() => ({theme: document.documentElement.getAttribute('data-theme') || '',
        lang: document.documentElement.getAttribute('lang') || '',
        ui: localStorage.getItem('oo.ui') || '', net: window.__net, mut: window.__mut})
"""


def sweep_selects(page, where: str, results: list, log, seen: set, scope: str = "") -> None:
    """Pick another option in every visible select on the current view (inside ``scope``, a CSS selector, when given) and judge it."""
    t_start = time.time()
    try:
        sels = page.evaluate(_COLLECT, scope)
    except Exception as exc:  # noqa: BLE001
        log(f"[sweep] collect failed at {where}: {exc}")
        return
    for s in sels:
        # The same element (top bar, query box) is visible on many subtabs: pick it once per pass.
        key = s["id"] or s["name"]
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        path = [s["id"], s["host"], s["idx"]]
        sel = (page.locator(f'[id="{s["id"]}"]') if s["id"]
               else page.locator(f'[id="{s["host"]}"] select').nth(s["idx"]))
        row = {"where": where, "id": s["id"] or s["name"] or f"{s['host']}[{s['idx']}]", "options": s["n"]}
        try:
            opts = sel.evaluate("e => [...e.options].filter(o => !o.disabled).map(o => o.value)")
            current = s["value"]
            pick = next((v for v in opts if v != current), None)
            if pick is None:
                row.update(status="skipped", why="no other enabled option")
                results.append(row)
                continue
            # What the page does by itself in 400 ms (polls, timers) is measured first, so a pick is
            # credited only with what exceeds it.
            s0 = page.evaluate(_STATE)
            page.wait_for_timeout(400)
            before = page.evaluate(_STATE)
            sel.select_option(value=pick, timeout=3000)
            page.wait_for_timeout(400)
            after = page.evaluate(_STATE)
            # Read the pick back from wherever the select is NOW (a pick may redraw its panel).
            back = page.evaluate(_READ, path)
            if back is None:
                held = None
            elif back["value"] == pick:
                held = True
            elif back["n"] == s["n"]:
                held = False
            else:
                held = None  # the panel was rebuilt with other options: nothing to compare
            idle = {"net": before["net"] - s0["net"], "mut": before["mut"] - s0["mut"]}
            effect = ("ui" if (before["theme"], before["lang"], before["ui"]) != (after["theme"], after["lang"], after["ui"])
                      else "net" if after["net"] - before["net"] > idle["net"]
                      else "dom" if after["mut"] - before["mut"] > idle["mut"] else "none")
            status = "unread" if held is None else "REVERTED" if held is False else "ok"
            row.update(status=status, picked=pick, held=held, effect=effect, idle_net=idle["net"], idle_mut=idle["mut"])
            if held is None:
                row["why"] = "the select was gone or rebuilt after the pick: its value could not be read back"
            try:  # restore, so the next select starts from the state it found
                if not page.evaluate(_SET, path + [current]):
                    row["restored"] = False
                page.wait_for_timeout(150)
            except Exception:  # noqa: BLE001
                pass
            page.keyboard.press("Escape")  # a consent popup or dialog a pick may have opened
        except Exception as exc:  # noqa: BLE001
            row.update(status="ERROR", why=f"{type(exc).__name__}: {str(exc)[:400]}")
        results.append(row)
    print(f"    {where}: {len(sels)} selects, {time.time() - t_start:.1f}s", file=sys.stderr, flush=True)


def require_loopback_offline(url: str, request) -> None:
    """Refuse a non-loopback ``url`` and an app that is ONLINE; ``request`` is a Playwright APIRequestContext.

    ``OO_NO_SCHEDULER=1`` skips the boot's kill-switch engage, so an app booted with it answers
    ``online:true`` and the record cannot say "airplane mode" about it. A sweep that picks every
    drop-down is only allowed to run where nothing it does can reach the internet.
    """
    host = urlparse(url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(f"refusing --url {url}: the sweep only runs against a loopback app")
    mode = request.get(url.rstrip("/") + "/api/system/network").json()
    if mode.get("online") is not False:
        raise SystemExit(
            f"refusing to sweep: GET /api/system/network says {mode!r}, not online:false "
            "(boot the app without OO_NO_SCHEDULER, which skips the offline engage)")


def run_width(browser, url: str, wname: str, themes: list[str], out: Path, only_tabs: list[str] | None) -> dict:
    w, h = WIDTHS[wname]
    ctx = browser.new_context(viewport={"width": w, "height": h})
    ctx.add_init_script(_INIT)
    if os.environ.get("OO_SWEEP_SKIP_GUIDE") == "1":
        # An EMPTY install opens the first-run guide over the page (it only ever opens on an empty corpus);
        # marking it done is what a person does by closing it, and lets the sweep reach what is under it.
        ctx.add_init_script("try { localStorage.setItem('oo_guide_v1', JSON.stringify({done: true})); } catch (e) {}")
    require_loopback_offline(url, ctx.request)
    page = ctx.new_page()
    # A select the page re-rendered away between the collect and the pick would otherwise cost
    # Playwright's 30 s default per ERROR row (50 of them in Settings measured 25 minutes a run).
    page.set_default_timeout(4000)
    console: list[str] = []
    page.on("console", lambda m: console.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: console.append(f"[pageerror] {e}"))
    page.on("dialog", lambda d: d.dismiss())
    page.on("response", lambda r: console.append(f"[http {r.status}] {r.request.method} {r.url[len(url):][:120]}")
            if r.status >= 400 else None)
    summary = {"width": wname, "themes": {}}
    page.goto(url, wait_until="load")
    page.wait_for_timeout(1500)
    # Every sidebar tab, plus every ``#tab-*`` page the app has (Settings is not in the nav list;
    # search/analyze are the two parts of Explore and would only repeat it).
    names = page.evaluate(
        "() => [...new Set([...document.querySelectorAll('#navGroups [data-tab]')].map(b => b.dataset.tab)"
        ".concat([...document.querySelectorAll('[id^=\"tab-\"]')].map(e => e.id.slice(4))))]"
        ".filter(n => n !== 'search' && n !== 'analyze')")
    if only_tabs:
        names = [n for n in names if n in only_tabs]
    for theme in themes:
        t0 = time.time()
        console.clear()
        page.evaluate("t => setTheme(t)", theme)
        page.wait_for_timeout(200)
        results: list = []
        seen: set = set()
        log = lambda s: console.append(s)  # noqa: E731
        for name in names:
            try:
                page.evaluate("n => showTab(n)", name)
                page.wait_for_timeout(500)
                sweep_selects(page, f"{name}", results, log, seen)
                # A page's subtabs are RELOCATED into the top strip (``.subtab-strip``) when it opens.
                subs = page.evaluate(
                    "n => { document.querySelectorAll('[data-sweep-sub]').forEach(e => e.removeAttribute('data-sweep-sub'));"
                    " const root = document.getElementById('tab-' + n);"
                    " const q = '.subtab-strip .tabs [data-tab], .subtab-strip [data-tab]'"
                    "   + (root ? ', #tab-' + n + ' .tabs [data-tab]' : '');"
                    " return [...new Set(document.querySelectorAll(q))]"
                    ".filter(b => b.offsetWidth || b.offsetHeight).map((b, i) => { b.setAttribute('data-sweep-sub', String(i));"
                    " return {i, t: b.dataset.tab}; }); }", name)
                for sub in subs:
                    try:
                        page.locator(f'[data-sweep-sub="{sub["i"]}"]').first.click(timeout=2000)
                        page.wait_for_timeout(350)
                        sweep_selects(page, f"{name} > {sub['t']}", results, log, seen)
                    except Exception as exc:  # noqa: BLE001
                        results.append({"where": f"{name} > {sub['t']}", "status": "ERROR", "why": f"subtab: {str(exc)[:120]}"})
            except Exception as exc:  # noqa: BLE001
                results.append({"where": name, "status": "ERROR", "why": f"tab: {str(exc)[:120]}"})
                try:
                    page.goto(url, wait_until="load")
                    page.wait_for_timeout(1000)
                    page.evaluate("t => setTheme(t)", theme)
                except Exception:  # noqa: BLE001
                    pass
        try:
            csp = page.evaluate("() => window.__csp")
        except Exception:  # noqa: BLE001
            csp = []
        csp_console = [c for c in console if re.search(r"content security policy|refused to (execute|load|apply)", c, re.I)]
        stat = {k: sum(1 for r in results if r["status"] == k) for k in ("ok", "REVERTED", "unread", "ERROR", "skipped")}
        stat.update(
            effect_none=sum(1 for r in results if r.get("effect") == "none"),
            csp_events=len(csp), csp_console=len(csp_console), console_lines=len(console),
            seconds=round(time.time() - t0, 1),
        )
        summary["themes"][theme] = stat
        (out / f"console-{wname}-{theme}.txt").write_text(
            f"# console (error + warning) and pageerror text, width {wname}, theme {theme}\n"
            f"# CSP violation events (securitypolicyviolation): {json.dumps(csp)}\n"
            + ("\n".join(console) if console else "(no console errors or warnings)") + "\n",
            encoding="utf-8")
        (out / f"selects-{wname}-{theme}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"{wname} {theme}: {stat}", flush=True)
    ctx.close()
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", choices=sorted(WIDTHS), action="append")
    ap.add_argument("--theme", action="append", help="default: every theme in the picker")
    ap.add_argument("--tab", action="append", help="default: every sidebar tab")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    themes = a.theme or themes_from_source()
    summaries = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for wname in a.width or list(WIDTHS):
            summaries.append(run_width(browser, a.url, wname, themes, out, a.tab))
        browser.close()
    (out / f"summary-{'-'.join(a.width or WIDTHS)}.json").write_text(
        json.dumps({"at": datetime.now(UTC).isoformat(), "themes": themes, "runs": summaries}, indent=1), encoding="utf-8")
    # A walk fails on a revert, a CSP event, an ERROR, an UNREAD pick, and on a walk that picked nothing:
    # a judge that cannot fail for whole classes of outcome (every pick timing out exits 0) is a rubber stamp.
    stats = [t for s in summaries for t in s["themes"].values()]
    bad = sum(t["REVERTED"] + t["ERROR"] + t["unread"] + t["csp_events"] + t["csp_console"] for t in stats)
    empty = sum(1 for t in stats if t["ok"] == 0)
    return 1 if bad or empty else 0


if __name__ == "__main__":
    sys.exit(main())
