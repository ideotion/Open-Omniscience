"""Boot 1 (offline) follow-ups: (a) T5 retried three times with long waits, straight on /tasks;
(b) the app's OWN plane hover in fr/ar/zh while offline, through the real switcher."""
import json, time
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8846"; OUT = "/tmp/claude-0/walk/T"
res = {"errors": []}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page()
    pg.on("pageerror", lambda e: res["errors"].append("pageerror " + str(e)))
    pg.on("console", lambda m: res["errors"].append("console " + m.text[:200]) if m.type == "error" else None)
    pg.on("response", lambda r: res["errors"].append(f"http {r.status} {r.url}") if r.status >= 400 else None)
    tries = []
    for i, wait in enumerate([6000, 12000, 20000]):
        pg.goto(BASE + "/tasks", wait_until="domcontentloaded"); pg.wait_for_timeout(wait)
        pg.hover("#net-toggle"); pg.wait_for_timeout(1200)
        tries.append(pg.evaluate("""async () => ({waited_ms: %d,
          title: document.getElementById('net-toggle').getAttribute('title'),
          fill: document.getElementById('net-plane').getAttribute('fill'),
          state: (document.querySelector('#tm-summary .tm-state') || {}).textContent,
          api_network: (await (await fetch('/api/system/network')).json()).online,
          api_status_online: (await (await fetch('/api/scheduler/status')).json()).online,
          api_activity_has_online: 'online' in (await (await fetch('/api/scheduler/activity')).json())})""" % wait))
    res["T5_retries"] = tries
    pg.screenshot(path=f"{OUT}/T-T5-tasks-while-offline-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})
    # (b) the app's own plane, offline, in fr / ar / zh
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(6000)
    pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    app = {}
    for code in ["fr", "ar", "zh", "en"]:
        pg.mouse.move(700, 900); pg.click("#lang-switch"); pg.wait_for_timeout(300)
        pg.click(f"#lang-menu [data-lang='{code}']")
        pg.wait_for_function(f"() => document.documentElement.lang === '{code}'"); pg.wait_for_timeout(800)
        pg.hover("#net-toggle"); pg.wait_for_timeout(500)
        app[code] = pg.evaluate("() => ({tip: document.getElementById('oo-tip').textContent, fill: document.getElementById('net-plane').getAttribute('fill')})")
    res["app_offline_titles"] = app
    br.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
