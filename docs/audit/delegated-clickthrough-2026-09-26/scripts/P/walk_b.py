"""Row P, folder B (seeded, encrypted, OO_AUTOSEED=0) on port 8839: P6-P11 + the 375 px pass."""
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import (EXE, PASS, TOAST_INIT, TOPBAR, Rec, attr, boxes, close_guide, dismiss_coach,  # noqa: E402
                    jsnow, junk_in, plane_filled, save, settings_sub, shot, switch_lang, text, tip, toasts_since,
                    wstate)

BASE = "http://127.0.0.1:8839"
STAGES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["en", "locales", "narrow"]
OUTF = "b_" + "_".join(STAGES) + ".json"
R = {}
rec = Rec("B")


def unlock(pg):
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_timeout(1500)
    st = pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json())")
    R.setdefault("unlocks", []).append(st)
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


def open_living(pg):
    pg.click(".nav-item[data-tab='living']")
    pg.wait_for_function("() => (document.getElementById('living-wiki-facts') || {}).innerText", timeout=15000)
    pg.wait_for_function("() => document.querySelectorAll('#living-stream .living-row').length > 0", timeout=15000)
    pg.wait_for_timeout(900)


def living_facts(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('#living-wiki-facts .living-fact')].map(f => ({
        label: f.querySelector('.muted').innerText, value: f.querySelector('.living-fact-v').innerText,
        hover: f.getAttribute('title') || f.dataset.ooTip || null}))""")


def stream_rows(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('#living-stream .living-row')].map(r => ({
        text: r.innerText, pills: [...r.querySelectorAll('.pill')].map(p => ({t: p.innerText, title: p.getAttribute('title') || p.dataset.ooTip || null})),
        delta: (r.querySelector('.living-delta') || {}).innerText || null,
        has_btn: !!r.querySelector('button')}))""")


def p6(pg):
    r = R["P6"] = {}
    pg.click(".nav-item[data-tab='timemap']")
    pg.wait_for_selector("[data-oomap-wiki]", timeout=30000)
    pg.wait_for_timeout(2500)
    r["lens_active"] = pg.evaluate("() => [...document.querySelectorAll('#oomap-lenses button')].map(b => b.innerText + (b.classList.contains('active') ? ' *' : ''))")
    r["btn_before"] = pg.evaluate("() => { const b = document.querySelector('[data-oomap-wiki]'); return {text: b.innerText, pressed: b.getAttribute('aria-pressed'), style: b.getAttribute('style')}; }")
    r["tip"] = tip(pg, "[data-oomap-wiki]")
    shot(pg, "P6-map-before-en")
    t0 = jsnow(pg)
    pg.click("[data-oomap-wiki]")
    pg.wait_for_timeout(3000)
    r["btn_on"] = pg.evaluate("() => { const b = document.querySelector('[data-oomap-wiki]'); return {text: b.innerText, pressed: b.getAttribute('aria-pressed'), style: b.getAttribute('style'), border: getComputedStyle(b).borderColor}; }")
    r["legend_on"] = pg.evaluate("() => [...document.querySelectorAll('#tab-timemap .muted')].map(e => e.innerText).filter(t => /Wikipedia/.test(t))")
    r["wiki_markers"] = pg.evaluate("() => document.querySelectorAll('[data-oomap-wikilayer] circle, [data-oomap-wikilayer] *').length")
    r["wikilayer_nodes"] = pg.evaluate("() => document.querySelectorAll('[data-oomap-wikilayer]').length")
    r["places_api"] = pg.evaluate("() => fetch('/api/wiki/lane/places').then(r => r.json()).then(d => ({measured: d.measured, n: (d.places || d.points || []).length, keys: Object.keys(d)}))")
    shot(pg, "P6-map-wiki-on-en")
    pg.click("[data-oomap-wiki]")
    pg.wait_for_timeout(2500)
    r["btn_off"] = pg.evaluate("() => { const b = document.querySelector('[data-oomap-wiki]'); return {pressed: b.getAttribute('aria-pressed'), style: b.getAttribute('style')}; }")
    r["legend_off"] = pg.evaluate("() => [...document.querySelectorAll('#tab-timemap .muted')].map(e => e.innerText).filter(t => /Wikipedia page/.test(t))")
    r["toasts"] = toasts_since(pg, t0)
    r["junk"] = junk_in(text(pg, "#tab-timemap"))


