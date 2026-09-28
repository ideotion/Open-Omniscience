import sys; sys.path.insert(0, "/tmp/claude-0/walk/S-recheck")
import recheck as W
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=W.CHROME, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 375, "height": 800}); ctx.add_init_script(W.INIT)
    pg = ctx.new_page(); W.attach(pg)
    W.unlock(pg); pg.wait_for_timeout(2500)
    c = pg.locator("#net-coach-dismiss")
    if c.count() and c.is_visible(): c.click(); pg.wait_for_timeout(500)
    print("overflow", pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"))
    pg.evaluate("() => window.scrollTo(0,0)")
    pg.locator(".home-glance").first.screenshot(path=str(W.SHOTS / "S-F7-home-glance-375-en.png"))
    b.close()
print(W.R["page_errors"], W.R["http_errors"])
