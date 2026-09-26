import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import EXE, TOAST_INIT, Rec, close_guide, dismiss_coach, save
BASE = "http://127.0.0.1:8839"
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-background-networking", "--disable-component-update"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec = Rec("dbg"); rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(3500); close_guide(pg); dismiss_coach(pg)
    pg.click(".omni"); pg.wait_for_selector("#pal-input", state="visible")
    pg.type("#pal-input", "Coastal Infrastructure Act", delay=40)
    for i in range(8):
        pg.wait_for_timeout(1500)
        print(i, pg.evaluate("() => [...document.querySelectorAll('#pal-list > *')].map(e => e.className + '|' + e.innerText.replace(/\\s+/g,' ').slice(0,90))")[:14])
    print(rec.dump())
    print(pg.evaluate("() => fetch('/api/search/omni?q=' + encodeURIComponent('Coastal Infrastructure Act')).then(r => r.status + ' ' + r.url)"))
    pg.screenshot(path="/tmp/claude-0/walk/P/dbg-pal.png")
    br.close()