def p7(pg, lang="en"):
    r = {}
    pg.click(".nav-item[data-tab='home']")
    pg.wait_for_selector("#home-wiki-figure", timeout=20000)
    pg.wait_for_timeout(800)
    r["strip"] = text(pg, "#home-stats")
    r["figure"] = text(pg, "#home-wiki-figure")
    r["tip"] = tip(pg, "#home-wiki-figure")
    r["lane_status_api"] = pg.evaluate("() => fetch('/api/wiki/lane/status').then(r => r.json())")
    r["counts_api"] = pg.evaluate("() => fetch('/api/stats').then(r => r.ok ? r.json() : r.status).catch(e => String(e))")
    shot(pg, f"P7-home-strip-{lang}", clip_sel="#home-stats")
    return r


def p8(pg, lang="en", full=True):
    r = {}
    open_living(pg)
    r["active_subtab"] = pg.evaluate("() => [...document.querySelectorAll('#living-subtabs button')].map(b => b.dataset.tab + ':' + b.getAttribute('aria-selected'))")
    r["caveat"] = text(pg, "#living-caveat")
    r["status"] = text(pg, "#living-status")
    r["facts"] = living_facts(pg)
    if full:
        # hover each Live-stream figure for real
        n = pg.locator("#living-wiki-facts .living-facts").first.locator(".living-fact").count()
        r["fact_tips"] = []
        for i in range(n):
            loc = pg.locator("#living-wiki-facts .living-facts").first.locator(".living-fact").nth(i)
            r["fact_tips"].append(tip(pg, None, locator=loc, wait=350)["text"])
    r["cap"] = text(pg, "#living-stream-cap")
    r["rows"] = stream_rows(pg)
    shot(pg, f"P8-living-{lang}", full=True)
    btn = pg.locator("#living-stream button.tiny").first
    r["btn_label_before"] = btn.inner_text()
    btn.click()
    pg.wait_for_selector("#living-stream .living-diff", timeout=8000)
    pg.wait_for_timeout(500)
    r["btn_label_after"] = pg.locator("#living-stream button.tiny").first.inner_text()
    r["diff_lines"] = pg.evaluate("() => [...document.querySelectorAll('#living-stream .living-diff .living-diff-l')].map(l => ({t: l.textContent, color: l.getAttribute('style'), dir: getComputedStyle(l).direction, bold: !!l.querySelector('b')}))")
    r["diff_note"] = pg.evaluate("() => [...document.querySelectorAll('#living-stream .living-diff ~ .muted')].map(e => e.innerText)")
    r["delta_render"] = pg.evaluate("() => [...document.querySelectorAll('#living-stream .living-delta')].map(d => { const r = d.getBoundingClientRect(); return {t: d.innerText, dir: getComputedStyle(d).direction, unicodeBidi: getComputedStyle(d).unicodeBidi}; })")
    pg.locator("#living-stream .living-diff").first.scroll_into_view_if_needed()
    shot(pg, f"P8-living-diff-{lang}")
    if full:
        # the log pill hover
        logpill = pg.locator("#living-stream .pill[title], #living-stream .pill[data-oo-tip]")
        r["log_pill_tip"] = tip(pg, None, locator=logpill.first)["text"] if logpill.count() else None
    # hide the diff again
    pg.locator("#living-stream button.tiny").first.click()
    pg.wait_for_timeout(400)
    r["btn_label_hidden"] = pg.locator("#living-stream button.tiny").first.inner_text()
    r["pages"] = pg.evaluate("() => [...document.querySelectorAll('#living-pages button.living-page')].map(b => b.innerText)")
    pages_before = len(pg.context.pages)
    tracked = pg.locator("#living-pages button.living-page", has_text="Walk Tracked Page")
    tracked.first.click()
    pg.wait_for_function("() => /\\S/.test(document.getElementById('wiki-tc-body').innerText) && !/Pick a page|Loading/.test(document.getElementById('wiki-tc-body').innerText)", timeout=10000)
    pg.wait_for_timeout(700)
    r["tc_title"] = text(pg, "#wiki-tc-title")
    r["tc_body"] = text(pg, "#wiki-tc-body")
    r["tc_method"] = text(pg, "#wiki-tc-method")
    r["tc_rows"] = pg.evaluate("() => document.querySelectorAll('#wiki-tc-body tr, #wiki-tc-body .living-row, #wiki-tc-body li').length")
    r["new_windows_opened"] = len(pg.context.pages) - pages_before
    r["dialogs_open"] = pg.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)")
    pg.locator("#wiki-tc").scroll_into_view_if_needed()
    shot(pg, f"P8-tracked-{lang}")
    r["junk"] = junk_in(text(pg, "#tab-living"))
    return r


