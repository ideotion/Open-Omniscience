import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import EXE, Rec, close_guide, dismiss_coach, save, shot
BASE = "http://127.0.0.1:8839"
R = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-background-networking", "--disable-component-update"])
    ctx = br.new_context(viewport={"width": 375, "height": 800})
    pg = ctx.new_page(); rec = Rec("n375"); rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(3500); close_guide(pg)
    try:
        pg.wait_for_selector("#net-coach-dismiss", state="visible", timeout=8000); pg.click("#net-coach-dismiss"); pg.wait_for_timeout(400)
    except Exception: pass
    for sub in ["graphics", "wikipedia", "data"]:
        pg.evaluate("() => showTab('settings')"); pg.wait_for_timeout(500)
        pg.click(f"#set-subtabs button[data-tab='{sub}']"); pg.wait_for_timeout(1200)
        R[sub] = {"scroll_x": pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"),
                  "offenders": pg.evaluate("""() => { const W = document.documentElement.clientWidth; const out = [];
                     document.querySelectorAll('body *').forEach(e => { const r = e.getBoundingClientRect(); if (r.width && r.right > W + 0.5 && getComputedStyle(e).position !== 'fixed') {
                        let p = e.parentElement, clipped = false; while (p && p !== document.body) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') { if (p.getBoundingClientRect().right <= W + 0.5) { clipped = true; break; } } p = p.parentElement; }
                        if (!clipped) out.push(e.tagName + '#' + e.id + '.' + String(e.className).slice(0,40) + ' right=' + Math.round(r.right) + ' w=' + Math.round(r.width) + ' txt=' + (e.innerText||'').slice(0,40).replace(/\\n/g,' ')); } });
                     return out.slice(0, 15); }""")}
        if sub == "wikipedia":
            shot(pg, "N375-settings-wikipedia-en", full=True)
    R["errors"] = rec.dump()
    save("narrow_dbg.json", R)
    br.close()
