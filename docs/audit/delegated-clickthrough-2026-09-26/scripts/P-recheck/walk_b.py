"""Row P recheck, folder B (seeded, encrypted) on port 8840.

Stages: en (D1 D2 D5 D6 D10), fr (D3 D7 D8), narrow (D9), ar (D2 in ar).
"""
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/P-recheck")
from common import (ARGS, EXE, PASS, TOAST_INIT, Rec, centre, close_guide, dismiss_coach,  # noqa: E402
                    save, shot, switch_lang, tipstate, wread)

BASE = "http://127.0.0.1:8840"
STAGES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["en"]
R = {"stages": STAGES}
rec = Rec("B")


def unlock(pg):
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_timeout(1500)
    st = pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json())")
    R.setdefault("lock_states", []).append(st.get("state"))
    if st.get("locked"):
        pg.wait_for_selector("#pw", timeout=20000)
        pg.fill("#pw", PASS)
        pg.click("#btn-unlock")
        pg.wait_for_url("**/#home", timeout=90000)
    pg.wait_for_timeout(3500)
    close_guide(pg)
    dismiss_coach(pg)
    pg.wait_for_timeout(500)
    close_guide(pg)


def hover_read(pg, sel, wait=600):
    pg.mouse.move(700, 600)
    pg.wait_for_timeout(250)
    x, y = centre(pg, sel)
    pg.mouse.move(x, y)
    pg.wait_for_timeout(wait)
    return tipstate(pg)


def settings_sub(pg, tab):
    pg.click("button[onclick=\"showTab('settings')\"]")
    pg.wait_for_timeout(600)
    pg.click(f"#set-subtabs button[data-tab='{tab}']")
    pg.wait_for_timeout(1200)


def d2_stale(pg, lang):
    """Stale bubble after a mouse click on W, then on the gauge."""
    r = {}
    r["w_initial"] = wread(pg)
    r["tip_hover_before_click"] = hover_read(pg, "#wiki-toggle")
    t0 = len(pg.evaluate("() => window.__toasts || []"))
    x, y = centre(pg, "#wiki-toggle")
    pg.mouse.click(x, y)          # real click, pointer stays on W
    pg.wait_for_timeout(2000)
    r["toasts_after_click"] = pg.evaluate("(n) => (window.__toasts || []).slice(n)", t0)
    r["w_after_click_still_hovered"] = wread(pg)
    r["tip_after_click_still_hovered"] = tipstate(pg)
    pg.mouse.move(700, 600)       # leave W
    pg.wait_for_timeout(500)
    r["w_after_leave"] = wread(pg)
    r["tip_rehover"] = hover_read(pg, "#wiki-toggle")
    shot(pg, f"D2-W-paused-rehover-{lang}", clip_sel="header")
    pg.screenshot(path=f"/tmp/claude-0/walk/P-recheck/P-D2-W-paused-rehover-{lang}-full.png")
    # control: a reload gives the fresh bubble
    return r


def d2_shift_stop(pg, lang):
    r = {}
    t0 = len(pg.evaluate("() => window.__toasts || []"))
    x, y = centre(pg, "#wiki-toggle")
    pg.mouse.move(x, y)
    pg.wait_for_timeout(500)
    pg.keyboard.down("Shift")
    pg.mouse.click(x, y)
    pg.keyboard.up("Shift")
    pg.wait_for_timeout(2000)
    r["toasts_after_shift_click"] = pg.evaluate("(n) => (window.__toasts || []).slice(n)", t0)
    r["w_after_shift_click"] = wread(pg)
    pg.mouse.move(700, 600)
    pg.wait_for_timeout(500)
    r["w_after_leave"] = wread(pg)
    r["tip_rehover"] = hover_read(pg, "#wiki-toggle")
    r["config_state"] = pg.evaluate("() => fetch('/api/scheduler/config').then(r => r.json()).then(c => c.wiki_lane_state)")
    return r


def d2_gauge(pg):
    r = {}
    r["tip_before"] = hover_read(pg, "#rate-toggle")
    x, y = centre(pg, "#rate-toggle")
    pg.mouse.click(x, y)
    pg.wait_for_timeout(2000)
    r["title_after_click_still_hovered"] = pg.evaluate("() => document.getElementById('rate-toggle').getAttribute('title')")
    pg.mouse.move(700, 600)
    pg.wait_for_timeout(500)
    r["title_after_leave"] = pg.evaluate("() => document.getElementById('rate-toggle').getAttribute('title')")
    r["tip_rehover"] = hover_read(pg, "#rate-toggle")
    # put it back
    x, y = centre(pg, "#rate-toggle")
    pg.mouse.click(x, y)
    pg.wait_for_timeout(1500)
    pg.mouse.move(700, 600)
    return r


