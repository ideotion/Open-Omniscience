"""Recheck part 2: (a) validate the proposed fixes without touching the repo — a Playwright route
adds `online` to /api/scheduler/activity (the server-side fix's effect), and injected CSS for the
two 375 px overflows; (b) the coach on a COLD Arabic load vs after a live switch; screenshots."""
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8848"
OUT = "/tmp/claude-0/walk/T-recheck"
res = {"page_errors": [], "console_errors": [], "http_errors": []}


def hook(pg, tag):
    pg.on("pageerror", lambda e: res["page_errors"].append(f"{tag}: {e}"))
    pg.on("console", lambda m: res["console_errors"].append(f"{tag}: {m.text[:240]}") if m.type == "error" else None)
    pg.on("response", lambda r: res["http_errors"].append(f"{tag}: {r.status} {r.url}") if r.status >= 400 else None)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox"])

    # (a1) /tasks with `online` added to the activity payload from the server's own kill-switch read
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); hook(pg, "tasks-fixsim")

    def add_online(route):
        r = route.fetch()
        body = r.json()
        import urllib.request
        nw = json.loads(urllib.request.urlopen(BASE + "/api/system/network", timeout=5).read())
        body["online"] = nw["online"]
        route.fulfill(response=r, json=body)
    pg.route("**/api/scheduler/activity", add_online)
    pg.goto(BASE + "/tasks", wait_until="domcontentloaded"); pg.wait_for_timeout(7000)
    pg.hover("#net-toggle"); pg.wait_for_timeout(600)
    res["fixsim_tasks_offline"] = pg.evaluate("""() => ({fill: document.getElementById('net-plane').getAttribute('fill'),
      color: getComputedStyle(document.getElementById('net-toggle')).color,
      title: document.getElementById('net-toggle').getAttribute('title'),
      state: (document.querySelector('#tm-summary .tm-state')||{}).textContent})""")
    pg.click("#tm-tabs [data-panel='schedule']"); pg.wait_for_timeout(1200)
    res["fixsim_schedule"] = pg.evaluate("() => document.getElementById('sched-body').innerText.slice(0, 300)")
    pg.click("#tm-tabs [data-panel='processes']"); pg.wait_for_timeout(300)
    pg.screenshot(path=f"{OUT}/T-recheck-tasks-offline-with-online-key-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 220})
    # live switch to fr / ar / zh with the key present: the Q1126 offline title re-translates
    titles = {}
    for code in ["fr", "ar", "zh", "en"]:
        pg.mouse.move(700, 900); pg.click("#lang-switch"); pg.wait_for_timeout(300)
        pg.click(f"#lang-menu [data-lang='{code}']")
        pg.wait_for_function(f"() => document.documentElement.lang === '{code}'"); pg.wait_for_timeout(700)
        titles[code] = pg.evaluate("() => document.getElementById('net-toggle').getAttribute('title')")
    res["fixsim_offline_titles"] = titles
    ctx.close()

    # (a2) 375 px with the proposed CSS
    c2 = br.new_context(viewport={"width": 375, "height": 812}); p2 = c2.new_page(); hook(p2, "phone-fixsim")
    p2.goto(BASE + "/", wait_until="domcontentloaded")
    p2.wait_for_function("() => location.hash === '#home'", timeout=30000); p2.wait_for_timeout(6000)
    p2.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    res["home375_before"] = p2.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    p2.screenshot(path=f"{OUT}/T-recheck-375-home-tier-before-en.png", clip={"x": 0, "y": 0, "width": 375, "height": 300})
    p2.add_style_tag(content=".corpus-tier{flex-wrap:wrap;white-space:normal;max-width:100%} .corpus-tier>span{white-space:nowrap}")
    p2.wait_for_timeout(400)
    res["home375_after_css"] = p2.evaluate("""() => { const e=document.getElementById('home-tier'), r=e.getBoundingClientRect(), c=e.querySelector('.tier-caveat').getBoundingClientRect();
      return {overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, tier_right: Math.round(r.right), caveat_right: Math.round(c.right), h: Math.round(r.height)}; }""")
    p2.screenshot(path=f"{OUT}/T-recheck-375-home-tier-with-proposed-css-en.png", clip={"x": 0, "y": 0, "width": 375, "height": 300})
    p2.goto(BASE + "/tasks", wait_until="domcontentloaded"); p2.wait_for_timeout(4000)
    res["tasks375_before"] = p2.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    p2.add_style_tag(content=".tm-tabs{overflow-x:auto;scrollbar-width:thin} .tm-tabs button{flex:none}")
    p2.wait_for_timeout(400)
    res["tasks375_after_css"] = p2.evaluate("() => ({overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, tabs_scrollW: document.getElementById('tm-tabs').scrollWidth, tabs_clientW: document.getElementById('tm-tabs').clientWidth})")
    c2.close()

    # (b) the coach on a COLD Arabic load (fresh profile, language chosen through the switcher, then reload)
    c3 = br.new_context(viewport={"width": 1440, "height": 950}); p3 = c3.new_page(); hook(p3, "coach-cold-ar")
    p3.goto(BASE + "/", wait_until="domcontentloaded"); p3.wait_for_function("() => location.hash === '#home'", timeout=30000)
    p3.wait_for_timeout(3000)
    p3.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    p3.mouse.move(700, 900); p3.click("#lang-switch"); p3.wait_for_timeout(300)
    p3.click("#lang-menu [data-lang='ar']"); p3.wait_for_function("() => document.documentElement.lang === 'ar'")
    p3.wait_for_timeout(1500)
    live = p3.evaluate("""() => { const c=document.getElementById('net-coach'), b=document.getElementById('net-toggle');
      const cr=c.getBoundingClientRect(), r=b.getBoundingClientRect();
      return {shown: c.classList.contains('show'), coach_l: Math.round(cr.left), coach_r: Math.round(cr.right), coach_t: Math.round(cr.top), plane_l: Math.round(r.left), plane_r: Math.round(r.right)}; }""")
    res["coach_live_switch_ar"] = live
    p3.screenshot(path=f"{OUT}/T-recheck-coach-ar-live-switch.png", clip={"x": 0, "y": 0, "width": 1440, "height": 300})
    p3.reload(wait_until="domcontentloaded"); p3.wait_for_function("() => location.hash === '#home'", timeout=30000)
    p3.wait_for_timeout(4000)
    p3.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    cold = p3.evaluate("""() => { const c=document.getElementById('net-coach'), b=document.getElementById('net-toggle');
      const cr=c.getBoundingClientRect(), r=b.getBoundingClientRect();
      const topbar = document.querySelector('.topbar').getBoundingClientRect();
      const under = [];
      for (const id of ['health','llm','act-host','lang-switch','tm-open','app-shutdown','net-toggle','rate-toggle','omni']) { const e=document.getElementById(id); if (!e) continue; const q=e.getBoundingClientRect();
        if (q.width && !(q.right < cr.left || q.left > cr.right || q.bottom < cr.top || q.top > cr.bottom)) under.push(id); }
      return {lang: document.documentElement.lang, dir: document.documentElement.dir, shown: c.classList.contains('show'),
        coach: [Math.round(cr.left), Math.round(cr.top), Math.round(cr.right), Math.round(cr.bottom)],
        plane: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)], topbar_bottom: Math.round(topbar.bottom), overlaps: under}; }""")
    res["coach_cold_ar"] = cold
    p3.screenshot(path=f"{OUT}/T-recheck-coach-ar-cold-load.png", clip={"x": 0, "y": 0, "width": 1440, "height": 300})
    c3.close()
    br.close()

open(f"{OUT}/recheck2.json", "w").write(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
