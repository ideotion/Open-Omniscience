"""Recheck part 4 (a row-T surface the walker passed): the #rate-toggle hover after a LIVE language
switch vs a cold load in that language. Real hover; reads the #oo-tip bubble text."""
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8848"; OUT = "/tmp/claude-0/walk/T-recheck"
res = {"live": {}, "cold": {}}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_function("() => location.hash === '#home'", timeout=30000)
    pg.wait_for_timeout(5000)
    pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    if pg.evaluate("() => document.getElementById('net-coach').classList.contains('show')"):
        pg.click("#net-coach-dismiss"); pg.wait_for_timeout(300)
    for code in ["fr", "ar", "zh"]:
        pg.mouse.move(700, 900); pg.click("#lang-switch"); pg.wait_for_timeout(300)
        pg.click(f"#lang-menu [data-lang='{code}']")
        pg.wait_for_function(f"() => document.documentElement.lang === '{code}'"); pg.wait_for_timeout(3000)
        pg.mouse.move(700, 900); pg.wait_for_timeout(300)
        pg.hover("#rate-toggle"); pg.wait_for_timeout(900)
        res["live"][code] = pg.evaluate("() => ({title: document.getElementById('rate-toggle').getAttribute('title'), tip: (document.getElementById('oo-tip')||{}).textContent, net_title: document.getElementById('net-toggle').getAttribute('title').slice(0,60)})")
        if code == "ar":
            pg.screenshot(path=f"{OUT}/T-recheck-rate-hover-ar-live.png", clip={"x": 0, "y": 0, "width": 800, "height": 200})
    # cold load in the last language (zh), then ar
    for code in ["zh", "ar"]:
        if code == "ar":
            pg.mouse.move(700, 900); pg.click("#lang-switch"); pg.wait_for_timeout(300)
            pg.click("#lang-menu [data-lang='ar']"); pg.wait_for_function("() => document.documentElement.lang === 'ar'"); pg.wait_for_timeout(800)
        pg.reload(wait_until="domcontentloaded"); pg.wait_for_function("() => location.hash === '#home'", timeout=30000)
        pg.wait_for_timeout(5000)
        pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
        pg.mouse.move(700, 900); pg.wait_for_timeout(300)
        pg.hover("#rate-toggle"); pg.wait_for_timeout(900)
        res["cold"][code] = pg.evaluate("() => ({lang: document.documentElement.lang, title: document.getElementById('rate-toggle').getAttribute('title'), tip: (document.getElementById('oo-tip')||{}).textContent})")
    br.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
open(f"{OUT}/recheck4.json", "w").write(json.dumps(res, ensure_ascii=False, indent=1))