def d6_consent_start(pg):
    """W stopped + airplane: click W -> popup; where is Wikipedia listed?"""
    r = {}
    x, y = centre(pg, "#wiki-toggle")
    pg.mouse.click(x, y)
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=10000)
    pg.wait_for_function("() => !/^…$/.test(document.getElementById('net-consent-lanes').innerText.trim())", timeout=10000)
    pg.wait_for_timeout(1000)
    r["reason"] = pg.evaluate("() => document.getElementById('net-consent-reason').innerText")
    r["lanes_text"] = pg.evaluate("() => document.getElementById('net-consent-lanes').innerText")
    r["is_modal"] = pg.evaluate("() => document.getElementById('net-consent').matches(':modal')")
    shot(pg, "D6-consent-start-W-en", clip_sel="#net-consent")
    # D1: hover the Wikipedia lane inside the modal
    wl = pg.locator("#net-consent-lanes span[title]", has_text="Wikipedia / Wikimedia").first.element_handle()
    r["wiki_lane_span_title_before_hover"] = wl.get_attribute("title")
    b = wl.bounding_box()
    pg.mouse.move(b["x"] + 8, b["y"] + b["height"] / 2)
    pg.wait_for_timeout(800)
    r["tip_in_modal"] = tipstate(pg)
    r["wiki_lane_span_title_while_hovered"] = wl.evaluate("e => e.getAttribute('title')")
    r["dialog_rect"] = pg.evaluate("() => { const d = document.getElementById('net-consent').getBoundingClientRect(); return [Math.round(d.left), Math.round(d.top), Math.round(d.right), Math.round(d.bottom)]; }")
    pg.screenshot(path="/tmp/claude-0/walk/P-recheck/P-D1-consent-hover-en.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(700)
    r["after_cancel"] = {"w": wread(pg), "plane_fill": pg.evaluate("() => document.getElementById('net-plane').getAttribute('fill')"),
                         "config": pg.evaluate("() => fetch('/api/scheduler/config').then(r => r.json()).then(c => c.wiki_lane_state)")}
    return r


def d1_control_outside_modal(pg):
    """Same bubble on a non-modal element: is it topmost there?"""
    return hover_read(pg, "#net-toggle")


def d1_export(pg, lang):
    r = {}
    settings_sub(pg, "data")
    pg.click("button[onclick='openUnifiedExport()']")
    pg.wait_for_function("() => document.querySelectorAll('#ux-checklist label').length > 1", timeout=30000)
    pg.wait_for_timeout(800)
    r["is_modal"] = pg.evaluate("() => document.getElementById('ux-export').matches(':modal')")
    r["rows"] = pg.evaluate("""() => [...document.querySelectorAll('#ux-checklist label')].map(l => { const i = l.querySelector('input');
        return {text: l.innerText.replace(/\\s+/g, ' ').trim(), disabled: i.disabled, checked: i.checked,
                title: l.getAttribute('title'), ooTip: l.dataset.ooTip || null}; })""")
    liv = pg.locator("#ux-checklist label").filter(has=pg.locator("#ux-c-lanes")).first
    if liv.count() == 0:
        liv = pg.locator("#ux-checklist label", has_text="Living").first
    b = liv.bounding_box()
    pg.mouse.move(700, 900)
    pg.wait_for_timeout(200)
    pg.mouse.move(b["x"] + 30, b["y"] + b["height"] / 2)
    pg.wait_for_timeout(800)
    r["tip"] = tipstate(pg)
    r["title_while_hovered"] = liv.evaluate("e => e.getAttribute('title')")
    pg.screenshot(path=f"/tmp/claude-0/walk/P-recheck/P-D1-export-hover-{lang}.png")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(600)
    return r


def d5_shift_scan(pg):
    return pg.evaluate("""() => { const hits = [];
      document.querySelectorAll('*').forEach(e => {
        for (const a of ['title', 'aria-label', 'data-oo-tip']) { const v = e.getAttribute && e.getAttribute(a); if (v && /shift|⇧/i.test(v)) hits.push(a + ': ' + v.slice(0, 120)); }
      });
      const body = document.body.innerText; const m = body.match(/.{0,40}(shift|⇧).{0,40}/ig) || [];
      return {attr_hits: hits, text_hits: m.slice(0, 10)}; }""")


def d10_ores(pg):
    settings_sub(pg, "wikipedia")
    return {"checked": pg.evaluate("() => document.getElementById('wiki-ores').checked"),
            "has_checked_attr": pg.evaluate("() => document.getElementById('wiki-ores').hasAttribute('checked')")}


def d7_home(pg, lang):
    pg.click(".nav-item[data-tab='home']")
    pg.wait_for_timeout(2500)
    shot(pg, f"D7-home-strip-{lang}", clip_sel="#home-stats")
    return pg.evaluate("""() => [...document.querySelectorAll('#home-stats .s')].map(s => s.innerText.replace(/\\s+/g, ' ').trim())""")


def d8_bytes(pg, lang):
    r = {}
    settings_sub(pg, "wikipedia")
    r["wiki_summary"] = pg.evaluate("() => { const e = document.getElementById('wiki-lane-summary'); return e ? e.innerText : null; }")
    if r["wiki_summary"] is None:
        r["wiki_summary_grep"] = pg.evaluate("() => (document.getElementById('set-wikipedia').innerText.match(/.{0,80}(KB|MB|Ko|Mo).{0,40}/g) || []).slice(0, 5)")
    settings_sub(pg, "data")
    r["storage_rows"] = pg.evaluate("() => [...document.querySelectorAll('#storage-lanes tr')].map(tr => tr.innerText.replace(/\\s+/g,' ').trim())")
    return r


def d3_reader(pg, lang):
    r = {}
    pg.keyboard.press("Escape")
    pg.click(".omni")
    pg.wait_for_selector("#pal-input", state="visible", timeout=8000)
    pg.type("#pal-input", "Coastal Infrastructure Act", delay=30)
    pg.wait_for_timeout(2500)
    items = pg.locator("#pal-list .pal-item")
    target = None
    for i in range(items.count()):
        t = items.nth(i).inner_text()
        if t.startswith("Coastal Infrastructure Act") and "2025-11-01" in t:
            target = i
            break
    r["picked"] = target
    if target is None:
        r["palette"] = pg.evaluate("() => document.getElementById('pal-list').innerText")
        return r
    with pg.context.expect_page() as newp:
        items.nth(target).click()
    reader = newp.value
    rr = Rec(f"reader-{lang}")
    rr.attach(reader)
    reader.wait_for_load_state("domcontentloaded")
    reader.wait_for_timeout(2500)
    r["reader_lang"] = reader.evaluate("() => document.documentElement.lang")
    r["licence_text"] = reader.evaluate("() => { const l = document.querySelector('.licence'); return l ? l.innerText : null; }")
    hist = reader.locator(".licence a.ext").nth(1)
    r["hist_text"] = hist.inner_text()
    n0 = len(pg.context.pages)
    hist.click()
    reader.wait_for_timeout(1500)
    r["dialogs"] = rr.dialogs
    r["pages_opened"] = len(pg.context.pages) - n0
    r["i18n_available"] = reader.evaluate("() => !!(window.OOI18N && OOI18N.t)")
    r["i18n_translates_key"] = reader.evaluate("() => window.OOI18N ? OOI18N.t('This leaves your local copy and makes a live request from your machine — the site may see your visit. Continue?') : null")
    shot(reader, f"D3-reader-licence-{lang}", clip_sel=".licence")
    r["errors"] = rr.dump()
    reader.close()
    return r


def d9_narrow(br):
    r = {}
    ctx = br.new_context(viewport={"width": 375, "height": 800})
    pg = ctx.new_page()
    rn = Rec("narrow")
    rn.attach(pg)
    pg.goto(BASE + "/#settings", wait_until="domcontentloaded")
    pg.wait_for_timeout(4000)
    close_guide(pg)
    dismiss_coach(pg)
    r["lang"] = pg.evaluate("() => document.documentElement.lang")
    pg.goto(BASE + "/#settings", wait_until="domcontentloaded")
    pg.wait_for_timeout(3000)
    close_guide(pg)
    try:
        pg.wait_for_selector("#net-coach-dismiss", state="visible", timeout=8000)
        pg.click("#net-coach-dismiss")
        pg.wait_for_timeout(500)
    except Exception:
        pass
    # open Settings via sidebar and the Wikipedia subtab
    try:
        pg.click("button[onclick=\"showTab('settings')\"]", timeout=5000)
    except Exception:
        pass
    pg.wait_for_timeout(800)
    pg.click("#set-subtabs button[data-tab='wikipedia']")
    pg.wait_for_timeout(2000)
    r["overflow_px"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    r["offenders"] = pg.evaluate("""() => { const vw = document.documentElement.clientWidth; const out = [];
      const clipped = (e) => { for (let a = e.parentElement; a && a !== document.documentElement; a = a.parentElement) {
          const ox = getComputedStyle(a).overflowX; if (ox !== 'visible') return true; } return false; };
      document.querySelectorAll('#set-wikipedia *').forEach(e => { const b = e.getBoundingClientRect();
        if (b.width > 0 && b.right > vw + 0.5 && !clipped(e)) out.push({tag: e.tagName, id: e.id, text: (e.innerText || '').slice(0, 60).replace(/\\s+/g, ' '),
          style: e.getAttribute('style'), right: Math.round(b.right), width: Math.round(b.width)}); });
      return out.slice(0, 12); }""")
    btn = pg.locator("button[onclick='dumpFtsBuild()']")
    btn.scroll_into_view_if_needed()
    pg.wait_for_timeout(400)
    pg.screenshot(path="/tmp/claude-0/walk/P-recheck/P-D9-narrow-settings-wikipedia-en.png")
    r["errors"] = rn.dump()
    ctx.close()
    return r


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=ARGS)
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    ctx.add_init_script(TOAST_INIT)
    pg = ctx.new_page()
    rec.attach(pg)
    try:
        unlock(pg)
        R["network"] = pg.evaluate("() => fetch('/api/system/network').then(r => r.json())")
        if "en" in STAGES:
            R["D10_ores"] = d10_ores(pg)
            pg.click(".nav-item[data-tab='home']")
            pg.wait_for_timeout(1500)
            R["D5_shift_scan_home"] = d5_shift_scan(pg)
            R["D1_control_outside_modal"] = d1_control_outside_modal(pg)
            R["D2_W_en"] = d2_stale(pg, "en")
            R["D2_W_shift_en"] = d2_shift_stop(pg, "en")
            R["D5_shift_scan_after"] = d5_shift_scan(pg)
            R["D6_consent"] = d6_consent_start(pg)
            R["D2_gauge"] = d2_gauge(pg)
            R["D1_export_en"] = d1_export(pg, "en")
            # control: reload -> fresh W bubble
            pg.reload(wait_until="domcontentloaded")
            pg.wait_for_timeout(4000)
            close_guide(pg)
            dismiss_coach(pg)
            R["D2_after_reload"] = {"w": wread(pg), "tip": hover_read(pg, "#wiki-toggle")}
        if "fr" in STAGES:
            switch_lang(pg, "fr")
            R["D7_home_fr"] = d7_home(pg, "fr")
            R["D8_fr"] = d8_bytes(pg, "fr")
            R["D1_export_fr"] = d1_export(pg, "fr")
            R["D3_reader_fr"] = d3_reader(pg, "fr")
        if "zh" in STAGES:
            switch_lang(pg, "zh")
            R["D7_home_zh"] = d7_home(pg, "zh")
            R["D3_reader_zh"] = d3_reader(pg, "zh")
        if "ar" in STAGES:
            switch_lang(pg, "ar")
            R["D7_home_ar"] = d7_home(pg, "ar")
            R["D3_reader_ar"] = d3_reader(pg, "ar")
            R["D2_W_ar_state_before"] = wread(pg)
        if "en2" in STAGES:
            switch_lang(pg, "en")
        if "narrow" in STAGES:
            R["D9_narrow"] = d9_narrow(br)
    except Exception:
        R["harness_exception"] = traceback.format_exc()
        try:
            pg.screenshot(path="/tmp/claude-0/walk/P-recheck/P-harness-exception.png")
        except Exception:
            pass
    R["errors"] = rec.dump()
    save("b_" + "_".join(STAGES) + ".json", R)
    br.close()
