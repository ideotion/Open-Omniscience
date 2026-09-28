"""Recheck part 3: in RTL, once the coach IS anchored to the plane (after a resize, or when first
shown in RTL), which top-bar controls does it cover? elementFromPoint at each control's centre."""
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8848"; OUT = "/tmp/claude-0/walk/T-recheck"
res = {}
PROBE = """() => { const c=document.getElementById('net-coach'); const cr=c.getBoundingClientRect();
  const out = {shown: c.classList.contains('show'), coach: [Math.round(cr.left), Math.round(cr.top), Math.round(cr.right), Math.round(cr.bottom)], covered: []};
  for (const e of document.querySelectorAll('.topbar button, .topbar a, .topbar [id]')) { const q=e.getBoundingClientRect(); if (!q.width || !q.height) continue;
    const x=q.left+q.width/2, y=q.top+q.height/2; const hit=document.elementFromPoint(x,y);
    if (hit && c.contains(hit)) out.covered.push((e.id||e.tagName.toLowerCase()) + ' @' + Math.round(x) + ',' + Math.round(y) + ' title=' + (e.getAttribute('title')||'').slice(0,40)); }
  return out; }"""
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_function("() => location.hash === '#home'", timeout=30000)
    pg.wait_for_timeout(6000)
    pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    res["en"] = pg.evaluate(PROBE)
    pg.mouse.move(700, 900); pg.click("#lang-switch"); pg.wait_for_timeout(300)
    pg.click("#lang-menu [data-lang='ar']"); pg.wait_for_function("() => document.documentElement.lang === 'ar'"); pg.wait_for_timeout(1500)
    res["ar_live_no_reanchor"] = pg.evaluate(PROBE)
    pg.set_viewport_size({"width": 1439, "height": 950}); pg.wait_for_timeout(600)
    res["ar_reanchored_by_resize"] = pg.evaluate(PROBE)
    pg.screenshot(path=f"{OUT}/T-recheck-coach-ar-reanchored-covers-topbar.png", clip={"x": 0, "y": 0, "width": 720, "height": 200})
    br.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
open(f"{OUT}/recheck3.json", "w").write(json.dumps(res, ensure_ascii=False, indent=1))
