"""Recheck part 5: a COLD RTL load (language picked through the real switcher, then reload) --
where does the coach land, and which top-bar controls does it cover?"""
import json
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8848"; OUT = "/tmp/claude-0/walk/T-recheck"
PROBE = open(OUT + "/recheck3.py").read().split('PROBE = """')[1].split('"""')[0]
res = {"timeline": []}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_function("() => location.hash === '#home'", timeout=30000)
    pg.wait_for_timeout(4000)
    res["first_load_wizard_open"] = pg.evaluate("() => { const d=document.getElementById('guide-wizard'); return !!(d && d.open); }")
    pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.mouse.move(700, 900); pg.click("#lang-switch"); pg.wait_for_timeout(300)
    pg.click("#lang-menu [data-lang='ar']"); pg.wait_for_function("() => document.documentElement.lang === 'ar'"); pg.wait_for_timeout(800)
    pg.reload(wait_until="domcontentloaded")
    for i in range(16):
        pg.wait_for_timeout(500)
        res["timeline"].append(pg.evaluate("() => ({wiz: !!(document.getElementById('guide-wizard')||{}).open, coach: document.getElementById('net-coach').classList.contains('show'), lang: document.documentElement.lang, hash: location.hash})"))
    res["cold_ar"] = pg.evaluate(PROBE)
    res["coach_state_ls"] = pg.evaluate("() => localStorage.getItem('oo_net_coach_v1')")
    pg.screenshot(path=f"{OUT}/T-recheck-coach-ar-cold.png", clip={"x": 0, "y": 0, "width": 720, "height": 200})
    br.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
open(f"{OUT}/recheck5.json", "w").write(json.dumps(res, ensure_ascii=False, indent=1))
