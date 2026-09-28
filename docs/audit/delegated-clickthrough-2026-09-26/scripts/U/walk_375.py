# -*- coding: utf-8 -*-
"""375 px en pass over row U's surfaces (horizontal scroll + clipped/offscreen text) on 8850,
plus fresh-render probes for the U6 SVG label and U9 moon hover in fr."""
import sys, re
from playwright.sync_api import sync_playwright
from common import *
import walk_main as W

BASE = "http://127.0.0.1:8850"
rec = Rec("w375"); W.rec = rec

CLIP_JS = """(root) => { const out = []; const r = document.querySelector(root); if (!r) return ['(no root)'];
  r.querySelectorAll('*').forEach(e => { if (!e.getClientRects().length) return; const cs = getComputedStyle(e);
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) return;
    if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip' || cs.textOverflow === 'ellipsis') && e.scrollWidth > e.clientWidth + 1)
      out.push('CLIP ' + e.tagName + (e.id ? '#' + e.id : '') + '.' + e.className + ' :: ' + e.textContent.trim().slice(0, 60) + ` [${e.scrollWidth}>${e.clientWidth}]`);
    const b = e.getBoundingClientRect(); if (b.width && (b.right > innerWidth + 1 || b.left < -1)) out.push('OFFSCREEN ' + e.tagName + (e.id ? '#' + e.id : '') + '.' + e.className + ' :: ' + e.textContent.trim().slice(0, 50) + ` [${Math.round(b.left)}..${Math.round(b.right)}]`);
  }); return out.slice(0, 12); }"""


def widest(pg):
    return pg.evaluate("""() => { let best = null; document.querySelectorAll('body *').forEach(e => { if (!e.getClientRects().length) return;
        const b = e.getBoundingClientRect(); if (b.right > innerWidth + 1 && (!best || b.right > best.r)) best = {r: Math.round(b.right), tag: e.tagName, id: e.id, cls: String(e.className).slice(0,60), text: (e.textContent||'').trim().slice(0,50)}; });
        return best; }""")


with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    close_unrelated_dialogs(pg)
    if "probes" in sys.argv:
        # U6: FRESH render of the Price subtab in fr (switch first, then open the window)
        switch_lang(pg, "fr")
        W.nav(pg, "markets")
        pg.wait_for_selector("#mkt-dashboard .fam-member", timeout=30000)
        mem = pg.locator("#mkt-dashboard .fam-member", has=pg.locator(".fam-mlabel", has_text=re.compile(r"^Nd$")))
        mem.first.locator("button.fam-mbtn[data-act='0']").click(); pg.wait_for_timeout(1500)
        if "active" not in (pg.locator("#an-price-tab").get_attribute("class") or ""):
            pg.click("#an-price-tab")
        pg.wait_for_selector("#an-price svg", timeout=20000); pg.wait_for_timeout(800)
        rec.note("probe.u6.fr_fresh_svg_label", pg.eval_on_selector_all("#an-price svg text", "els => els.slice(0,1).map(e => e.textContent)"))
        # U9: FRESH render of the month grid in fr (already fr before opening Agenda)
        W.nav(pg, "agenda"); pg.wait_for_timeout(1200)
        pg.click("#agenda-views [data-tab='week']"); pg.wait_for_timeout(700)
        pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(1200)
        rec.note("probe.u9.fr_fresh_moon_title", pg.eval_on_selector_all(".ag-moon", "els => els.slice(0,2).map(e => e.getAttribute('title') || e.dataset.ooTip)"))
        shot(pg, "U-U9-agenda-month-fr")
        switch_lang(pg, "en")
    pg.set_viewport_size({"width": 375, "height": 812})
    pg.wait_for_timeout(800)

    def open_nav(tab):
        W.dismiss_coach(pg)
        if not pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger"); pg.wait_for_timeout(500)
        pg.click(f"#navGroups .nav-item[data-tab='{tab}']"); pg.wait_for_timeout(700)
        if pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger", force=True); pg.wait_for_timeout(400)

    def open_settings(sub):
        W.dismiss_coach(pg)
        if not pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger"); pg.wait_for_timeout(500)
        pg.click(".sb-foot button[onclick=\"showTab('settings')\"]"); pg.wait_for_timeout(700)
        if pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger", force=True); pg.wait_for_timeout(400)
        pg.click(f"#set-subtabs [data-tab='{sub}']"); pg.wait_for_timeout(700)

    def surf(name, fn, root, shotname=None):
        try:
            fn(); pg.wait_for_timeout(900)
            W.dismiss_coach(pg)
            res = {"hscroll": hscroll(pg), "issues": pg.evaluate(CLIP_JS, root), "widest": widest(pg),
                   "nav_open": pg.evaluate("() => document.body.classList.contains('nav-open')")}
        except Exception as e:
            res = {"error": str(e)[:300]}
        rec.note(f"w375.{name}", res)
        if shotname:
            shot(pg, shotname)

    surf("home", lambda: open_nav("home"), "#tab-home", "U-375-home-en")

    def to_diag():
        open_settings("advanced")
        sel = "#set-advanced details.adv-sec[data-adv='diagnostics']"
        if not pg.evaluate(f"() => document.querySelector(\"{sel}\").open"):
            pg.click(f"{sel} > summary"); pg.wait_for_timeout(600)
        pg.locator("#set-advanced button[onclick='loadPatternsGate()']").scroll_into_view_if_needed()
        pg.click("#set-advanced button[onclick='loadPatternsGate()']"); pg.wait_for_timeout(1200)
        pg.locator("#patterns-gate").scroll_into_view_if_needed()
    surf("diagnostics-gate", to_diag, "#set-advanced details.adv-sec[data-adv='diagnostics']", "U-375-patterns-gate-en")

    def to_data():
        open_settings("data")
        pg.locator("#nl-files").scroll_into_view_if_needed()
    surf("data-newsletters", to_data, "#set-data")

    def to_markets():
        open_nav("markets"); pg.wait_for_selector("#mkt-dashboard .fam-member", timeout=20000)
    surf("commodities", to_markets, "#tab-markets")

    def to_price():
        mem = pg.locator("#mkt-dashboard .fam-member", has=pg.locator(".fam-mlabel", has_text=re.compile(r"^Dy$")))
        mem.first.locator("button.fam-mbtn[data-act='0']").click(); pg.wait_for_timeout(1200)
        if "active" not in (pg.locator("#an-price-tab").get_attribute("class") or ""):
            pg.click("#an-price-tab")
        pg.wait_for_selector("#an-price svg", timeout=20000)
        pg.locator("#an-price svg").scroll_into_view_if_needed()
    surf("analysis-price", to_price, "#an-price", "U-375-price-Dy-en")

    def to_agenda():
        open_nav("agenda"); pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(800)
    surf("agenda", to_agenda, "#tab-agenda")

    def to_law():
        open_nav("law"); pg.click("#gov-subtabs [data-tab='law']")
    surf("law", to_law, "#gov-law")

    def to_help():
        W.dismiss_coach(pg)
        pg.click("button.icon-btn[onclick=\"showTab('help')\"]"); pg.wait_for_timeout(1000)
    surf("help", to_help, "#tab-help", "U-375-help-en")
    rec.note("plane_fill_end", plane_filled(pg))
    rec.save(); br.close()
print("page_errors", rec.page_errors); print("console_errors", rec.console_errors)
print("http_errors", rec.http_errors); print("junk", rec.junk)
