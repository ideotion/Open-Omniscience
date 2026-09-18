# -*- coding: utf-8 -*-
"""S04-14 targeted click-through: the surfaces this slice changed, in four locales.

Drives the REAL top-bar language switcher rather than calling OOI18N.setLang -- a
scripted state change is not the control, and a harness that sets the language
itself cannot see invariant #15's switcher fail.
"""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

PORT = int(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
BASE = f"http://127.0.0.1:{PORT}"
LOCALES = ["en", "fr", "ar", "zh", "hi"]

# (label, how to reach it, selector whose rendered text is the evidence)
SURFACES = [
    # SELECTORS FIXED after a dry run that reported four surfaces as evidence when they
    # were not. `#tab-law p.hint` matched the FIRST hint in the tab, which is the World
    # Bank statistics panel, so the law text was never read and the walk would have
    # reported a translated string belonging to a different surface. The CSV block had
    # the same shape. Anchor each one to the panel that owns it, never to the tab.
    ("collection-hint",  ("adv", "collect"),       "#set-advanced details[data-adv='collect'] p.hint"),
    ("speed-value",      ("adv", "collect"),       "#sch-speed-val"),
    ("csv-columns",      ("adv", "sources"),       "#src-csv-hint"),
    ("patterns-gate",    ("adv", "diagnostics"),   "#patterns-gate"),
    ("bulletin-hint",    ("adv", "bulletin"),      "#bulletin-panel p.hint"),
    ("stoplist-summary", ("adv", "keywords"),      "#kf-builtin-view > summary"),
    ("law-hint",         ("gov", "law"),           "#gov-law p.hint"),
    ("help-hint",        ("tab", "help"),          "#tab-help p.muted"),
]


def run():
    errors, report = [], {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                               args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = br.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.on("console", lambda m: errors.append(f"console.error: {m.text[:160]}")
              if m.type == "error" else None)
        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(1500)

        for loc in LOCALES:
            # THE REAL CONTROL (invariant #15): open the top-bar switcher and click
            # the row, so a broken switcher fails the walk instead of being bypassed.
            pg.click("#lang-switch", timeout=15000)
            pg.wait_for_timeout(250)
            pg.click(f"#lang-menu [data-lang='{loc}']", timeout=15000)
            pg.wait_for_timeout(1200)
            got = pg.evaluate("() => (window.OOI18N && OOI18N.current && OOI18N.current()) || '?'")
            direction = pg.evaluate("() => document.documentElement.dir || getComputedStyle(document.body).direction")
            report[loc] = {"selected": got, "dir": direction, "surfaces": {}}

            for name, (how, key), sel in SURFACES:
                try:
                    if how == "tab":
                        pg.evaluate(f"() => showTab('{key}')")
                    elif how == "gov":
                        # The law panel is a SUB-VIEW of the Governments tab (whose tab id
                        # is "law", not "gov") and it ships display:none, so reaching it
                        # needs the tab AND the subtab -- otherwise the walk reads a hidden
                        # element and reports the surface as empty. Driven by CLICKING the
                        # real ooSubtabs button rather than calling showGovView, for the
                        # same reason the language switcher is clicked: a scripted state
                        # change cannot see the control itself fail.
                        pg.evaluate("() => showTab('law')")
                        pg.wait_for_timeout(400)
                        pg.click(f"#gov-subtabs [data-tab='{key}']", timeout=15000)
                    elif how == "set":
                        pg.evaluate("() => showTab('settings')")
                        pg.wait_for_timeout(200)
                        pg.evaluate(f"() => {{ if (window.showSetCat) showSetCat('{key}'); }}")
                    else:
                        pg.evaluate("() => showTab('settings')")
                        pg.wait_for_timeout(200)
                        pg.evaluate("() => (window._openAdvanced ? 1 : 0)")
                        pg.evaluate(f"""() => {{
                            const s = document.querySelector('#set-settings, #setnav [data-tab="advanced"]');
                            if (window.showSetCat) showSetCat('advanced');
                            const d = document.querySelector('#set-advanced details.adv-sec[data-adv="{key}"]');
                            if (d && !d.open) {{ d.open = true; d.dispatchEvent(new Event('toggle')); }}
                        }}""")
                    pg.wait_for_timeout(700)
                    # textContent, NOT innerText: innerText is EMPTY for a hidden element,
                    # so the dry run reported three surfaces as empty when they were merely
                    # inside a collapsed <details>. An empty string and a hidden element are
                    # different facts and only one of them is a finding, so the visibility is
                    # measured and reported beside the text instead of being conflated with it.
                    txt = pg.eval_on_selector(sel, """e => {
                        const vis = !!(e.offsetParent || e.getClientRects().length);
                        const t = (e.textContent || '').replace(/\\s+/g, ' ').trim();
                        return (vis ? '' : '[hidden] ') + t.slice(0, 400);
                    }""")
                except Exception as exc:
                    txt = f"<<unreachable: {type(exc).__name__}>>"
                report[loc]["surfaces"][name] = txt
            pg.screenshot(path=str(OUT / f"{loc}.png"), full_page=False)
        br.close()
    report["_page_errors"] = errors
    (OUT / "walk.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: {"selected": v["selected"], "dir": v["dir"]} for k, v in report.items()
                      if k != "_page_errors"}, ensure_ascii=False, indent=1))
    print(f"\npage errors: {len(errors)}")
    for e in errors[:6]: print("   ", e[:170])

run()
