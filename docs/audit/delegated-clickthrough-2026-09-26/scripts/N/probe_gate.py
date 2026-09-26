import sys, json
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = launch(p); ctx = b.new_context(viewport={"width": 1440, "height": 950}); page = ctx.new_page()
    page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(3000); close_dialogs(page); dismiss_coach(page)
    page.click("button[onclick=\"showTab('settings')\"]"); page.click("#set-subtabs button[data-tab=advanced]"); page.wait_for_timeout(800)
    page.click("details[data-adv=uninstall] > summary"); page.wait_for_timeout(400)
    page.click("details[data-adv=bulletin] > summary")
    for t in (1, 4, 8):
        page.wait_for_timeout(t * 1000)
        print(t, {"gate_visible": page.is_visible("#bulletin-gate"), "gate_text": text(page, "#bulletin-gate"), "controls": page.is_visible("#bulletin-controls")})
    page.locator("#bulletin-panel").scroll_into_view_if_needed()
    page.screenshot(path="/tmp/claude-0/walk/N/shots/N-N10-bulletin-panel-en.png")
    b.close()
