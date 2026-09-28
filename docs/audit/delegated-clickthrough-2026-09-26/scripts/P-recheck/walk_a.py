"""Row P recheck, folder A (fresh, encrypted via first-launch) on port 8841: D4 + D10."""
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/P-recheck")
from common import ARGS, EXE, PASS, Rec, close_guide, save  # noqa: E402

BASE = "http://127.0.0.1:8841"
R = {}
rec = Rec("A")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=ARGS)
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page()
    rec.attach(pg)
    dl = []
    pg.on("response", lambda r: dl.append({"url": r.url, "status": r.status}) if "data-location" in r.url else None)
    try:
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        R["url_after_goto"] = pg.url
        pg.wait_for_selector("#view-language:not(.hidden) .lang-btn", timeout=20000)
        pg.click("#lang-list .lang-btn[lang='en']")
        pg.wait_for_selector("#view-legal:not(.hidden)", timeout=20000)
        pg.wait_for_timeout(1200)
        pg.check("#lg-check")
        pg.click("#lg-accept")
        pg.wait_for_timeout(2500)
        R["datadir_view_visible"] = pg.is_visible("#view-datadir")
        R["create_view_visible"] = pg.is_visible("#view-create")
        R["data_location_responses"] = list(dl)
        R["data_location_body_now"] = pg.evaluate("() => fetch('/api/system/data-location').then(async r => ({status: r.status, body: await r.json()}))")
        R["lock_state_now"] = pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json()).then(j => j.state)")
        pg.screenshot(path="/tmp/claude-0/walk/P-recheck/P-D4-after-legal-en.png")
        pg.fill("#pw1", PASS)
        pg.fill("#pw2", PASS)
        pg.click("#btn-create")
        pg.wait_for_url("**/?wikiwizard=1*", timeout=120000)
        pg.wait_for_timeout(3500)
        R["data_location_after_create"] = pg.evaluate("() => fetch('/api/system/data-location').then(async r => ({status: r.status, body: await r.json()}))")
        R["lock_state_after_create"] = pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json()).then(j => j.state)")
        close_guide(pg)
        for sel in ("#wiki-wizard-cancel",):
            try:
                if pg.is_visible(sel):
                    pg.click(sel)
                    pg.wait_for_timeout(500)
            except Exception:
                pass
        close_guide(pg)
        try:
            pg.wait_for_selector("#net-coach-dismiss", state="visible", timeout=6000)
            pg.click("#net-coach-dismiss")
        except Exception:
            pass
        pg.click("button[onclick=\"showTab('settings')\"]")
        pg.wait_for_timeout(600)
        pg.click("#set-subtabs button[data-tab='wikipedia']")
        pg.wait_for_timeout(1500)
        R["D10_ores_checked_fresh"] = pg.evaluate("() => document.getElementById('wiki-ores').checked")
        lbl = pg.locator("label", has=pg.locator("#wiki-ores")).first
        lbl.scroll_into_view_if_needed()
        R["D10_label_text"] = lbl.inner_text()
        pg.screenshot(path="/tmp/claude-0/walk/P-recheck/P-D10-ores-fresh-en.png")
    except Exception:
        R["harness_exception"] = traceback.format_exc()
        pg.screenshot(path="/tmp/claude-0/walk/P-recheck/P-A-harness-exception.png")
    R["errors"] = rec.dump()
    save("a.json", R)
    br.close()
