# -*- coding: utf-8 -*-
"""Recheck D2..D6, D8, D9, D3 on the unlocked ENCRYPTED seeded instance (8852)."""
import json, re, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/U-recheck")
from common import *
BASE = "http://127.0.0.1:8852"
STEPS = sys.argv[1:] or ["strip", "price", "moon", "calendar", "newsletter", "narrow", "help"]
rec = Rec("seeded_" + "_".join(STEPS))
WID = """(root) => { let best = null; document.querySelectorAll((root||'body') + ' *').forEach(e => { if (!e.getClientRects().length) return;
    const b = e.getBoundingClientRect(); if (b.right > innerWidth + 1 && (!best || b.right > best.r)) best = {r: Math.round(b.right), w: Math.round(b.width), tag: e.tagName, id: e.id, cls: String(e.className).slice(0,60), parent: e.parentElement ? (e.parentElement.tagName + '#' + e.parentElement.id + '.' + String(e.parentElement.className).slice(0,40)) : '', text: (e.textContent||'').trim().slice(0,80)}; });
    return best; }"""

def dismiss_coach(pg):
    try:
        if pg.is_visible("#net-coach-dismiss"): pg.click("#net-coach-dismiss", timeout=3000); pg.wait_for_timeout(300)
    except Exception: pass

def nav(pg, tab):
    dismiss_coach(pg)
    pg.click(f"#navGroups .nav-item[data-tab='{tab}']"); pg.wait_for_timeout(1000)

def goto_settings(pg, sub):
    dismiss_coach(pg)
    pg.click(".sb-foot button[onclick=\"showTab('settings')\"]"); pg.wait_for_timeout(600)
    pg.click(f"#set-subtabs [data-tab='{sub}']"); pg.wait_for_timeout(700)

def tip(pg, sel):
    pg.hover(sel); pg.wait_for_timeout(900)
    r = pg.evaluate("""(s) => { const t = document.getElementById('oo-tip'); const e = document.querySelector(s);
        return {tip_shown: !!(t && t.classList.contains('show')), tip_text: t ? t.textContent.slice(0,200) : null,
                el_classes: e ? e.className : null, title_attr: e ? (e.getAttribute('title') || '') .slice(0,200) : null,
                data_ootip: e ? (e.dataset.ooTip || null) : null}; }""", sel)
    pg.mouse.move(3, 940); pg.wait_for_timeout(250)
    return r

def open_price(pg, sym):
    nav(pg, "markets")
    pg.wait_for_selector("#mkt-dashboard .fam-member", timeout=30000); pg.wait_for_timeout(600)
    mem = pg.locator("#mkt-dashboard .fam-member", has=pg.locator(".fam-mlabel", has_text=re.compile(rf"^{sym}$")))
    mem.first.locator("button.fam-mbtn[data-act='0']").click(); pg.wait_for_timeout(1500)
    pt = pg.locator("#an-price-tab")
    if pt.is_visible() and "active" not in (pt.get_attribute("class") or ""): pt.click()
    pg.wait_for_function("() => { const p = document.getElementById('an-price'); return p && p.querySelector('svg'); }", timeout=30000)
    pg.wait_for_timeout(600)

