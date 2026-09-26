"""Probe: does the 'Go online?' consent window's lane list ever fill in? (T4 saw '…' after 1.2 s)"""
import json
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8846"; OUT = "/tmp/claude-0/walk/T"
res = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append("pageerror " + str(e)))
    pg.on("console", lambda m: errs.append(m.type + " " + m.text[:300]) if m.type in ("error", "warning") else None)
    pg.add_init_script("window.addEventListener('unhandledrejection', e => console.error('UNHANDLED', String(e.reason && (e.reason.stack || e.reason))));")
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(7000)
    pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    res["oo_net_lanes_len"] = pg.evaluate("() => (window.OO_NET_LANES || []).length")
    pg.click("#net-toggle")   # offline -> the consent window
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=15000)
    samples = []
    for i in range(12):
        samples.append((i, pg.evaluate("() => document.getElementById('net-consent-lanes').innerText.slice(0,200)")))
        pg.wait_for_timeout(1000)
    res["samples"] = samples
    pg.screenshot(path=f"{OUT}/_probe-consent-lanes.png")
    pg.click("#net-consent-cancel"); pg.wait_for_timeout(800)
    res["online_after_cancel"] = pg.evaluate("async () => (await (await fetch('/api/system/network')).json()).online")
    res["errs"] = errs
    br.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
