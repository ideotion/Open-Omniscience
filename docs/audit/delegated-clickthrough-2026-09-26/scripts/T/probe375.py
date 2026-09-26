"""Probe: what makes the page wider than a 375 px viewport (home and /tasks)?"""
import json
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8846"; OUT = "/tmp/claude-0/walk/T"
FIND = """() => { const cw = document.documentElement.clientWidth; const out = [];
  for (const e of document.querySelectorAll('body *')) { const r = e.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
    const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (r.right > cw + 1) out.push({el: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).slice(0,2).join('.') : ''), right: Math.round(r.right), w: Math.round(r.width), pos: cs.position, text: (e.innerText || '').trim().slice(0, 40)}); }
  return {sw: document.documentElement.scrollWidth, cw, body_sw: document.body.scrollWidth, n: out.length, first: out.slice(0, 25)}; }"""
res = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    for theme in ["light", "dark"]:
        ctx = br.new_context(viewport={"width": 375, "height": 812}, color_scheme=theme); pg = ctx.new_page()
        pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(7000)
        res[f"home_{theme}"] = pg.evaluate(FIND)
        # with the coach dismissed, is the overflow still there?
        pg.evaluate("() => { const c = document.getElementById('net-coach'); if (c) c.classList.remove('show'); }")
        pg.wait_for_timeout(300)
        res[f"home_{theme}_nocoach"] = {"overflow": pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")}
        pg.goto(BASE + "/tasks", wait_until="domcontentloaded"); pg.wait_for_timeout(4000)
        res[f"tasks_{theme}"] = pg.evaluate(FIND)
        ctx.close()
    br.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
