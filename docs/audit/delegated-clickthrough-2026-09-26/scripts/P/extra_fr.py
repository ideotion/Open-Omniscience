import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import EXE, Rec, close_guide, save, shot, switch_lang, text, tip
BASE = "http://127.0.0.1:8839"
R = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-background-networking", "--disable-component-update"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec = Rec("extra-fr"); rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(3500); close_guide(pg)
    try:
        pg.wait_for_selector("#net-coach-dismiss", state="visible", timeout=8000); pg.click("#net-coach-dismiss"); pg.wait_for_timeout(400)
    except Exception: pass
    switch_lang(pg, "fr", rec)
    pg.click("button[onclick=\"showTab('settings')\"]"); pg.wait_for_timeout(500)
    pg.click("#set-subtabs button[data-tab='data']"); pg.wait_for_timeout(1500)
    R["storage_rows"] = pg.evaluate("() => [...document.querySelectorAll('#storage-lanes tr')].map(tr => tr.innerText.replace(/\\s+/g,' ').trim())")
    pg.click("button[onclick='openUnifiedExport()']")
    pg.wait_for_function("() => !/…/.test(document.getElementById('ux-inv-status').innerText)", timeout=30000); pg.wait_for_timeout(600)
    R["status"] = text(pg, "#ux-inv-status")
    R["rows"] = pg.evaluate("() => [...document.querySelectorAll('#ux-checklist label')].map(l => ({t: l.innerText.replace(/\\s+/g,' ').trim(), title: l.getAttribute('title')}))")
    shot(pg, "P10-export-fr", clip_sel="#ux-export")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    pg.click(".nav-item[data-tab='timemap']"); pg.wait_for_selector("[data-oomap-wiki]", timeout=30000); pg.wait_for_timeout(2000)
    R["map_btn"] = pg.evaluate("() => { const b = document.querySelector('[data-oomap-wiki]'); return {t: b.innerText, title: b.getAttribute('title')}; }")
    pg.click("[data-oomap-wiki]"); pg.wait_for_timeout(2500)
    R["map_legend"] = pg.evaluate("() => [...document.querySelectorAll('#tab-timemap .muted')].map(e => e.innerText).filter(t => /Wikip/.test(t))")
    pg.click("[data-oomap-wiki]"); pg.wait_for_timeout(1500)
    R["errors"] = rec.dump()
    save("extra_fr.json", R)
    br.close()
