from playwright.sync_api import sync_playwright
from common import *
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1440, "height": 950})
    pg.goto("http://127.0.0.1:8850/", wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
    print(pg.evaluate("() => { const c = document.getElementById('nl-attach-caveat'); return {cls: c.className, title: c.getAttribute('title'), undoCls: document.getElementById('nl-attach-undo').className}; }"))
    br.close()