def p9(pg, lang="en"):
    r = {}
    pg.keyboard.press("Escape")
    pg.click(".omni")
    pg.wait_for_selector("#pal-input", state="visible", timeout=8000)
    pg.type("#pal-input", "Coastal Infrastructure Act", delay=30)
    pg.wait_for_function("() => [...document.querySelectorAll('#pal-list .pal-group')].some(g => /articles/i.test(g.innerText))", timeout=15000)
    pg.wait_for_timeout(800)
    r["palette"] = pg.evaluate("() => [...document.querySelectorAll('#pal-list > *')].map(e => (e.className.includes('pal-group') ? '## ' : '') + e.innerText.replace(/\\s+/g, ' ').trim())")
    shot(pg, "P9-palette-en")
    items = pg.locator("#pal-list .pal-item")
    target = None
    for i in range(items.count()):
        t = items.nth(i).inner_text()
        if t.startswith("Coastal Infrastructure Act") and "consolidated" not in t and "2025-11-01" in t:
            target = i
            break
    r["picked_index"] = target
    if target is None:
        r["blocked"] = "no Articles row 'Coastal Infrastructure Act' dated 2025-11-01"
        return r, None
    with pg.context.expect_page() as newp:
        items.nth(target).click()
    reader = newp.value
    rec2 = Rec("B-reader")
    rec2.attach(reader, dialog_policy="dismiss")
    reader.wait_for_load_state("domcontentloaded")
    reader.wait_for_timeout(2000)
    r["reader_url"] = reader.url
    r.update(reader_read(reader))
    loc = reader.locator(".licence")
    if loc.count():
        loc.scroll_into_view_if_needed()
        shot(reader, f"P9-reader-licence-{lang}", clip_sel=".licence")
    # click the history link -> confirm -> Cancel
    before_pages = len(pg.context.pages)
    hist = reader.locator(".licence a.ext").nth(1)
    r["history_link_text"] = hist.inner_text()
    r["history_href"] = hist.get_attribute("href")
    hist.click()
    reader.wait_for_timeout(1200)
    r["confirm_dialogs"] = list(rec2.dialogs)
    r["pages_opened_after_cancel"] = len(pg.context.pages) - before_pages
    r["reader_url_after_cancel"] = reader.url
    r["reader_errors"] = rec2.dump()
    return r, reader


def reader_read(reader):
    return reader.evaluate("""() => { const l = document.querySelector('.licence');
      return {html_lang: document.documentElement.lang, dir: document.documentElement.dir || getComputedStyle(document.body).direction,
              licence_text: l ? l.innerText : null,
              licence_links: l ? [...l.querySelectorAll('a')].map(a => ({text: a.innerText, cls: a.className, href: a.getAttribute('href')})) : [],
              licence_visible: l ? (l.getBoundingClientRect().height > 0 && getComputedStyle(l).display !== 'none') : false,
              title: document.title}; }""")


