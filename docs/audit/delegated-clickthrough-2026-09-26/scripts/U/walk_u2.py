# -*- coding: utf-8 -*-
"""U2: encrypted seeded corpus on 8850 boots LOCKED -> wrong passphrase -> right one -> At-rest encryption."""
from playwright.sync_api import sync_playwright
from common import *

BASE = "http://127.0.0.1:8850"
rec = Rec("u2")
OBS_JS = """() => { window.__prep = []; const v = document.getElementById('view-preparing');
  const el = document.getElementById('prep-elapsed');
  const mo = new MutationObserver(() => { window.__prep.push({prep_visible: !v.classList.contains('hidden'),
      elapsed: el.textContent, unlock_visible: !document.getElementById('view-unlock').classList.contains('hidden'),
      msg: document.getElementById('msg').textContent, t: Date.now()}); });
  mo.observe(v, {attributes: true}); mo.observe(el, {childList: true, characterData: true, subtree: true});
  mo.observe(document.getElementById('msg'), {childList: true, characterData: true, subtree: true}); }"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec.attach(pg)
    rec.note("u2.lock_state_before", pg.request.get(BASE + "/api/system/lock-state").json())
    pg.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector("#view-unlock:not(.hidden)", timeout=20000)
    rec.note("u2.url", pg.url)
    rec.note("u2.visible_views", pg.evaluate("() => [...document.querySelectorAll('[id^=view-]')].filter(v => !v.classList.contains('hidden')).map(v => v.id)"))
    rec.note("u2.unlock_view", text_of(pg, "#view-unlock"))
    shot(pg, "U-U2-unlock-en")
    # wrong passphrase
    pg.evaluate(OBS_JS)
    pg.fill("#pw", "definitely the wrong phrase")
    pg.click("#btn-unlock")
    pg.wait_for_function("() => (document.getElementById('msg').textContent || '').trim().length > 0", timeout=60000)
    pg.wait_for_timeout(500)
    rec.note("u2.wrong_prep_trace", pg.evaluate("() => window.__prep"))
    rec.note("u2.wrong_msg", text_of(pg, "#msg"))
    rec.note("u2.wrong_msg_color", pg.evaluate("() => getComputedStyle(document.getElementById('msg')).color"))
    rec.note("u2.after_wrong_views", pg.evaluate("() => [...document.querySelectorAll('[id^=view-]')].filter(v => !v.classList.contains('hidden')).map(v => v.id)"))
    rec.note("u2.btn_enabled_after_wrong", pg.is_enabled("#btn-unlock"))
    rec.note("u2.pw_editable_after_wrong", pg.is_editable("#pw"))
    shot(pg, "U-U2-wrong-passphrase-en")
    # right passphrase
    pg.evaluate(OBS_JS)
    pg.fill("#pw", "walk-pass-2026")
    pg.click("#btn-unlock")
    seen = []
    shot_done = False
    for i in range(600):
        try:
            if "/unlock" not in pg.url:
                break
            st = pg.evaluate("() => ({prep: !document.getElementById('view-preparing').classList.contains('hidden'), phase: document.getElementById('prep-phase').textContent, elapsed: document.getElementById('prep-elapsed').textContent})")
            if st["prep"] and (not seen or seen[-1] != st):
                seen.append(st)
                if not shot_done:
                    shot(pg, "U-U2-preparing-en"); shot_done = True
        except Exception:
            break
        pg.wait_for_timeout(100)
    rec.note("u2.right_prep_trace", seen)
    pg.wait_for_url("**/#home", timeout=180000)
    rec.note("u2.entered_url", pg.url)
    pg.wait_for_timeout(4000)
    rec.note("u2.dialogs", pg.evaluate("""() => ({wiki: !!(document.getElementById('wiki-wizard')||{}).open,
        guide: !!(document.getElementById('guide-wizard')||{}).open})"""))
    if pg.evaluate("() => !!document.getElementById('guide-wizard').open"):
        pg.click("#gw-close", timeout=5000)
        pg.wait_for_timeout(500)
    if pg.is_visible("#net-coach-dismiss"):
        pg.click("#net-coach-dismiss"); pg.wait_for_timeout(300)
    for i in range(30):
        if pg.evaluate("() => !!document.querySelector('#briefing-feed .card, #briefing-feed .brief-bucket')"):
            break
        pg.wait_for_timeout(1000)
    rec.note("u2.home_stats", text_of(pg, "#home-stats"))
    rec.note("u2.home_feed_head", text_of(pg, "#briefing-feed")[:600])
    rec.note("u2.plane_fill", plane_filled(pg))
    shot(pg, "U-U2-home-en")
    # Settings -> Advanced -> Safety -> At-rest encryption
    pg.click(".sb-foot button:has-text('Settings')")
    pg.wait_for_timeout(800)
    pg.click("#set-subtabs [data-tab='advanced']")
    pg.wait_for_timeout(800)
    pg.click("#set-advanced details.adv-sec[data-adv='safety'] > summary")
    pg.wait_for_function("() => { const e = document.getElementById('atrest-state'); return e && !/Checking/.test(e.textContent); }", timeout=20000)
    pg.wait_for_timeout(600)
    rec.note("u2.atrest", text_of(pg, "#atrest-state"))
    pg.locator("#atrest-state").scroll_into_view_if_needed()
    shot(pg, "U-U2-atrest-en")
    rec.note("u2.lock_state_after", pg.evaluate("async () => (await (await fetch('/api/system/lock-state')).json())"))
    rec.junk_scan(pg, "#set-advanced details.adv-sec[data-adv='safety']", "U2 safety fold en")
    rec.save(); br.close()
print("page_errors", rec.page_errors); print("console_errors", rec.console_errors)
print("http_errors", rec.http_errors); print("junk", rec.junk)
