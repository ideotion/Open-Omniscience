import json, sys
sys.path.insert(0, "/tmp/claude-0/walk/S")
import walk_a as W
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=W.CHROME, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 375, "height": 800})
    pg = ctx.new_page()
    W.unlock_if_needed(pg); W.settle_chrome(pg); pg.wait_for_timeout(2500)
    if pg.locator("#net-coach-dismiss").is_visible():
        pg.click("#net-coach-dismiss"); pg.wait_for_timeout(600)
    pg.wait_for_timeout(1500)
    over = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    wide = pg.evaluate("""() => { const out=[]; document.querySelectorAll('body *').forEach(e => { if (!e.offsetParent && getComputedStyle(e).position!=='fixed') return; const r=e.getBoundingClientRect(); if (r.width>0 && r.right > window.innerWidth+1) out.push({tag:e.tagName,id:e.id,cls:String(e.className).slice(0,40),left:Math.round(r.left),right:Math.round(r.right),w:Math.round(r.width),text:(e.innerText||'').slice(0,40)}); }); return out.slice(0,25); }""")
    strip = pg.evaluate("() => Array.from(document.querySelectorAll('#home-stats .s')).map(e => { const r=e.getBoundingClientRect(); const lab=e.querySelector('span'); return {text:e.innerText.replace(/\\s+/g,' '), left:Math.round(r.left), right:Math.round(r.right), labClipped: lab ? lab.scrollWidth>lab.clientWidth+1 : null}; })")
    pg.locator("#home-stats").screenshot(path=str(W.SHOTS / "S-375-home-strip-en.png"))
    print(json.dumps({"overflow": over, "wide": wide, "strip": strip}, indent=1, ensure_ascii=False))
    b.close()
