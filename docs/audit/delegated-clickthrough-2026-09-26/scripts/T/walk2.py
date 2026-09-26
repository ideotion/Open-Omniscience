"""Row T click-through, boot 2 (OO_NO_SCHEDULER=1: online, nothing scheduled): T8.
Both planes' hovers online, the Task manager tab's live language switch (sampled every 100 ms,
with the page's own refresh requests timestamped so the listener and the poll can be told
apart), then ONE click on the Task manager's plane to go offline, sampled for 12 s."""
import json, re, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8846"; OUT = "/tmp/claude-0/walk/T"; PASS = "walk-pass-2026"
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")
R = {"page_errors": [], "console_errors": [], "http_errors": [], "junk": [], "T8": {}}
T0 = time.time()


def attach(pg, tag):
    pg.on("pageerror", lambda e: R["page_errors"].append(f"[{tag}] {e}"))
    pg.on("console", lambda m: R["console_errors"].append(f"[{tag}] {m.text[:300]}") if m.type == "error" else None)
    pg.on("response", lambda r: R["http_errors"].append(f"[{tag}] {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)


TM_JS = """() => { const b = document.getElementById('net-toggle'); const st = document.querySelector('#tm-summary .tm-state');
  return {lang: document.documentElement.lang, dir: document.documentElement.dir || 'ltr', title: b.getAttribute('title'),
    fill: document.getElementById('net-plane').getAttribute('fill'), color: getComputedStyle(b).color, inline: b.style.color,
    state: st ? st.textContent.trim() : null, conn: (document.getElementById('tm-conn') || {}).textContent || ''}; }"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); attach(pg, "app")
    s = R["T8"]
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(1500)
    if "/unlock" in pg.url:
        pg.fill("#pw", PASS); pg.click("#btn-unlock")
        pg.wait_for_url(lambda u: "/unlock" not in u, timeout=90000)
    pg.wait_for_timeout(7000)
    s["guide_closed"] = pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) { d.close(); return true; } return false; }")
    s["api_network_boot"] = pg.evaluate("async () => (await (await fetch('/api/system/network')).json())")
    s["scheduler_status"] = pg.evaluate("async () => { const a = await (await fetch('/api/scheduler/status')).json(); return {running: a.running, active: a.active, online: a.online, wiki_lane: a.wiki_lane}; }")
    s["app_plane"] = pg.evaluate("() => ({fill: document.getElementById('net-plane').getAttribute('fill'), off: document.getElementById('net-toggle').classList.contains('off'), body_offline: document.body.classList.contains('net-offline'), coach: document.getElementById('net-coach').classList.contains('show')})")
    pg.hover("#net-toggle"); pg.wait_for_timeout(600)
    s["app_hover_tip"] = pg.evaluate("() => { const t = document.getElementById('oo-tip'); return {show: t.classList.contains('show'), text: t.textContent}; }")
    pg.screenshot(path=f"{OUT}/T-T8-app-online-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})

    # the Task manager tab
    pg.mouse.move(700, 900)
    with ctx.expect_page() as pinfo:
        pg.click("#tm-open")
    tm = pinfo.value; attach(tm, "tasks")
    act_times = []
    tm.on("request", lambda r: act_times.append(round(time.time() - T0, 3)) if "/api/scheduler/activity" in r.url else None)
    tm.wait_for_load_state("domcontentloaded"); tm.set_viewport_size({"width": 1440, "height": 950})
    tm.wait_for_function("() => document.querySelector('#tm-summary .tm-state')", timeout=30000); tm.wait_for_timeout(1500)
    tm.hover("#net-toggle"); tm.wait_for_timeout(1200)
    s["tm_en"] = tm.evaluate(TM_JS)
    tm.screenshot(path=f"{OUT}/T-T8-tasks-online-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})

    def tm_lang(code):
        tm.mouse.move(700, 900); tm.click("#lang-switch"); tm.wait_for_timeout(300)
        t_click = round(time.time() - T0, 3)
        tm.click(f"#lang-menu [data-lang='{code}']")
        samples = []
        for _ in range(25):          # 2.5 s at 100 ms
            v = tm.evaluate("() => [document.documentElement.lang, document.getElementById('net-toggle').getAttribute('title'), (document.querySelector('#tm-summary .tm-state')||{}).textContent]")
            samples.append([round(time.time() - T0, 3)] + v)
            tm.wait_for_timeout(100)
        return t_click, samples

    s["switches"] = {}
    for code in ["fr", "ar", "zh", "en"]:
        t_click, samples = tm_lang(code)
        tm.hover("#net-toggle"); tm.wait_for_timeout(1200)
        final = tm.evaluate(TM_JS)
        # first sample where the title is in the target language (compared to the locale file below)
        s["switches"][code] = {"t_click": t_click, "samples": samples, "final": final}
        if code != "en":
            tm.screenshot(path=f"{OUT}/_T8-tasks-online-{code}.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})
        for v in samples:
            for m in JUNK.finditer(" ".join(str(x) for x in v[1:])):
                R["junk"].append(f"T8 {code}: {v}")
        # summary-strip language lag: how long until the state label re-renders in the new language
        lag = []
        for _ in range(16):
            lag.append([round(time.time() - T0, 3), tm.evaluate("() => (document.querySelector('#tm-summary .tm-state')||{}).textContent"),
                        tm.evaluate("() => (document.getElementById('tm-conn')||{}).textContent")])
            tm.wait_for_timeout(500)
        s["switches"][code]["summary_lag"] = lag
    s["activity_request_times"] = act_times[:]

    # the one click: go offline from the Task manager tab
    tm.mouse.move(700, 900)
    t_click = round(time.time() - T0, 3)
    tm.click("#net-toggle")
    after = []
    for _ in range(60):   # 12 s at 200 ms
        after.append([round(time.time() - T0, 3)] + tm.evaluate("() => [document.getElementById('net-plane').getAttribute('fill'), document.getElementById('net-toggle').getAttribute('title'), (document.querySelector('#tm-summary .tm-state')||{}).textContent, (document.getElementById('tm-conn')||{}).textContent]"))
        if len(after) == 3:
            tm.screenshot(path=f"{OUT}/T-T8-tasks-just-after-click-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})
        tm.wait_for_timeout(200)
    s["click_t"] = t_click; s["after_click"] = after
    s["api_network_after_click"] = tm.evaluate("async () => (await (await fetch('/api/system/network')).json())")
    tm.hover("#net-toggle"); tm.wait_for_timeout(1200)
    s["tm_after_hover"] = tm.evaluate(TM_JS)
    tm.screenshot(path=f"{OUT}/T-T8-tasks-after-offline-12s-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})
    s["activity_request_times_all"] = act_times[:]
    # the app tab repaints from its own poll
    pg.bring_to_front(); pg.wait_for_timeout(6500)
    s["app_after"] = pg.evaluate("() => ({fill: document.getElementById('net-plane').getAttribute('fill'), title: document.getElementById('net-toggle').getAttribute('title') || document.getElementById('net-toggle').dataset.ooTip, body_offline: document.body.classList.contains('net-offline')})")
    tm.close(); ctx.close(); br.close()
json.dump(R, open(f"{OUT}/walk2.json", "w"), ensure_ascii=False, indent=1)
print("done")