def p10(pg):
    r = R["P10"] = {}
    settings_sub(pg, "data")
    pg.click("button[onclick='openUnifiedExport()']")
    pg.wait_for_function("() => /What do you want to back up\\?/.test(document.getElementById('ux-inv-status').innerText)", timeout=30000)
    pg.wait_for_timeout(600)
    r["status"] = text(pg, "#ux-inv-status")
    r["rows"] = pg.evaluate("""() => [...document.querySelectorAll('#ux-checklist label')].map(l => { const i = l.querySelector('input');
        return {text: l.innerText.replace(/\\s+/g, ' ').trim(), checked: i.checked, disabled: i.disabled, title: l.getAttribute('title') || l.dataset.ooTip || null}; })""")
    liv = pg.locator("#ux-checklist label", has_text="Living sources")
    r["living_tip"] = tip(pg, None, locator=liv.first) if liv.count() else None
    shot(pg, "P10-export-en", clip_sel="#ux-export")
    r["inventory_api_living"] = pg.evaluate("() => fetch('/api/backup/inventory').then(r => r.json()).then(i => (i.members || []).filter(m => /living|lane|wiki/i.test(m.key + m.label)))")
    pg.click("#ux-export button.secondary:has-text('Close')")
    pg.wait_for_timeout(500)
    r["closed"] = not pg.evaluate("() => document.getElementById('ux-export').open")


def w_read_fresh(pg):
    """The W bubble as a person sees it after a reload (fresh paint), plus the live attribute."""
    return {"w": wstate(pg), "tip": tip(pg, "#wiki-toggle")}


def wizard_locale(pg, lang):
    settings_sub(pg, "wikipedia")
    pg.wait_for_function("() => !/Loading|…/.test(document.getElementById('wiki-lane-summary').innerText)", timeout=15000)
    pg.wait_for_timeout(500)
    out = {"summary": text(pg, "#wiki-lane-summary"),
           "panel": pg.evaluate("() => document.getElementById('wiki-lane-summary').closest('section').innerText")}
    pg.locator("#wiki-lane-summary").scroll_into_view_if_needed()
    shot(pg, f"P11-settings-wikipedia-{lang}")
    pg.click("#wiki-wizard-open")
    pg.wait_for_function("() => document.getElementById('wiki-wizard').open && document.querySelectorAll('#wiki-wizard-editions input').length", timeout=15000)
    pg.wait_for_timeout(700)
    out["wizard"] = pg.evaluate("""() => { const d = document.getElementById('wiki-wizard');
        return {title: d.querySelector('h3').innerText, hosts: document.getElementById('wiki-wizard-hosts').innerText,
                share: document.getElementById('wiki-wizard-share').innerText, count: document.getElementById('wiki-wizard-count').innerText,
                buttons: [...d.querySelectorAll('button')].map(b => b.innerText), body: d.innerText,
                dir: getComputedStyle(d).direction}; }""")
    shot(pg, f"P11-wizard-{lang}")
    pg.click("#wiki-wizard-cancel")
    pg.wait_for_timeout(400)
    return out


def consent_via_w(pg, lang):
    pg.mouse.move(2, 400)
    pg.click("#wiki-toggle")
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=10000)
    pg.wait_for_function("() => !/^…$/.test(document.getElementById('net-consent-lanes').innerText)", timeout=10000)
    pg.wait_for_timeout(900)
    c = pg.evaluate("""() => { const d = document.getElementById('net-consent');
        const wl = [...document.querySelectorAll('#net-consent-lanes span[title]')].map(s => ({t: s.innerText, title: s.getAttribute('title')}));
        return {body: d.innerText, reason: document.getElementById('net-consent-reason').innerText, wiki_lines: wl.filter(x => /wikimedia/.test(x.title || '')),
                buttons: [...d.querySelectorAll('button')].map(b => b.innerText), dir: getComputedStyle(d).direction}; }""")
    shot(pg, f"P11-consent-{lang}")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(700)
    c["plane_filled_after"] = plane_filled(pg)
    c["w_after"] = wstate(pg)["cls"]
    return c


