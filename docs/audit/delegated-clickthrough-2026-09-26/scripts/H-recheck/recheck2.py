"""Row H recheck, part 2: Discover-by-topic heading (UI toggle), Local AI transparent text,
Arabic bidi of '*.wikipedia.org', French lone colon, Home strip English in fr/ar."""
import json

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8812"
OUT = "/tmp/claude-0/walk/H-recheck"
PASS = "walk-pass-2026"
VW, VH = 1440, 950
rep = {"notes": [], "page_errors": [], "console_errors": [], "http_errors": []}


def api(pg, path, method="GET", body=None):
    return pg.evaluate("""([p, m, b]) => fetch(p, {method: m, headers: {'Content-Type': 'application/json'},
        body: b === null ? undefined : JSON.stringify(b)}).then(r => r.json())""", [path, method, body])


def enter(pg):
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(2000)
    if pg.locator("#view-unlock").count() and pg.locator("#view-unlock").is_visible():
        pg.fill("#pw", PASS); pg.click("#btn-unlock")
        pg.wait_for_function("() => location.hash === '#home'", timeout=120000)
        rep["notes"].append("unlocked via #pw")
    pg.wait_for_selector("#net-toggle", timeout=60000)
    pg.wait_for_timeout(2500)
    if pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
        pg.click("#gw-close"); pg.wait_for_timeout(400)
    loc = pg.locator("#net-coach-dismiss")
    if loc.count() and loc.is_visible():
        loc.click(); pg.wait_for_timeout(300)


def open_popup(pg):
    pg.mouse.move(700, 600)
    pg.click("#net-toggle")
    pg.wait_for_function("() => { const d = document.getElementById('net-consent'); return d && d.open && "
                         "document.querySelectorAll('#net-consent-lanes .oo-tip-target').length > 10 && "
                         "document.getElementById('net-consent-ifaces').textContent.trim() !== '…'; }", timeout=20000)
    pg.wait_for_timeout(700)


def groups(pg):
    return pg.evaluate("""() => { const out = []; let cur = null;
      [...document.getElementById('net-consent-lanes').children].forEach(ch => {
        if (ch.classList.contains('muted')) { cur = {h: ch.textContent.trim(), lanes: []}; out.push(cur); }
        else if (!ch.classList.contains('hint') && cur) { const s = ch.querySelector('span'); if (s) cur.lanes.push(s.textContent.trim()); } });
      return out; }""")


