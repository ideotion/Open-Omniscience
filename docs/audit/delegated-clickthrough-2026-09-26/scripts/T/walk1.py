"""Row T click-through, boot 1 (offline, encrypted store): T1-T7, the 375px pass, and the
read-only observations for T9/T10. Drives the real UI in Chromium via Playwright."""
import json, os, re, sys, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE", "http://127.0.0.1:8846")
OUT = "/tmp/claude-0/walk/T"
PASS = "walk-pass-2026"
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")
R = {"page_errors": [], "console_errors": [], "http_errors": [], "junk": [], "steps": {}}


def save():
    json.dump(R, open(f"{OUT}/walk1.json", "w"), ensure_ascii=False, indent=1)


def attach(pg, tag):
    pg.on("pageerror", lambda e: R["page_errors"].append(f"[{tag}] {e}"))
    pg.on("console", lambda m: R["console_errors"].append(f"[{tag}] {m.text[:300]}") if m.type == "error" else None)
    pg.on("response", lambda r: R["http_errors"].append(f"[{tag}] {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)


def junk(where, text):
    for m in JUNK.finditer(text or ""):
        s = max(0, m.start() - 60)
        R["junk"].append(f"{where}: ...{text[s:m.end()+60]!r}")


def unlock(pg):
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(1500)
    info = {"url_before": pg.url}
    if "/unlock" in pg.url:
        info["legal_visible"] = pg.evaluate("() => { const v=document.getElementById('view-legal'); return !!v && !v.classList.contains('hidden'); }")
        info["unlock_visible"] = pg.evaluate("() => { const v=document.getElementById('view-unlock'); return !!v && !v.classList.contains('hidden'); }")
        pg.screenshot(path=f"{OUT}/T-T1-unlock-en.png")
        pg.fill("#pw", PASS)
        pg.click("#btn-unlock")
        pg.wait_for_url(lambda u: "/unlock" not in u, timeout=90000)
    pg.wait_for_load_state("domcontentloaded")
    info["url_after"] = pg.url
    return info


def close_guide(pg):
    return pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) { d.close(); return true; } return false; }")


def app_lang(pg, code):
    pg.mouse.move(700, 900)
    pg.click("#lang-switch")
    pg.wait_for_timeout(300)
    pg.click(f"#lang-menu [data-lang='{code}']")
    pg.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=15000)
    pg.wait_for_timeout(900)


COACH_JS = """() => {
  const el = document.getElementById('net-coach');
  const out = {show: el.classList.contains('show'), prominent: el.classList.contains('prominent'),
    body: el.querySelector('.coach-body').textContent.trim(), sub: el.querySelector('.coach-sub').textContent.trim(),
    dir: document.documentElement.dir || 'ltr', lang: document.documentElement.lang, theme: document.documentElement.getAttribute('data-theme') || '(root ink)'};
  out.buttons = {};
  for (const id of ['net-coach-dismiss', 'net-coach-go']) {
    const e = document.getElementById(id), cs = getComputedStyle(e), r = e.getBoundingClientRect();
    out.buttons[id] = {text: e.textContent.trim(), cls: e.className, bg: cs.backgroundColor, fg: cs.color,
      fw: cs.fontWeight, fs: cs.fontSize, ff: cs.fontFamily.slice(0, 40), h: Math.round(r.height*100)/100, w: Math.round(r.width*100)/100,
      x: Math.round(r.x), border: [cs.borderTopWidth, cs.borderTopStyle, cs.borderTopColor].join(' '),
      bw: [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth].join(','),
      outline: cs.outlineStyle + ' ' + cs.outlineWidth, opacity: cs.opacity, filter: cs.filter,
      shadow: cs.boxShadow, padding: cs.padding, radius: cs.borderRadius,
      clipped: e.scrollWidth > e.clientWidth + 1};
  }
  const a = document.getElementById('net-coach-dismiss'), b = document.getElementById('net-coach-go');
  const ca = getComputedStyle(a), cb = getComputedStyle(b);
  const keys = ['backgroundColor','color','fontWeight','fontSize','borderTopWidth','borderTopStyle','outlineStyle','opacity','filter','boxShadow','paddingTop','paddingBottom','borderRadius','fontFamily'];
  out.diff = keys.filter(k => ca[k] !== cb[k]).map(k => k + ': ' + ca[k] + ' vs ' + cb[k]);
  if (Math.abs(a.getBoundingClientRect().height - b.getBoundingClientRect().height) > 0.5) out.diff.push('height');
  const cr = el.getBoundingClientRect(), pr = document.getElementById('net-toggle').getBoundingClientRect();
  const ar = el.querySelector('.coach-arrow').getBoundingClientRect();
  const acx = ar.x + ar.width/2, acy = ar.y + ar.height/2;
  const dx = Math.max(pr.left - acx, 0, acx - pr.right), dy = Math.max(pr.top - acy, 0, acy - pr.bottom);
  out.place = {coach: [Math.round(cr.x), Math.round(cr.y), Math.round(cr.width), Math.round(cr.height)],
    plane: [Math.round(pr.x), Math.round(pr.y), Math.round(pr.width), Math.round(pr.height)],
    arrow_center: [Math.round(acx), Math.round(acy)], arrow_to_plane_px: Math.round(Math.hypot(dx, dy)),
    in_viewport: cr.left >= 0 && cr.right <= innerWidth && cr.top >= 0 && cr.bottom <= innerHeight};
  return out;
}"""