def locales(pg):
    L = R["P11"] = {"per_lang": {}}
    langs = ["ar", "zh", "fr"]
    # Phase 1: RUNNING bubble in each language (the boot state of folder B)
    for lg in langs:
        switch_lang(pg, lg, rec)
        L["per_lang"].setdefault(lg, {})["W_running"] = w_read_fresh(pg)
    # Phase 2 (ar): click to PAUSE; read the fresh attribute while still hovered, then the
    # bubble after moving away and back (the stale-bubble check), then a reload
    lg = "ar"
    switch_lang(pg, lg, rec)
    t0 = jsnow(pg)
    pg.hover("#wiki-toggle")
    pg.wait_for_timeout(400)
    pg.click("#wiki-toggle")
    pg.wait_for_timeout(1500)
    L["per_lang"][lg]["pause"] = {"toasts": toasts_since(pg, t0), "popup": pg.evaluate("() => document.getElementById('net-consent').open"),
                                  "title_attr_fresh": attr(pg, "#wiki-toggle", "title"), "w": wstate(pg)}
    L["per_lang"][lg]["pause"]["rehover_tip"] = tip(pg, "#wiki-toggle")
    shot(pg, "P11-W-paused-stale-bubble-ar")
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_timeout(3500)
    close_guide(pg)
    dismiss_coach(pg)
    for lg2 in langs:
        switch_lang(pg, lg2, rec)
        L["per_lang"][lg2]["W_paused"] = w_read_fresh(pg)
        shot(pg, f"P11-W-paused-{lg2}", clip_sel="header")
    # Phase 3 (fr): Shift+click to STOP
    lg = "fr"
    t0 = jsnow(pg)
    pg.mouse.move(2, 400)
    pg.click("#wiki-toggle", modifiers=["Shift"])
    pg.wait_for_timeout(1500)
    L["per_lang"][lg]["stop"] = {"toasts": toasts_since(pg, t0), "title_attr_fresh": attr(pg, "#wiki-toggle", "title")}
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_timeout(3500)
    close_guide(pg)
    dismiss_coach(pg)
    for lg2 in langs:
        switch_lang(pg, lg2, rec)
        L["per_lang"][lg2]["W_stopped"] = w_read_fresh(pg)
        L["per_lang"][lg2]["consent"] = consent_via_w(pg, lg2)
        L["per_lang"][lg2]["wizard"] = wizard_locale(pg, lg2)
        L["per_lang"][lg2]["home"] = p7(pg, lg2)
        L["per_lang"][lg2]["living"] = p8(pg, lg2, full=False)
        L["per_lang"][lg2]["living_fact_tip_sample"] = tip(pg, None, locator=pg.locator("#living-wiki-facts .living-fact").first)["text"]
        url = (R.get("P9") or {}).get("reader_url") or R.get("reader_url_hint")
        if url:
            rd = pg.context.new_page()
            rr = Rec("B-reader-" + lg2)
            rr.attach(rd)
            rd.goto(url, wait_until="domcontentloaded")
            rd.wait_for_timeout(2500)
            L["per_lang"][lg2]["reader"] = reader_read(rd)
            if rd.locator(".licence").count():
                rd.locator(".licence").scroll_into_view_if_needed()
                shot(rd, f"P11-reader-licence-{lg2}", clip_sel=".licence")
            L["per_lang"][lg2]["reader_errors"] = rr.dump()
            rd.close()
        save(OUTF, R)


