"""Chromium walk for the bulletin carrier (row K, PR #1245). Loopback only.

Walks the two Settings screens whose wording or controls this change touches, opens every
drop-down on them, picks an option and reads the choice back:

  * Settings -> OpenStreetMap: the hint that used to say OSM data is kept out of bulletins;
    the "Add a country" drop-down;
  * Settings -> Advanced -> bulletin: the Period drop-down (every option picked in turn);

and renders an edition carrying the lane card as HTML, read in the same browser, to confirm the
credit and the ODbL line are on the page. Stamped "Chromium-verified (remote sandbox) · awaiting
human UX pass".
"""
import json
import os

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8765")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/s5/out2")
HTML = os.environ.get("OO_WALK_HTML", "/tmp/claude-0/s5/lane_bulletin.html")
os.makedirs(OUT, exist_ok=True)
report = {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    ctx = b.new_context(viewport={"width": 1366, "height": 900})
    blocked = []
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith((BASE, "data:", "blob:", "about:")) else (blocked.append(r.request.url), r.abort()))
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text[:200]) if m.type == "error" else None)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.evaluate("() => showTab('settings')")
    pg.wait_for_timeout(300)

    # OpenStreetMap subtab: the hint, and the country drop-down
    pg.locator('#set-subtabs button[data-tab="offlinemap"]').first.click()
    pg.wait_for_selector("#osm-lane-picker", state="visible", timeout=5000)
    hint = pg.locator("#osm-lane-picker .hint", has_text="OpenStreetMap data stays on this machine").first.inner_text()
    report["osm_hint"] = hint
    assert "kept out of exports" not in hint and "ODbL 1.0" in hint
    sel = pg.locator("#osm-pick-add")
    opts = sel.evaluate("(s) => [...s.options].map(o => [o.value, o.text])")
    report["osm_pick_options"] = len(opts)
    if len(opts) > 1:
        sel.select_option(index=1)
        report["osm_pick_after"] = sel.evaluate("(s) => [s.value, s.options[s.selectedIndex].text]")
        assert report["osm_pick_after"][0] == opts[1][0]
    pg.screenshot(path=f"{OUT}/1-osm-hint.png")

    # Advanced -> bulletin: the Period drop-down, each option picked and read back
    pg.locator('#set-subtabs button[data-tab="advanced"]').first.click()
    pg.evaluate("() => { const d = document.querySelector('details.adv-sec[data-adv=\"bulletin\"]'); if (d) d.open = true; const c = document.getElementById('bulletin-controls'); if (c) c.hidden = false; }")
    pg.wait_for_selector("#bul-cadence", state="visible", timeout=5000)
    picked = []
    for v in pg.locator("#bul-cadence").evaluate("(s) => [...s.options].map(o => o.value)"):
        pg.locator("#bul-cadence").select_option(v)
        picked.append([v, pg.locator("#bul-cadence").input_value()])
    assert all(a == b_ for a, b_ in picked), picked
    report["period_dropdown_picks"] = picked
    pg.screenshot(path=f"{OUT}/2-bulletin-period.png")

    # the HTML edition with the lane card, read in this browser
    pg2 = ctx.new_page()
    pg2.set_content(open(HTML, encoding="utf-8").read())
    body = pg2.inner_text("body")
    report["html_has_credit"] = "© OpenStreetMap contributors" in body and "ODbL" in body
    assert report["html_has_credit"], body
    pg2.screenshot(path=f"{OUT}/3-bulletin-html-credit.png", full_page=True)

    report["errors"] = errs
    report["blocked_non_loopback"] = blocked
    b.close()
json.dump(report, open(f"{OUT}/report.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(report, indent=1, ensure_ascii=False))
