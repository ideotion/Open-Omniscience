"""Independent recheck of row T's six reported defects on a fresh encrypted instance (port 8848,
booted LOCKED, airplane mode). Drives the real UI; page.evaluate is used only to READ state and
to fetch API payloads for comparison (and to close an unrelated guide dialog)."""
import json, re, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8848"
OUT = "/tmp/claude-0/walk/T-recheck"
PASS = "walk-pass-2026"
res = {"page_errors": [], "console_errors": [], "http_errors": []}


def hook(pg, tag):
    pg.on("pageerror", lambda e: res["page_errors"].append(f"{tag}: {e}"))
    pg.on("console", lambda m: res["console_errors"].append(f"{tag}: {m.text[:240]}") if m.type == "error" else None)
    pg.on("response", lambda r: res["http_errors"].append(f"{tag}: {r.status} {r.url}") if r.status >= 400 else None)


def close_wizard(pg):
    pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")


TM_STATE = """async () => {
  const b = document.getElementById('net-toggle'), pl = document.getElementById('net-plane');
  const act = await (await fetch('/api/scheduler/activity')).json();
  const st = await (await fetch('/api/scheduler/status')).json();
  const nw = await (await fetch('/api/system/network')).json();
  const h = await (await fetch('/api/health')).json();
  return {
    plane_fill: pl && pl.getAttribute('fill'), btn_color_inline: b && b.style.color,
    btn_color_computed: b && getComputedStyle(b).color, title: b && b.getAttribute('title'),
    summary_state: (document.querySelector('#tm-summary .tm-state') || {}).textContent,
    summary_state_cls: (document.querySelector('#tm-summary .tm-state') || {}).className,
    summary_text: (document.getElementById('tm-summary') || {}).innerText,
    health_pill: (document.getElementById('health') || {}).innerText,
    api_network_online: nw.online, api_status_online: st.online,
    api_activity_has_online_key: Object.prototype.hasOwnProperty.call(act, 'online'),
    api_activity_online: act.online, api_health: h,
    lang: document.documentElement.lang, dir: document.documentElement.dir };
}"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); hook(pg, "app")
    # ---- unlock through the real form ----
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_selector("#pw", state="visible", timeout=30000)
    pg.fill("#pw", PASS); pg.click("#btn-unlock")
    pg.wait_for_function("() => location.hash === '#home'", timeout=60000)
    pg.wait_for_timeout(5000); close_wizard(pg)
    res["lock_state"] = pg.evaluate("async () => (await (await fetch('/api/system/lock-state')).json())")
    res["app_offline"] = pg.evaluate("""async () => ({
      plane_fill: document.getElementById('net-plane').getAttribute('fill'),
      body_net_offline: document.body.classList.contains('net-offline'),
      api: (await (await fetch('/api/system/network')).json()),
      coach_shown: document.getElementById('net-coach').classList.contains('show'),
      health: document.getElementById('health').innerText })""")
    pg.screenshot(path=f"{OUT}/T-recheck-app-offline-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 260})

    # ---- DEFECT 4: coach re-anchor on a live language/direction switch ----
    def coach_geo():
        return pg.evaluate("""() => { const c=document.getElementById('net-coach'), b=document.getElementById('net-toggle');
          const cr=c.getBoundingClientRect(), br=b.getBoundingClientRect(), a=c.querySelector('.coach-arrow');
          const ar = a ? a.getBoundingClientRect() : null;
          return {shown: c.classList.contains('show'), coach:{l:Math.round(cr.left), r:Math.round(cr.right), t:Math.round(cr.top), b:Math.round(cr.bottom)},
            plane:{l:Math.round(br.left), r:Math.round(br.right), t:Math.round(br.top), b:Math.round(br.bottom)},
            arrow: ar ? {x:Math.round(ar.left+ar.width/2), y:Math.round(ar.top+ar.height/2)} : null,
            arrow_to_plane_px: ar ? Math.round(Math.hypot((ar.left+ar.width/2)-(br.left+br.width/2), (ar.top+ar.height/2)-(br.top+br.height/2))) : null,
            dir: document.documentElement.dir, lang: document.documentElement.lang,
            style: {left: c.style.left, top: c.style.top}}; }""")
    coach = {"en_before": coach_geo()}
    for code in ["ar", "zh", "en"]:
        pg.mouse.move(700, 900); pg.click("#lang-switch"); pg.wait_for_timeout(300)
        pg.click(f"#lang-menu [data-lang='{code}']")
        pg.wait_for_function(f"() => document.documentElement.lang === '{code}'"); pg.wait_for_timeout(2500)
        coach[code] = coach_geo()
        if code == "ar":
            pg.screenshot(path=f"{OUT}/T-recheck-coach-ar.png")
            pg.set_viewport_size({"width": 1434, "height": 950}); pg.wait_for_timeout(600)
            coach["ar_after_resize"] = coach_geo()
            pg.set_viewport_size({"width": 1440, "height": 950}); pg.wait_for_timeout(600)
            coach["ar_after_resize_back"] = coach_geo()
    res["defect4_coach"] = coach

    # ---- DEFECT 1 + 2: open /tasks through the top-bar #tm-open ----
    with ctx.expect_page(timeout=15000) as newp:
        pg.click("#tm-open")
    tm = newp.value; hook(tm, "tasks")
    tm.wait_for_load_state("domcontentloaded")
    res["tasks_url"] = tm.url
    tries = []
    for wait in (6000, 12000, 20000):
        if tries:
            tm.reload(wait_until="domcontentloaded")
        tm.wait_for_timeout(wait)
        tm.hover("#net-toggle"); tm.wait_for_timeout(800)
        s = tm.evaluate(TM_STATE); s["waited_ms"] = wait; tries.append(s)
    res["defect1_tasks_offline_tries"] = tries
    tm.screenshot(path=f"{OUT}/T-recheck-tasks-offline-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 220})
    # Schedule panel while offline
    tm.click("#tm-tabs [data-panel='schedule']"); tm.wait_for_timeout(1500)
    res["defect1_schedule_panel_offline"] = tm.evaluate("() => document.getElementById('sched-body').innerText.slice(0, 600)")
    tm.screenshot(path=f"{OUT}/T-recheck-tasks-schedule-offline-en.png")
    tm.click("#tm-tabs [data-panel='processes']"); tm.wait_for_timeout(500)

    # the /tasks plane click while (really) offline: it shows online, so a click POSTs online:false.
    # Sample every 50 ms to see the brief correct paint and the revert.
    tm.evaluate("""() => { window.__s = []; const t0 = performance.now();
      const iv = setInterval(() => { const pl = document.getElementById('net-plane');
        window.__s.push([Math.round(performance.now()-t0), pl.getAttribute('fill'),
          (document.querySelector('#tm-summary .tm-state')||{}).textContent,
          document.getElementById('net-toggle').getAttribute('title').slice(0, 40)]);
        if (performance.now()-t0 > 12000) clearInterval(iv); }, 50); }""")
    tm.click("#net-toggle")
    tm.wait_for_timeout(12500)
    samples = tm.evaluate("() => window.__s")
    # compress runs
    runs = []
    for s in samples:
        key = (s[1], s[2], s[3])
        if not runs or runs[-1]["key"] != key:
            runs.append({"key": key, "from_ms": s[0], "to_ms": s[0]})
        else:
            runs[-1]["to_ms"] = s[0]
    res["defect1_after_click_runs"] = [{"fill": r["key"][0], "state": r["key"][1], "title": r["key"][2], "from_ms": r["from_ms"], "to_ms": r["to_ms"]} for r in runs]
    res["defect1_after_click_final"] = tm.evaluate(TM_STATE)
    res["defect1_conn_text"] = tm.evaluate("() => document.getElementById('tm-conn').innerText")
    tm.screenshot(path=f"{OUT}/T-recheck-tasks-after-offline-click-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 220})

    # ---- DEFECT 5: summary strip language after a live switch from a non-English locale ----
    sw = {}
    for code in ["fr", "ar", "zh", "en"]:
        tm.mouse.move(700, 900); tm.click("#lang-switch"); tm.wait_for_timeout(300)
        tm.evaluate("""() => { window.__l = []; const t0 = performance.now();
          const iv = setInterval(() => { window.__l.push([Math.round(performance.now()-t0),
            (document.getElementById('tm-summary')||{}).innerText.replace(/\\s+/g,' ').slice(0,120),
            document.getElementById('net-toggle').getAttribute('title').slice(0,50),
            (document.getElementById('health')||{}).innerText]);
            if (performance.now()-t0 > 9000) clearInterval(iv); }, 100); }""")
        tm.click(f"#lang-menu [data-lang='{code}']")
        tm.wait_for_function(f"() => document.documentElement.lang === '{code}'")
        tm.wait_for_timeout(9300)
        L = tm.evaluate("() => window.__l")
        runs = []
        for s in L:
            key = (s[1], s[2], s[3])
            if not runs or runs[-1]["key"] != key:
                runs.append({"key": key, "from_ms": s[0]})
        sw[code] = [{"summary": r["key"][0], "title": r["key"][1], "health": r["key"][2], "from_ms": r["from_ms"]} for r in runs]
        if code in ("zh",):
            tm.screenshot(path=f"{OUT}/T-recheck-tasks-zh-after-ar.png", clip={"x": 0, "y": 0, "width": 1440, "height": 220})
        if code == "ar":
            tm.screenshot(path=f"{OUT}/T-recheck-tasks-ar.png", clip={"x": 0, "y": 0, "width": 1440, "height": 220})
    res["defect5_lang_switch_runs"] = sw
    tm.close()
    ctx.close()

    # ---- DEFECT 3 + 6: 375 px ----
    FIND = """() => { const cw = document.documentElement.clientWidth; const out = [];
      for (const e of document.querySelectorAll('body *')) { const r = e.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
        const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        if (r.right > cw + 1 || r.left < -1) out.push({el: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/).slice(0,3).join('.') : ''),
          left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width), pos: cs.position, text: (e.innerText || '').trim().slice(0, 50)}); }
      return {overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, sw: document.documentElement.scrollWidth, cw, n: out.length, first: out.slice(0, 20)}; }"""
    phone = {}
    for scheme in ("dark", "light"):
        c2 = br.new_context(viewport={"width": 375, "height": 812}, color_scheme=scheme)
        p2 = c2.new_page(); hook(p2, f"phone-{scheme}")
        p2.goto(BASE + "/", wait_until="domcontentloaded")
        p2.wait_for_function("() => location.hash === '#home'", timeout=30000)
        p2.wait_for_timeout(6000); close_wizard(p2)
        phone[f"home_{scheme}"] = p2.evaluate(FIND)
        phone[f"home_{scheme}_tier"] = p2.evaluate("""() => { const e = document.getElementById('home-tier'); if (!e) return null;
          const r = e.getBoundingClientRect(), c = e.querySelector('.tier-caveat'); const cr = c ? c.getBoundingClientRect() : null;
          return {hidden: e.hidden, cls: e.className, text: e.innerText, w: Math.round(r.width), left: Math.round(r.left), right: Math.round(r.right),
                  ws: getComputedStyle(e).whiteSpace, caveat_right: cr ? Math.round(cr.right) : null,
                  parent_w: Math.round(e.parentElement.getBoundingClientRect().width)}; }""")
        # dismiss the coach (not under test) through its own button, then re-measure
        if p2.evaluate("() => document.getElementById('net-coach').classList.contains('show')"):
            p2.click("#net-coach-dismiss"); p2.wait_for_timeout(400)
        phone[f"home_{scheme}_nocoach_overflow"] = p2.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if scheme == "dark":
            p2.screenshot(path=f"{OUT}/T-recheck-375-home-en.png")
            p2.evaluate("() => window.scrollTo(0,0)")
        p2.goto(BASE + "/tasks", wait_until="domcontentloaded"); p2.wait_for_timeout(5000)
        phone[f"tasks_{scheme}"] = p2.evaluate(FIND)
        phone[f"tasks_{scheme}_tabs"] = p2.evaluate("""() => Array.from(document.querySelectorAll('#tm-tabs button')).map(b => ({t: b.innerText, right: Math.round(b.getBoundingClientRect().right)}))""")
        if scheme == "dark":
            p2.screenshot(path=f"{OUT}/T-recheck-375-tasks-en.png")
        c2.close()
    res["defect3_6_phone"] = phone
    br.close()

open(f"{OUT}/recheck1.json", "w").write(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1)[:20000])