def narrow(br):
    ctx = br.new_context(viewport={"width": 375, "height": 800})
    ctx.add_init_script(TOAST_INIT)
    pg = ctx.new_page()
    rec3 = Rec("B-375")
    rec3.attach(pg)
    unlock(pg)
    N = R["narrow"] = {}

    def sx():
        return pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")

    N["home_scroll_x"] = sx()
    N["home_fig"] = text(pg, "#home-wiki-figure")
    shot(pg, "N375-home-en", full=True)
    N["topbar_boxes"] = boxes(pg, TOPBAR)
    pg.evaluate("() => showTab('living')")  # the sidebar is an icon rail at 375 px
    pg.wait_for_function("() => document.querySelectorAll('#living-stream .living-row').length > 0", timeout=15000)
    pg.wait_for_timeout(800)
    N["living_scroll_x"] = sx()
    N["living_overflowing"] = pg.evaluate("""() => [...document.querySelectorAll('#tab-living *')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && (r.right > window.innerWidth + 1); }).slice(0, 8).map(e => e.tagName + '.' + e.className + ' right=' + Math.round(e.getBoundingClientRect().right))""")
    shot(pg, "N375-living-en", full=True)
    pg.evaluate("() => showTab('settings')")
    pg.wait_for_timeout(600)
    pg.click("#set-subtabs button[data-tab='wikipedia']")
    pg.wait_for_timeout(900)
    N["settings_wiki_scroll_x"] = sx()
    pg.click("#wiki-wizard-open")
    pg.wait_for_function("() => document.getElementById('wiki-wizard').open", timeout=10000)
    pg.wait_for_timeout(800)
    N["wizard_scroll_x"] = sx()
    N["wizard_box"] = pg.evaluate("() => { const r = document.getElementById('wiki-wizard').getBoundingClientRect(); return [r.left, r.right, r.width, window.innerWidth]; }")
    N["wizard_buttons_visible"] = pg.evaluate("() => [...document.querySelectorAll('#wiki-wizard button')].map(b => { const r = b.getBoundingClientRect(); return b.innerText + ':' + (r.bottom <= window.innerHeight && r.right <= window.innerWidth && r.left >= 0); })")
    shot(pg, "N375-wizard-en")
    pg.click("#wiki-wizard-cancel")
    pg.wait_for_timeout(300)
    # consent popup via W (stopped -> popup)
    pg.click("#wiki-toggle")
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=10000)
    pg.wait_for_timeout(900)
    N["consent_scroll_x"] = sx()
    N["consent_buttons_visible"] = pg.evaluate("() => [...document.querySelectorAll('#net-consent button')].map(b => { const r = b.getBoundingClientRect(); return b.innerText + ':' + (r.bottom <= window.innerHeight && r.right <= window.innerWidth && r.left >= 0); })")
    shot(pg, "N375-consent-en")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(400)
    N["plane_filled"] = plane_filled(pg)
    N["errors"] = rec3.dump()
    ctx.close()


def main():
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking", "--disable-component-update"])
        try:
            if "en" in STAGES or "locales" in STAGES or "p9p10" in STAGES:
                ctx = br.new_context(viewport={"width": 1440, "height": 950})
                ctx.add_init_script(TOAST_INIT)
                pg = ctx.new_page()
                rec.attach(pg)
                unlock(pg)
                R["boot"] = {"plane_filled": plane_filled(pg), "network": pg.evaluate("() => fetch('/api/system/network').then(r => r.json())"),
                             "at_rest": pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json())"),
                             "w": wstate(pg), "w_tip": tip(pg, "#wiki-toggle"), "topbar": boxes(pg, TOPBAR),
                             "sched_wiki": pg.evaluate("() => fetch('/api/scheduler/status').then(r => r.json()).then(s => s.wiki_lane && {state: s.wiki_lane.state, active: s.wiki_lane.active, reason: s.wiki_lane.reason})")}
                shot(pg, "P3-boot-W-running-folderB-en", clip_sel="header")
                if "p9p10" in STAGES:
                    res, reader = p9(pg)
                    R["P9"] = res
                    if reader is not None:
                        reader.close()
                    save(OUTF, R)
                    pg.keyboard.press("Escape")
                    p10(pg)
                    save(OUTF, R)
                if "en" in STAGES:
                    for fn, key in ((p6, None), (lambda q: R.__setitem__("P7", p7(q)), None),
                                    (lambda q: R.__setitem__("P8", p8(q)), None)):
                        try:
                            fn(pg)
                        except Exception:
                            R.setdefault("stage_exceptions", []).append(traceback.format_exc())
                        save(OUTF, R)
                    try:
                        res, reader = p9(pg)
                        R["P9"] = res
                        if reader is not None:
                            reader.close()
                    except Exception:
                        R.setdefault("stage_exceptions", []).append(traceback.format_exc())
                    save(OUTF, R)
                    try:
                        p10(pg)
                    except Exception:
                        R.setdefault("stage_exceptions", []).append(traceback.format_exc())
                    save(OUTF, R)
                if "locales" in STAGES:
                    try:
                        locales(pg)
                    except Exception:
                        R.setdefault("stage_exceptions", []).append(traceback.format_exc())
                    save(OUTF, R)
                ctx.close()
            if "narrow" in STAGES:
                try:
                    narrow(br)
                except Exception:
                    R.setdefault("stage_exceptions", []).append(traceback.format_exc())
        finally:
            R["errors"] = rec.dump()
            save(OUTF, R)
            br.close()


if __name__ == "__main__":
    main()