def switch_lang(pg, lang):
    pg.keyboard.press("Escape"); pg.mouse.move(700, 600); pg.wait_for_timeout(300)
    pg.click("#lang-switch")
    pg.wait_for_selector(f"#lang-menu [data-lang='{lang}']", state="visible", timeout=6000)
    pg.click(f"#lang-menu [data-lang='{lang}']")
    pg.wait_for_function("(l) => document.documentElement.lang === l", arg=lang, timeout=8000)
    pg.wait_for_timeout(1000)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": VW, "height": VH})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: rep["page_errors"].append(str(e)[:300]))
    pg.on("console", lambda m: rep["console_errors"].append(m.text[:300]) if m.type == "error" else None)
    pg.on("response", lambda r: rep["http_errors"].append(f"{r.status} {r.url}") if r.status >= 400 else None)
    enter(pg)
    rep["lock"] = api(pg, "/api/system/lock-state")["state"]

    # ---------- Local AI lane text in transparent mode ----------
    open_popup(pg)
    rep["transport_kind"] = (api(pg, "/api/safety/settings") or {}).get("transport")
    rep["ai_lane_hover_dom"] = pg.evaluate("""() => { const s = [...document.querySelectorAll('#net-consent-lanes span.oo-tip-target')]
        .find(x => x.textContent.trim() === 'Local AI install & weights'); return s ? (s.getAttribute('title') || s.dataset.ooTip) : null; }""")
    rep["groups_default"] = groups(pg)
    pg.click("#net-consent-cancel"); pg.wait_for_timeout(500)

    # ---------- Discover by topic: tick it through the real Settings UI ----------
    pg.click("button[onclick=\"showTab('settings')\"]")
    pg.wait_for_selector("#set-subtabs button[data-tab='advanced']", state="visible", timeout=15000)
    pg.click("#set-subtabs button[data-tab='advanced']")
    pg.wait_for_selector("#set-advanced", state="visible", timeout=10000)
    if not pg.evaluate("() => document.querySelector(\"details[data-adv='safety']\").open"):
        pg.click("details[data-adv='safety'] > summary")
    pg.wait_for_selector("#discovery-external", state="visible", timeout=10000)
    pg.wait_for_timeout(600)
    cb = pg.locator("#discovery-external")
    cb.scroll_into_view_if_needed()
    rep["dx_before"] = {"checked": cb.is_checked(), "api": api(pg, "/api/safety/settings").get("discovery_external_enabled")}
    cb.click()
    pg.wait_for_function("() => document.getElementById('discovery-external-result').textContent.trim().length > 0", timeout=8000)
    pg.wait_for_timeout(400)
    rep["dx_on"] = {"checked": cb.is_checked(), "api": api(pg, "/api/safety/settings").get("discovery_external_enabled"),
                    "result": pg.inner_text("#discovery-external-result")}
    open_popup(pg)
    rep["groups_dx_on"] = groups(pg)
    pg.screenshot(path=f"{OUT}/H-dx-on-popup-en.png")
    pg.click("#net-consent-cancel"); pg.wait_for_timeout(500)
    loc = pg.locator("#net-coach-dismiss")
    if loc.count() and loc.is_visible():
        loc.click(); pg.wait_for_timeout(300)
    cb.scroll_into_view_if_needed()
    cb.click()
    pg.wait_for_function("() => document.getElementById('discovery-external-result').textContent.includes('Disabled')", timeout=8000)
    rep["dx_off"] = {"checked": cb.is_checked(), "api": api(pg, "/api/safety/settings").get("discovery_external_enabled")}
    rep["network_after_dx"] = api(pg, "/api/system/network")
    pg.click("nav button.nav-item[data-tab='home'], button.nav-item[data-tab='home']")
    pg.wait_for_timeout(1500)

    # ---------- French: lone colon + Home strip ----------
    rep["home_strip_en"] = pg.inner_text("#home-stats")
    switch_lang(pg, "fr")
    rep["home_strip_fr_after_switch"] = pg.inner_text("#home-stats")
    pg.wait_for_timeout(6000)
    rep["home_strip_fr_after_6s"] = pg.inner_text("#home-stats")
    rep["home_stats_keys"] = api(pg, "/api/stats") if False else None
    open_popup(pg)
    rep["fr_colon"] = pg.evaluate("""() => {
      const body = document.getElementById('net-consent');
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
      const out = []; let n;
      while ((n = walker.nextNode())) {
        const s = n.textContent; const i = s.lastIndexOf(':');
        if (i < 2 || s.slice(i + 1).trim()) continue;          // only text ending in ':'
        const r1 = document.createRange(); r1.setStart(n, i); r1.setEnd(n, i + 1);
        const r0 = document.createRange(); r0.setStart(n, i - 2); r0.setEnd(n, i - 1);
        const a = r1.getBoundingClientRect(), b = r0.getBoundingClientRect();
        if (!a.width && !a.height) continue;
        out.push({text: s.trim().slice(-60), charBeforeColon: s.charCodeAt(i - 1).toString(16),
                  colonTop: Math.round(a.top), wordTop: Math.round(b.top), colonAlone: Math.round(a.top) > Math.round(b.top) + 4});
      }
      return out; }""")
    pg.screenshot(path=f"{OUT}/H-fr-popup.png")
    pg.click("#net-consent-cancel"); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/H-fr-home.png")
    # reload with fr persisted: does the strip come up translated from a fresh render?
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_selector("#home-stats .s", timeout=60000)
    pg.wait_for_timeout(3000)
    rep["lang_after_reload"] = pg.evaluate("() => document.documentElement.lang")
    rep["home_strip_fr_after_reload"] = pg.inner_text("#home-stats")
    loc = pg.locator("#net-coach-dismiss")
    if loc.count() and loc.is_visible():
        loc.click(); pg.wait_for_timeout(300)

    # ---------- Arabic: bidi of '*.wikipedia.org' in the Wikipedia bubble ----------
    switch_lang(pg, "ar")
    rep["home_strip_ar_after_switch"] = pg.inner_text("#home-stats")
    open_popup(pg)
    wiki = pg.locator("#net-consent-lanes span.oo-tip-target").nth(2)
    rep["ar_wiki_label"] = wiki.inner_text()
    wiki.hover(); pg.wait_for_timeout(900)
    BIDI = """() => { const t = document.getElementById('oo-tip'); const n = t.firstChild;
      const rc = (i) => { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); const b = r.getBoundingClientRect(); return {x: Math.round(b.x), y: Math.round(b.y)}; };
      return {dir: getComputedStyle(t).direction, text: t.textContent.slice(0, 40), parent: t.parentElement.tagName,
              star: rc(0), dot: rc(1), w: rc(2), a_last: rc(t.textContent.indexOf('.org') + 3)}; }"""
    rep["ar_bidi_in_body"] = pg.evaluate(BIDI)
    pg.screenshot(path=f"{OUT}/H-ar-wiki-hover.png")
    # diagnosis only: re-parent into the dialog so the bubble is painted, to SEE the bidi result
    pg.mouse.move(5, 5); pg.wait_for_timeout(300)
    pg.evaluate("() => document.getElementById('net-consent').appendChild(document.getElementById('oo-tip'))")
    wiki.hover(); pg.wait_for_timeout(900)
    rep["ar_bidi_fixprobe"] = pg.evaluate(BIDI)
    tr = pg.evaluate("() => { const r = document.getElementById('oo-tip').getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }")
    pg.screenshot(path=f"{OUT}/H-ar-wiki-hover-FIXPROBE.png", clip={"x": max(0, tr["x"] - 10), "y": max(0, tr["y"] - 10), "width": tr["width"] + 20, "height": tr["height"] + 20})
    pg.mouse.move(5, 5); pg.wait_for_timeout(300)
    pg.evaluate("() => document.body.appendChild(document.getElementById('oo-tip'))")
    pg.click("#net-consent-cancel"); pg.wait_for_timeout(500)
    switch_lang(pg, "en")
    rep["network_end"] = api(pg, "/api/system/network")
    br.close()

with open(f"{OUT}/recheck2.json", "w", encoding="utf-8") as fh:
    json.dump(rep, fh, ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1)[:9000])
