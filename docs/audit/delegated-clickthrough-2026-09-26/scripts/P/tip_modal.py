import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import EXE, Rec, close_guide, dismiss_coach, save, shot
BASE = "http://127.0.0.1:8839"
R = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-background-networking", "--disable-component-update"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec = Rec("tipmodal"); rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(3500); close_guide(pg); dismiss_coach(pg)
    pg.click("#net-toggle")
    pg.wait_for_function("() => document.getElementById('net-consent').open")
    pg.wait_for_function("() => !/^…$/.test(document.getElementById('net-consent-lanes').innerText)")
    pg.wait_for_timeout(800)
    wl = pg.locator("#net-consent-lanes span[title]", has_text="Wikipedia / Wikimedia").first
    b = wl.bounding_box(); pg.mouse.move(b["x"] + 10, b["y"] + 5); pg.wait_for_timeout(700)
    R["consent"] = pg.evaluate("""() => { const t = document.getElementById('oo-tip'); const r = t.getBoundingClientRect(); const cs = getComputedStyle(t);
       const d = document.getElementById('net-consent').getBoundingClientRect();
       return {show: t.classList.contains('show'), opacity: cs.opacity, text: t.textContent.slice(0, 80), tip: [r.left, r.top, r.right, r.bottom], dialog: [d.left, d.top, d.right, d.bottom],
               tip_parent: t.parentElement.tagName, in_top_layer: !!t.closest('dialog')}; }""")
    pg.screenshot(path="/tmp/claude-0/walk/P/P-P3-consent-hover-hidden-en.png")
    pg.click("#net-consent-cancel"); pg.wait_for_timeout(500)
    R["errors"] = rec.dump()
    save("tip_modal.json", R)
    br.close()