def price_label(pg):
    return pg.evaluate("() => { const s = document.querySelector('#an-price svg'); if (!s) return null; return [...s.querySelectorAll('text')].slice(0,2).map(t => t.textContent); }")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.attach(pg)
    unlock(pg, BASE); close_unrelated(pg); dismiss_coach(pg)
    rec.note("lock_state", pg.evaluate("async () => (await (await fetch('/api/system/lock-state')).json()).state"))

    if "strip" in STEPS:
        pg.wait_for_function("() => !/Loading/.test(document.getElementById('home-stats').textContent)", timeout=30000)
        rec.note("strip.en", {"stats": pg.inner_text("#home-stats"), "status": pg.inner_text("#home-status")})
        rec.note("strip.api_keys", pg.evaluate("async () => Object.keys((await (await fetch('/api/database/stats')).json()).counts)"))
        switch_lang(pg, "fr")
        rec.note("strip.fr_1s", {"stats": pg.inner_text("#home-stats"), "status": pg.inner_text("#home-status"), "briefing_head": (pg.inner_text("#tab-home") or "")[:0]})
        shot(pg, "U-D4-strip-fr-after-switch")
        pg.wait_for_timeout(4000)
        rec.note("strip.fr_5s", {"stats": pg.inner_text("#home-stats"), "status": pg.inner_text("#home-status")})
        # wait for the LIVE poll (refreshHomeLive) to repaint
        try:
            pg.wait_for_function("() => /Mots-clés|Mots clés|Sources/.test(document.getElementById('home-stats').innerText) && !/Keywords/.test(document.getElementById('home-stats').innerText)", timeout=45000)
            rec.note("strip.fr_after_poll", {"stats": pg.inner_text("#home-stats"), "status": pg.inner_text("#home-status")})
        except Exception as e:
            rec.note("strip.fr_after_poll_timeout", {"stats": pg.inner_text("#home-stats"), "status": pg.inner_text("#home-status")})
        shot(pg, "U-D4-strip-fr-after-poll")
        switch_lang(pg, "en")

    if "price" in STEPS:
        open_price(pg, "Dy")
        rec.note("price.en", price_label(pg))
        switch_lang(pg, "fr")
        rec.note("price.fr_after_switch", {"svg": price_label(pg), "tab": pg.inner_text("#an-price-tab")})
        # re-select the Price subtab (walker said this does not repaint)
        try:
            pg.click("#an-subtabs [data-tab]:not(#an-price-tab) >> nth=0"); pg.wait_for_timeout(500)
            pg.click("#an-price-tab"); pg.wait_for_timeout(1200)
            rec.note("price.fr_after_reselect", price_label(pg))
        except Exception as e:
            rec.note("price.reselect_err", str(e)[:200])
        shot(pg, "U-D8-price-fr-after-switch")
        # open fresh in fr
        pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
        open_price(pg, "Dy")
        rec.note("price.fr_fresh_open", price_label(pg))
        switch_lang(pg, "en")

    if "moon" in STEPS:
        nav(pg, "agenda"); pg.wait_for_timeout(1200)
        pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(1500)
        rec.note("moon.en", pg.eval_on_selector_all(".ag-moon", "els => els.slice(0,2).map(e => e.getAttribute('title') || e.dataset.ooTip)"))
        switch_lang(pg, "fr")
        rec.note("moon.fr_after_switch", pg.eval_on_selector_all(".ag-moon", "els => els.slice(0,2).map(e => e.getAttribute('title') || e.dataset.ooTip)"))
        rec.note("moon.fr_month_heading", pg.evaluate("() => (document.getElementById('agenda-month')||{}).innerText ? document.getElementById('agenda-month').innerText.slice(0,80) : null"))
        nav(pg, "home"); nav(pg, "agenda"); pg.wait_for_timeout(1200)
        pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(1500)
        rec.note("moon.fr_after_renav", pg.eval_on_selector_all(".ag-moon", "els => els.slice(0,2).map(e => e.getAttribute('title') || e.dataset.ooTip)"))
        if pg.query_selector(".ag-moon"):
            rec.note("moon.fr_hover", tip(pg, ".ag-moon"))
        shot(pg, "U-D8-moon-fr")
        switch_lang(pg, "en")

    if "calendar" in STEPS:
        goto_settings(pg, "advanced")
        sel = "#set-advanced details.adv-sec[data-adv='calendars']"
        if not pg.evaluate(f"() => document.querySelector(\"{sel}\").open"): pg.click(f"{sel} > summary"); pg.wait_for_timeout(900)
        pg.wait_for_function("() => document.querySelectorAll('#feeddir-kind option').length > 1", timeout=30000)
        rec.note("cal.hint", pg.eval_on_selector("#agenda-feeds p.hint", "e => e.innerText.replace(/\\s+/g,' ')"))
        rec.note("cal.kinds", pg.eval_on_selector_all("#feeddir-kind option", "els => els.map(e => e.value)"))
        rec.note("cal.status", pg.evaluate("() => (document.getElementById('feeddir-status')||{}).innerText"))
        rec.note("cal.api", pg.evaluate("""async () => { const d = await (await fetch('/api/events/feeds')).json(); const fams = d.families || d; 
            const k = {}; (fams||[]).forEach(f => k[f.kind] = (k[f.kind]||0) + 1); return {families: (fams||[]).length, kinds: k, keys: Object.keys(d).slice(0,8)}; }"""))
        pg.locator("#agenda-feeds p.hint").first.scroll_into_view_if_needed(); shot(pg, "U-D2-calendar-hint-en")

    if "newsletter" in STEPS:
        goto_settings(pg, "data")
        pg.locator("#nl-files").scroll_into_view_if_needed()
        files = sorted(str(x) for x in (OUT / "eml").glob("*.eml"))
        pg.set_input_files("#nl-files", files); pg.click("#nl-import-btn")
        pg.wait_for_function("() => /imported/.test(document.getElementById('nl-result').textContent)", timeout=60000)
        pg.wait_for_function("() => document.getElementById('nl-attach').style.display !== 'none'", timeout=20000)
        pg.wait_for_timeout(800)
        rec.note("nl.result", pg.inner_text("#nl-result"))
        rec.note("nl.rows_innerText", pg.eval_on_selector_all("#nl-attach-body .vr", "els => els.map(e => e.innerText)"))
        rec.note("nl.row_layout", pg.eval_on_selector_all("#nl-attach-body .vr", "els => els.map(e => ({display: getComputedStyle(e).display, spans: [...e.children].map(c => [c.tagName, Math.round(c.getBoundingClientRect().left), Math.round(c.getBoundingClientRect().right)])}))"))
        pg.locator("#nl-attach").scroll_into_view_if_needed(); shot(pg, "U-D6-rows-en")
        # the caveat: wait a long time to rule out a late mark
        pg.wait_for_timeout(3000)
        rec.note("nl.caveat_hover", tip(pg, "#nl-attach-caveat"))
        rec.note("nl.caveat_hover_retry", tip(pg, "#nl-attach-caveat"))
        rec.note("nl.count_hover", tip(pg, "#nl-attach-body .vr b"))
        # a reload of the Data subtab (loadNewsletterAttach on an element which now HAS a title at load?)
        pg.reload(wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
        if "/unlock" in pg.url: unlock(pg, BASE)
        close_unrelated(pg); goto_settings(pg, "data"); pg.wait_for_timeout(1500)
        pg.locator("#nl-attach").scroll_into_view_if_needed()
        rec.note("nl.caveat_hover_after_reload", tip(pg, "#nl-attach-caveat"))
        # undo to leave the state as found
        n = len(rec.dialogs)
        pg.click("#nl-attach-undo")
        pg.wait_for_function("() => /moved back/.test(document.getElementById('nl-result').textContent)", timeout=30000)
        rec.note("nl.undo", {"confirm": rec.dialogs[n:], "result": pg.inner_text("#nl-result")})

    if "narrow" in STEPS:
        nav(pg, "markets"); pg.wait_for_selector("#mkt-dashboard canvas", timeout=30000); pg.wait_for_timeout(1000)
        rec.note("narrow.1440", {"hscroll": hscroll(pg), "canvas_w": pg.evaluate("() => [...document.querySelectorAll('#mkt-dashboard canvas')].map(c => c.style.width)")})
        pg.set_viewport_size({"width": 375, "height": 812}); pg.wait_for_timeout(2500)
        rec.note("narrow.375_no_reload", {"hscroll": hscroll(pg), "widest": pg.evaluate(WID, "#tab-markets")})
        shot(pg, "U-D9-commodities-narrowed-375")
        # does going to another tab and back refit?
        pg.goto(BASE + "/#home"); pg.wait_for_timeout(500)
        pg.set_viewport_size({"width": 1440, "height": 950}); pg.wait_for_timeout(500)

    if "help" in STEPS:
        c2 = br.new_context(viewport={"width": 375, "height": 812}); p2 = c2.new_page(); rec.attach(p2)
        p2.goto(BASE + "/", wait_until="domcontentloaded"); p2.wait_for_timeout(3500); close_unrelated(p2)
        try:
            if p2.is_visible("#net-coach-dismiss"): p2.click("#net-coach-dismiss")
        except Exception: pass
        rec.note("help.home_hscroll", hscroll(p2))
        p2.click("button.icon-btn[onclick=\"showTab('help')\"]"); p2.wait_for_timeout(3000)
        rec.note("help.hscroll", hscroll(p2))
        rec.note("help.widest", p2.evaluate(WID, "#tab-help"))
        rec.note("help.layout", p2.evaluate("""() => { const l = document.querySelector('#tab-help .doc-layout'); if (!l) return null;
            return {cols: getComputedStyle(l).gridTemplateColumns, w: Math.round(l.getBoundingClientRect().width),
                    pre: [...l.querySelectorAll('pre')].slice(0,3).map(p => ({w: Math.round(p.getBoundingClientRect().width), sw: p.scrollWidth}))}; }"""))
        shot(p2, "U-D3-help-375-en")
        c2.close()
    rec.note("net_online_end", pg.evaluate("async () => (await (await fetch('/api/system/network')).json()).online"))
    rec.save(); br.close()