def coach_clip(pg, path):
    box = pg.evaluate("""() => { const a = document.getElementById('net-coach').getBoundingClientRect(), b = document.getElementById('net-toggle').getBoundingClientRect();
      const x = Math.min(a.left, b.left) - 16, y = Math.min(a.top, b.top) - 12, r = Math.max(a.right, b.right) + 16, bt = Math.max(a.bottom, b.bottom) + 12;
      return {x: Math.max(0, x), y: Math.max(0, y), width: Math.min(innerWidth, r) - Math.max(0, x), height: Math.min(innerHeight, bt) - Math.max(0, y)}; }""")
    pg.screenshot(path=path, clip=box)


def toasts(pg):
    return pg.evaluate("() => [...document.querySelectorAll('#toast .note')].map(n => n.textContent.trim())")


def net_state(pg):
    return pg.evaluate("""() => { const b = document.getElementById('net-toggle'); const tb = document.querySelector('header.topbar');
      return {plane_fill: document.getElementById('net-plane').getAttribute('fill'), btn_off: b.classList.contains('off'),
        body_net_offline: document.body.classList.contains('net-offline'), topbar_shadow: getComputedStyle(tb).boxShadow,
        consent_open: document.getElementById('net-consent').open,
        title: b.getAttribute('title') || b.dataset.ooTip || ''}; }""")


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); attach(pg, "app")

    # ------------------------------------------------------------------ T1
    s = {}
    s["unlock"] = unlock(pg)
    pg.wait_for_timeout(8000)   # "wait 5-10 seconds without clicking"
    s["guide_open"] = pg.evaluate("() => { const d=document.getElementById('guide-wizard'); return !!(d && d.open); }")
    s["net"] = net_state(pg)
    s["coach_show_after_8s"] = pg.evaluate("() => document.getElementById('net-coach').classList.contains('show')")
    s["api_network"] = pg.evaluate("async () => (await (await fetch('/api/system/network')).json())")
    s["api_lock"] = pg.evaluate("async () => (await (await fetch('/api/system/lock-state')).json())")
    pg.screenshot(path=f"{OUT}/T-T1-home-en.png")
    # Feed
    pg.mouse.move(700, 900)
    pg.click("#navGroups [data-tab='feed']")
    pg.wait_for_timeout(2500)
    s["feed"] = pg.evaluate("""() => { const l = document.getElementById('feed-list');
      return {items: l ? l.children.length : -1, first: l ? l.innerText.slice(0, 300) : '', note: (document.getElementById('feed-note')||{}).innerText || ''}; }""")
    junk("T1 feed", s["feed"]["first"])
    s["coach_show_on_feed"] = pg.evaluate("() => document.getElementById('net-coach').classList.contains('show')")
    R["steps"]["T1"] = s; save()

    # ------------------------------------------------------------------ T2
    s = {"themes": {}}
    pg.mouse.move(700, 900)
    s["initial"] = pg.evaluate(COACH_JS)
    pg.click("button[onclick=\"showTab('settings')\"]")
    pg.wait_for_timeout(800)
    pg.click("#set-subtabs [data-tab='graphics']")
    pg.wait_for_timeout(800)
    for th in ["Ink", "Paper", "Solar", "Mint"]:
        pg.locator("#dr-themes button").filter(has_text=re.compile(rf"^\s*{th}\s*$")).first.click()
        pg.mouse.move(700, 900)
        pg.wait_for_timeout(700)
        m = pg.evaluate(COACH_JS)
        s["themes"][th] = m
        coach_clip(pg, f"{OUT}/_T2-{th.lower()}.png")
        junk(f"T2 coach {th}", m["body"] + " " + m["sub"])
    pg.locator("#dr-themes button").filter(has_text=re.compile(r"^\s*Ink\s*$")).first.click()
    pg.wait_for_timeout(500)
    s["final_theme"] = pg.evaluate("() => document.documentElement.getAttribute('data-theme') || '(root ink)'")
    pg.screenshot(path=f"{OUT}/T-T2-settings-ink-en.png")
    R["steps"]["T2"] = s; save()

    # ------------------------------------------------------------------ T3
    s = {}
    for code in ["fr", "ar", "zh"]:
        app_lang(pg, code)
        pg.mouse.move(700, 900)
        m = pg.evaluate(COACH_JS)
        s[code] = m
        junk(f"T3 coach {code}", m["body"] + " " + m["sub"])
        if code == "ar":
            pg.screenshot(path=f"{OUT}/T-T3-coach-ar.png", clip={"x": 0, "y": 0, "width": 1440, "height": 320})
            # side observation: re-anchor after a small window resize
            pg.set_viewport_size({"width": 1446, "height": 950}); pg.wait_for_timeout(600)
            s["ar_after_resize"] = pg.evaluate(COACH_JS)["place"]
            pg.set_viewport_size({"width": 1440, "height": 950}); pg.wait_for_timeout(600)
            s["ar_after_resize_back"] = pg.evaluate(COACH_JS)["place"]
        else:
            coach_clip(pg, f"{OUT}/T-T3-coach-{code}.png")
    app_lang(pg, "en")
    s["en_back"] = pg.evaluate(COACH_JS)
    R["steps"]["T3"] = s; save()

    # ------------------------------------------------------------------ T4
    s = {}
    pg.evaluate("""() => { window.__consentOpens = 0; const d = document.getElementById('net-consent');
      new MutationObserver(() => { if (d.open) window.__consentOpens++; }).observe(d, {attributes: true, attributeFilter: ['open']}); }""")
    s["before"] = net_state(pg)
    pg.click("#net-coach-go")
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=15000)
    pg.wait_for_timeout(1200)
    s["dialog"] = pg.evaluate("""() => { const d = document.getElementById('net-consent');
      const st = id => { const e = document.getElementById(id), cs = getComputedStyle(e); return {text: e.textContent.trim(), cls: e.className, bg: cs.backgroundColor, fg: cs.color, fw: cs.fontWeight, border: cs.borderTopWidth + ' ' + cs.borderTopStyle}; };
      return {title: d.querySelector('h3').textContent.trim(), reason: document.getElementById('net-consent-reason').innerText.trim(),
        lanes: document.getElementById('net-consent-lanes').innerText.trim(), ifaces: document.getElementById('net-consent-ifaces').innerText.trim(),
        text: d.innerText, cancel: st('net-consent-cancel'), ok: st('net-consent-ok')}; }""")
    junk("T4 consent", s["dialog"]["text"])
    s["network_while_dialog"] = pg.evaluate("async () => (await (await fetch('/api/system/network')).json())")
    pg.screenshot(path=f"{OUT}/T-T4-consent-en.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(2000)
    s["after"] = net_state(pg)
    s["coach_show_after"] = pg.evaluate("() => document.getElementById('net-coach').classList.contains('show')")
    s["coach_storage"] = pg.evaluate("() => localStorage.getItem('oo_net_coach_v1')")
    s["toasts_after"] = toasts(pg)
    s["network_after"] = pg.evaluate("async () => (await (await fetch('/api/system/network')).json())")
    s["consent_opens"] = pg.evaluate("() => window.__consentOpens")
    R["steps"]["T4"] = s; save()

    # ------------------------------------------------------------------ T5
    s = {}
    pg.mouse.move(700, 900)
    with ctx.expect_page() as pinfo:
        pg.click("#tm-open")
    tm = pinfo.value; attach(tm, "tasks")
    tm.wait_for_load_state("domcontentloaded")
    tm.set_viewport_size({"width": 1440, "height": 950})
    tm.wait_for_function("() => document.querySelector('#tm-summary .tm-state')", timeout=30000)
    tm.wait_for_timeout(1500)
    s["tab_title"] = tm.title(); s["url"] = tm.url

    TM_JS = """() => { const b = document.getElementById('net-toggle'); const st = document.querySelector('#tm-summary .tm-state');
      const errv = getComputedStyle(document.documentElement).getPropertyValue('--err').trim();
      return {lang: document.documentElement.lang, dir: document.documentElement.dir || 'ltr', title: b.getAttribute('title'),
        plane_fill: document.getElementById('net-plane').getAttribute('fill'), btn_color: getComputedStyle(b).color, err_var: errv,
        inline_color: b.style.color, summary_state: st ? st.textContent.trim() : null,
        header_text: document.querySelector('header') ? document.querySelector('header').innerText : '',
        summary_text: document.getElementById('tm-summary').innerText, conn: (document.getElementById('tm-conn')||{}).textContent || ''}; }"""

    def tm_lang(code):
        tm.mouse.move(700, 900)
        tm.click("#lang-switch"); tm.wait_for_timeout(300)
        tm.click(f"#lang-menu [data-lang='{code}']")
        tm.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=15000)

    tm.hover("#net-toggle"); tm.wait_for_timeout(1200)
    s["en"] = tm.evaluate(TM_JS)
    tm.screenshot(path=f"{OUT}/T-T5-tasks-offline-en.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})
    for code in ["fr", "ar", "zh"]:
        tm_lang(code)
        t0 = time.time()
        # read the title IMMEDIATELY (before the periodic refresh could repaint it), then after a hover
        s[code + "_immediate"] = tm.evaluate("() => document.getElementById('net-toggle').getAttribute('title')")
        tm.hover("#net-toggle"); tm.wait_for_timeout(1200)
        s[code] = tm.evaluate(TM_JS)
        s[code]["read_after_s"] = round(time.time() - t0, 2)
        junk(f"T5 tasks {code}", s[code]["header_text"] + " " + s[code]["summary_text"])
        if code in ("ar", "zh", "fr"):
            tm.screenshot(path=f"{OUT}/T-T5-tasks-offline-{code}.png", clip={"x": 0, "y": 0, "width": 1440, "height": 200})
    tm_lang("en")
    tm.hover("#net-toggle"); tm.wait_for_timeout(1200)
    s["en_back"] = tm.evaluate(TM_JS)
    junk("T5 tasks en", s["en"]["header_text"] + " " + s["en"]["summary_text"])
    R["steps"]["T5"] = s; save()

    # ------------------------------------------------------------------ T6
    s = {}
    pg.bring_to_front()
    s["app_lang_on_return"] = pg.evaluate("() => document.documentElement.lang")
    if s["app_lang_on_return"] != "en":
        app_lang(pg, "en")
    pg.evaluate("() => { window.__consentOpens = 0; }")
    RATE_JS = """() => { const b = document.getElementById('rate-toggle'); return {max: b.classList.contains('rate-max'),
      needle: document.getElementById('rate-needle').getAttribute('transform'), color: getComputedStyle(b).color,
      title: b.getAttribute('title') || b.dataset.ooTip, pressed: b.getAttribute('aria-pressed')}; }"""
    SET_JS = """() => { const sl = document.getElementById('sch-speed'); return {val: document.getElementById('sch-speed-val').textContent.trim(),
      slider: sl.value, stops: Number(sl.max) + 1, visible: sl.offsetParent !== null}; }"""
    cfg = lambda: pg.evaluate("async () => { const c = await (await fetch('/api/scheduler/config')).json(); return {mode: c.collect_rate_mode, target: c.collect_target_kbps}; }")
    s["cfg0"] = cfg()
    s["knob0"] = pg.evaluate(RATE_JS)
    pg.hover("#rate-toggle"); pg.wait_for_timeout(500)
    s["hover0_tip"] = pg.evaluate("() => { const t = document.getElementById('oo-tip'); return {show: t.classList.contains('show'), text: t.textContent}; }")
    pg.screenshot(path=f"{OUT}/_T6-hover0.png", clip={"x": 700, "y": 0, "width": 740, "height": 160})
    # open the Settings path first so the slider is live and visible
    pg.mouse.move(700, 900)
    pg.click("button[onclick=\"showTab('settings')\"]"); pg.wait_for_timeout(600)
    pg.click("#set-subtabs [data-tab='advanced']"); pg.wait_for_timeout(1000)
    det = pg.locator("#set-advanced details[data-adv='collect']")
    if not det.evaluate("d => d.open"):
        det.locator("> summary").click(); pg.wait_for_timeout(1500)
    leg = det.locator("details.adv-collect").first
    if not leg.evaluate("d => d.open"):
        leg.locator("> summary").click(); pg.wait_for_timeout(800)
    s["settings0"] = pg.evaluate(SET_JS)
    s["settings_label"] = pg.evaluate("() => document.querySelector('label[for=sch-speed]').textContent.trim()")
    pg.locator("#sch-speed").scroll_into_view_if_needed(); pg.wait_for_timeout(300)
    # click 1
    pg.click("#rate-toggle"); pg.wait_for_timeout(1500)
    s["click1_toasts"] = toasts(pg)
    s["knob1"] = pg.evaluate(RATE_JS); s["settings1"] = pg.evaluate(SET_JS); s["cfg1"] = cfg()
    pg.mouse.move(700, 600); pg.wait_for_timeout(200)
    pg.screenshot(path=f"{OUT}/T-T6-click1-en.png")
    pg.wait_for_timeout(5500)  # let the toast clear so the next one is unambiguous
    # click 2
    pg.click("#rate-toggle"); pg.wait_for_timeout(1500)
    s["click2_toasts"] = toasts(pg)
    s["knob2"] = pg.evaluate(RATE_JS); s["settings2"] = pg.evaluate(SET_JS); s["cfg2"] = cfg()
    pg.mouse.move(700, 600); pg.wait_for_timeout(200)
    pg.screenshot(path=f"{OUT}/T-T6-click2-en.png")
    s["consent_opens_during_T6"] = pg.evaluate("() => window.__consentOpens")
    s["net_after"] = net_state(pg)
    # Wikipedia and OpenStreetMap settings: look for any speed/bandwidth control of their own
    for cat in ["wikipedia", "offlinemap"]:
        pg.click(f"#set-subtabs [data-tab='{cat}']"); pg.wait_for_timeout(1500)
        s["scan_" + cat] = pg.evaluate("""(cat) => { const v = document.getElementById('set-' + cat); const txt = v.innerText;
          const re = /(speed|bandwidth|throttl|kbps|kbit|KiB\\/s|MiB\\/s|MB\\/s|Mbps|download.?rate|rate limit|vitesse)/ig;
          const hits = []; let m; while ((m = re.exec(txt))) hits.push(txt.slice(Math.max(0, m.index - 70), m.index + 70).replace(/\\s+/g, ' '));
          const ranges = [...v.querySelectorAll('input[type=range]')].map(i => (i.id || '') + ' ' + ((document.querySelector('label[for=\"' + i.id + '\"]') || {}).textContent || '').trim());
          const nums = [...v.querySelectorAll('input[type=number]')].map(i => (i.id || '') + ' ' + ((document.querySelector('label[for=\"' + i.id + '\"]') || {}).textContent || '').trim());
          const titles = [...v.querySelectorAll('[title]')].map(e => e.getAttribute('title')).filter(t => /(speed|bandwidth|throttl|kbps|rate)/i.test(t));
          return {hits, ranges, nums, titles: titles.slice(0, 10), chars: txt.length}; }""", cat)
    s["consent_opens_total"] = pg.evaluate("() => window.__consentOpens")
    # locale re-check of the knob (hover + both messages) in fr / ar / zh
    s["locales"] = {}
    for code in ["fr", "ar", "zh"]:
        app_lang(pg, code)
        d = {}
        pg.hover("#rate-toggle"); pg.wait_for_timeout(500)
        d["hover"] = pg.evaluate("() => document.getElementById('oo-tip').textContent")
        pg.mouse.move(700, 600); pg.wait_for_timeout(5500)
        pg.click("#rate-toggle"); pg.wait_for_timeout(1500); d["msg1"] = toasts(pg)
        d["settings1"] = pg.evaluate(SET_JS)
        pg.mouse.move(700, 600); pg.wait_for_timeout(5500)
        pg.click("#rate-toggle"); pg.wait_for_timeout(1500); d["msg2"] = toasts(pg)
        d["settings2"] = pg.evaluate(SET_JS)
        s["locales"][code] = d
        junk(f"T6 {code}", json.dumps(d, ensure_ascii=False))
    app_lang(pg, "en")
    s["cfg_final"] = cfg()
    s["consent_opens_final"] = pg.evaluate("() => window.__consentOpens")
    R["steps"]["T6"] = s; save()

    # ------------------------------------------------------------------ T7
    s = {}
    pg.mouse.move(700, 900)
    t0 = time.time()
    res = pg.evaluate("""async () => { let ok=0, refused=0, other=[]; let body429 = null; const hdr = {};
      for (let i=0;i<150;i++){ const r = await fetch('/api/articles?limit=1'); if (r.status===429) { refused++; if (!body429) body429 = await r.text(); }
        else if (r.ok) ok++; else other.push(r.status);
        if (i === 149) { for (const k of ['x-ratelimit-limit','x-ratelimit-remaining','ratelimit-limit','retry-after']) hdr[k] = r.headers.get(k); } }
      console.log('ok', ok, 'refused', refused); return {ok, refused, other, body429, hdr}; }""")
    s["result"] = res; s["seconds"] = round(time.time() - t0, 1)
    R["steps"]["T7"] = s; save()

    # ------------------------------------------------------------------ T9 (read-only observation; no pass can run here)
    s = {}
    s["activity"] = pg.evaluate("""async () => { const a = await (await fetch('/api/scheduler/activity')).json();
      return {active: a.active, running: a.running, online: a.online, has_collect_perf: a.collect_perf != null,
        process_budget: a.collect_perf ? a.collect_perf.process_budget : '(no collect_perf)', keys: Object.keys(a).slice(0, 40)}; }""")
    # the only way in, per the step: type toggleVitals() in the console
    pg.evaluate("() => toggleVitals()"); pg.wait_for_timeout(1500)
    s["vitals_open"] = pg.evaluate("() => { const v = document.getElementById('vitals-pop'); return v ? {hidden: v.hidden, display: getComputedStyle(v).display} : null; }")
    try:
        pg.click("#tm-subtabs [data-tab='system']", timeout=5000); pg.wait_for_timeout(1500)
        s["system_text"] = pg.evaluate("() => (document.getElementById('vitals-body') || {}).innerText || ''")[:1500]
    except Exception as e:
        s["system_error"] = str(e)[:300]
    s["collection_speed_block_present"] = "COLLECTION SPEED" in (s.get("system_text") or "").upper()
    pg.screenshot(path=f"{OUT}/_T9-vitals-system-en.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
    # is there any on-screen opener of toggleVitals besides the close button?
    s["openers"] = pg.evaluate("() => [...document.querySelectorAll('[onclick*=toggleVitals]')].map(e => e.id || e.className || e.tagName)")
    R["steps"]["T9"] = s; save()

    # ------------------------------------------------------------------ T10 (read-only)
    s = {}
    s["history"] = pg.evaluate("""async () => { const t = await (await fetch('/api/jobs/history?limit=100')).text();
      return {len: t.length, crawl_delay_deferred: t.includes('crawl_delay_deferred'), runs: (JSON.parse(t).runs || []).length}; }""")
    hs = "/tmp/claude-0/walk/T/data/host_schedule.json"
    s["host_schedule_exists"] = os.path.exists(hs)
    s["data_dir_files"] = sorted(os.listdir("/tmp/claude-0/walk/T/data"))
    R["steps"]["T10"] = s; save()

    # ------------------------------------------------------------------ 375 px pass (en), fresh browser profile
    s = {}
    c2 = br.new_context(viewport={"width": 375, "height": 812})
    m = c2.new_page(); attach(m, "app375")
    m.goto(BASE + "/", wait_until="domcontentloaded"); m.wait_for_timeout(7000)
    s["guide_closed"] = close_guide(m)
    s["lang"] = m.evaluate("() => document.documentElement.lang")
    s["home"] = m.evaluate("""() => ({overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      coach_show: document.getElementById('net-coach').classList.contains('show')})""")
    if s["home"]["coach_show"]:
        s["coach"] = m.evaluate(COACH_JS)
    m.screenshot(path=f"{OUT}/T-375-home-en.png")
    m.goto(BASE + "/tasks", wait_until="domcontentloaded"); m.wait_for_timeout(4000)
    s["tasks"] = m.evaluate("""() => { const b = document.getElementById('net-toggle'); const r = b.getBoundingClientRect();
      const clipped = [...document.querySelectorAll('header *, #tm-summary *')].filter(e => e.children.length === 0 && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible').map(e => (e.id || e.className || e.tagName) + ':' + e.textContent.trim().slice(0, 30));
      return {overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, plane_in_view: r.right <= innerWidth && r.left >= 0,
        title: b.getAttribute('title'), clipped}; }""")
    m.screenshot(path=f"{OUT}/T-375-tasks-en.png")
    c2.close()
    R["steps"]["375"] = s; save()

    tm.close(); ctx.close(); br.close()
save()
print("done")
