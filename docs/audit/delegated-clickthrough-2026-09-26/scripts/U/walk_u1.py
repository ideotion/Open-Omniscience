# -*- coding: utf-8 -*-
"""U1: fresh first launch on 8851 -> Home 'No Leads yet' -> fr / ar / zh via the top-bar switcher."""
import sys
from playwright.sync_api import sync_playwright
from common import *

BASE = "http://127.0.0.1:8851"
PASS = "amber river quiet lantern walk"
rec = Rec("u1")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec.attach(pg)
    pg.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(1500)
    rec.note("u1.landing_url", pg.url)
    pg.wait_for_selector("#view-language:not(.hidden)", timeout=20000)
    rec.note("u1.language_view", text_of(pg, "#view-language"))
    shot(pg, "U-U1-choose-language-en")
    pg.click("#lang-list button[lang='en']")
    pg.wait_for_selector("#view-legal:not(.hidden)", timeout=20000)
    pg.wait_for_function("() => (document.getElementById('lg-accept').textContent || '').trim().length > 0", timeout=20000)
    rec.note("u1.legal_heading", text_of(pg, "#lg-heading"))
    rec.note("u1.legal_accept_label", text_of(pg, "#lg-accept-label"))
    rec.note("u1.legal_accept_btn", text_of(pg, "#lg-accept"))
    rec.note("u1.legal_accept_disabled_before_tick", pg.is_disabled("#lg-accept"))
    pg.check("#lg-check")
    pg.wait_for_timeout(200)
    rec.note("u1.legal_accept_disabled_after_tick", pg.is_disabled("#lg-accept"))
    pg.click("#lg-accept")
    # data location (or straight to create when not offerable)
    pg.wait_for_selector("#view-datadir:not(.hidden), #view-create:not(.hidden)", timeout=20000)
    if pg.is_visible("#view-datadir"):
        rec.note("u1.datadir_shown", True)
        rec.note("u1.datadir_default_path", text_of(pg, "#dl-default-path"))
        rec.note("u1.datadir_default_checked", pg.is_checked("#dl-default"))
        shot(pg, "U-U1-datadir-en")
        pg.click("#dl-continue")
    else:
        rec.note("u1.datadir_shown", False)
    pg.wait_for_selector("#view-create:not(.hidden)", timeout=20000)
    rec.note("u1.create_view", text_of(pg, "#view-create")[:300])
    pg.fill("#pw1", PASS); pg.fill("#pw2", PASS)
    pg.click("#btn-create")
    try:
        pg.wait_for_selector("#view-preparing:not(.hidden)", timeout=5000)
        rec.note("u1.preparing_seen", text_of(pg, "#view-preparing")[:300])
    except Exception:
        rec.note("u1.preparing_seen", "not observed (too fast or skipped)")
    pg.wait_for_url("**/?wikiwizard=1**", timeout=120000)
    rec.note("u1.entered_url", pg.url)
    pg.wait_for_timeout(4000)
    state = pg.evaluate("""() => ({wiki: !!(document.getElementById('wiki-wizard')||{}).open,
        guide: !!(document.getElementById('guide-wizard')||{}).open,
        coach: document.getElementById('net-coach').classList.contains('show')})""")
    rec.note("u1.dialogs_after_entry", state)
    shot(pg, "U-U1-entry-dialogs-en")
    # Both first-run dialogs can be open at once, stacked in a racy order. Dismiss
    # whichever is ON TOP through its own button (trial click = hit-target check).
    order = []
    for _ in range(6):
        wiz_open = pg.evaluate("() => !!document.getElementById('wiki-wizard').open")
        gw_open = pg.evaluate("() => !!document.getElementById('guide-wizard').open")
        if not wiz_open and not gw_open:
            break
        done = False
        if wiz_open:
            try:
                pg.click("#wiki-wizard-cancel", timeout=1500, trial=True)
                rec.note("u1.wiki_wizard_opened", text_of(pg, "#wiki-wizard h3"))
                shot(pg, "U-U1-wiki-wizard-en")
                pg.click("#wiki-wizard-cancel", timeout=5000)
                order.append("wiki-wizard: Not now"); done = True
            except Exception:
                pass
        if not done and gw_open:
            try:
                pg.click("#gw-close", timeout=1500, trial=True)
                pg.click("#gw-close", timeout=5000)
                order.append("guide-wizard: X"); done = True
            except Exception:
                pass
        pg.wait_for_timeout(700)
    rec.note("u1.dismiss_order", order)
    pg.wait_for_timeout(1500)
    try:
        if pg.is_visible("#net-coach-dismiss"):
            rec.note("u1.coachmark", text_of(pg, "#net-coach"))
            pg.click("#net-coach-dismiss")
            pg.wait_for_timeout(400)
        else:
            rec.note("u1.coachmark", "not shown")
    except Exception as e:
        rec.note("u1.coachmark_err", str(e))
    rec.note("u1.dialogs_after_dismiss", pg.evaluate("""() => ({wiki: !!(document.getElementById('wiki-wizard')||{}).open,
        guide: !!(document.getElementById('guide-wizard')||{}).open})"""))
    # Home settles: wait for the empty-state card heading
    feed = "#briefing-feed"
    ok = False
    for i in range(60):
        h = pg.evaluate("() => { const h = document.querySelector('#briefing-feed .card h4'); return h ? h.textContent : null; }")
        if h:
            ok = True; break
        pg.wait_for_timeout(1000)
    rec.note("u1.home_settled", ok)
    rec.note("u1.plane_fill_en", plane_filled(pg))
    rec.note("u1.home_card_en", text_of(pg, "#briefing-feed .card"))
    rec.note("u1.home_bold_en", pg.eval_on_selector_all("#briefing-feed .card p.sum b", "els => els.map(e => e.textContent)"))
    rec.note("u1.home_grey_en", text_of(pg, "#briefing-feed .card p.muted"))
    rec.note("u1.sidebar_en", sidebar_side(pg))
    rec.junk_scan(pg, "#tab-home", "U1 home en")
    shot(pg, "U-U1-home-en")
    for code in ["fr", "ar", "zh"]:
        r = switch_lang(pg, code, rec)
        pg.wait_for_timeout(1500)
        rec.note(f"u1.lang_{code}", r)
        rec.note(f"u1.home_card_{code}", text_of(pg, "#briefing-feed .card"))
        rec.note(f"u1.home_h4_{code}", text_of(pg, "#briefing-feed .card h4"))
        rec.note(f"u1.home_bold_{code}", pg.eval_on_selector_all("#briefing-feed .card p.sum b", "els => els.map(e => e.textContent)"))
        rec.note(f"u1.home_grey_{code}", text_of(pg, "#briefing-feed .card p.muted"))
        rec.note(f"u1.plane_fill_{code}", plane_filled(pg))
        rec.note(f"u1.sidebar_{code}", sidebar_side(pg))
        rec.note(f"u1.textalign_{code}", pg.evaluate("() => getComputedStyle(document.querySelector('#briefing-feed .card p.sum')).textAlign + ' / dir=' + getComputedStyle(document.querySelector('#briefing-feed .card p.sum')).direction"))
        rec.note(f"u1.hscroll_{code}", hscroll(pg))
        rec.junk_scan(pg, "#tab-home", f"U1 home {code}")
        shot(pg, f"U-U1-home-{code}")
    rec.note("u1.lock_state_after", pg.evaluate("async () => (await (await fetch('/api/system/lock-state')).json())"))
    rec.note("u1.online_state", pg.evaluate("async () => { try { return await (await fetch('/api/system/network')).json(); } catch (e) { return String(e); } }"))
    rec.save()
    br.close()
print("page_errors", rec.page_errors)
print("console_errors", rec.console_errors)
print("http_errors", rec.http_errors)
print("junk", rec.junk)
