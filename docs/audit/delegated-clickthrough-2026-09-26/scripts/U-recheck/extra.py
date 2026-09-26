import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/U-recheck")
from common import *
BASE = "http://127.0.0.1:8852"; rec = Rec("extra")
def dismiss(pg):
    try:
        if pg.is_visible("#net-coach-dismiss"): pg.click("#net-coach-dismiss", timeout=2000)
    except Exception: pass
def wk(pg): return pg.evaluate("() => { const g = document.querySelector('#agenda-month .ag-grid, .ag-grid'); return g ? g.innerText.split('\\n').slice(0,7) : null; }")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1440, "height": 950}); rec.attach(pg)
    unlock(pg, BASE); close_unrelated(pg); dismiss(pg)
    pg.wait_for_function("() => !/Loading/.test(document.getElementById('home-stats').textContent)", timeout=30000)
    switch_lang(pg, "ar"); pg.wait_for_timeout(1500)
    rec.note("strip.ar_after_switch", {"stats": pg.inner_text("#home-stats")[:200], "status": pg.inner_text("#home-status"), "dir": pg.evaluate("() => document.documentElement.dir")})
    shot(pg, "U-D4-strip-ar-after-switch")
    switch_lang(pg, "en"); dismiss(pg)
    pg.click("#navGroups .nav-item[data-tab='agenda']"); pg.wait_for_timeout(1200)
    pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(1500)
    rec.note("agenda.en_weekdays", wk(pg))
    switch_lang(pg, "fr"); pg.wait_for_timeout(1000)
    rec.note("agenda.fr_after_switch_weekdays", wk(pg))
    pg.click("#navGroups .nav-item[data-tab='home']"); pg.wait_for_timeout(600)
    pg.click("#navGroups .nav-item[data-tab='agenda']"); pg.wait_for_timeout(1200)
    pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(1500)
    rec.note("agenda.fr_after_renav_weekdays", wk(pg))
    switch_lang(pg, "en")
    rec.note("net_online_end", pg.evaluate("async () => (await (await fetch('/api/system/network')).json()).online"))
    rec.save(); br.close()
