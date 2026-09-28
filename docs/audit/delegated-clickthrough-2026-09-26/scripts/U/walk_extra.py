# -*- coding: utf-8 -*-
"""Extra locale re-checks (U6 overlay, U7 block, U9 moon hover) + the 375 px en pass."""
import sys, re
from playwright.sync_api import sync_playwright
from common import *
import walk_main as W  # noqa -- reuse helpers (module guarded below)

BASE = "http://127.0.0.1:8850"
rec = Rec("extra")
W.rec = rec

CLIP_JS = """(root) => { const out = []; const r = document.querySelector(root); if (!r) return ['(no root)'];
  r.querySelectorAll('*').forEach(e => { if (!e.getClientRects().length) return; const cs = getComputedStyle(e);
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) return;
    if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip' || cs.textOverflow === 'ellipsis' || cs.whiteSpace === 'nowrap') && e.scrollWidth > e.clientWidth + 1)
      out.push(e.tagName + (e.id ? '#' + e.id : '') + '.' + e.className + ' :: ' + e.textContent.trim().slice(0, 60) + ` [${e.scrollWidth}>${e.clientWidth}]`);
    const b = e.getBoundingClientRect(); if (b.right > innerWidth + 1 || b.left < -1) out.push('OFFSCREEN ' + e.tagName + '.' + e.className + ' :: ' + e.textContent.trim().slice(0, 60) + ` [${Math.round(b.left)}..${Math.round(b.right)}]`);
  }); return out.slice(0, 25); }"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    close_unrelated_dialogs(pg)
    # --- U6 overlay in fr / ar / zh: open Dy price, then switch language while on it
    if "only375" not in sys.argv:
      pass
    if "only375" in sys.argv:
        goto375 = True
    else:
        goto375 = False
    W.nav(pg, "markets")
    pg.wait_for_selector("#mkt-dashboard .fam-member", timeout=30000)
    mem = pg.locator("#mkt-dashboard .fam-member", has=pg.locator(".fam-mlabel", has_text=re.compile(r"^Dy$")))
    mem.first.locator("button.fam-mbtn[data-act='0']").click()
    pg.wait_for_timeout(1500)
    if "active" not in (pg.locator("#an-price-tab").get_attribute("class") or ""):
        pg.click("#an-price-tab")
    pg.wait_for_selector("#an-price svg", timeout=20000)
    for code in ["fr", "ar", "zh"]:
        switch_lang(pg, code)
        pg.wait_for_timeout(600)
        rec.note(f"u6.{code}.after_switch", {"head": text_of(pg, "#an-price .hint"), "svg_texts": pg.eval_on_selector_all("#an-price svg text", "els => els.slice(0,2).map(e => e.textContent)"),
                                             "note": pg.evaluate("() => [...document.querySelectorAll('#an-price > div')].map(d => d.textContent).slice(-1)[0]"),
                                             "tab": text_of(pg, "#an-price-tab")})
        # re-open the Price subtab (another subtab, then back) to see a fresh render
        pg.click("#an-subtabs [data-tab='overview']"); pg.wait_for_timeout(500)
        pg.click("#an-price-tab"); pg.wait_for_selector("#an-price svg", timeout=20000); pg.wait_for_timeout(800)
        rec.note(f"u6.{code}.after_reopen", {"head": text_of(pg, "#an-price .hint"), "svg_texts": pg.eval_on_selector_all("#an-price svg text", "els => els.slice(0,2).map(e => e.textContent)"),
                                              "note": pg.evaluate("() => [...document.querySelectorAll('#an-price > div')].map(d => d.textContent).slice(-1)[0]"),
                                              "bars": pg.evaluate("() => document.querySelectorAll('#an-price svg rect[fill-opacity=\"0.55\"]').length")})
        if code == "ar":
            shot(pg, "U-U6-price-Dy-ar")
    switch_lang(pg, "en")
    # --- U9 moon hover in fr / ar / zh
    W.nav(pg, "agenda"); pg.wait_for_timeout(1200)
    pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(1200)
    for code in ["fr", "ar", "zh"]:
        switch_lang(pg, code); pg.wait_for_timeout(1000)
        n = pg.evaluate("() => document.querySelectorAll('.ag-moon').length")
        rec.note(f"u9.{code}.moon", {"n": n, "hover": W.tip_text(pg, ".ag-moon") if n else None})
    switch_lang(pg, "en")
    # --- 375 px en pass
    pg.set_viewport_size({"width": 375, "height": 812})
    pg.wait_for_timeout(800)
    checks = {}
    def surf(name, fn, root):
        try:
            fn(); pg.wait_for_timeout(900)
            checks[name] = {"hscroll": hscroll(pg), "clipped": pg.evaluate(CLIP_JS, root)}
        except Exception as e:
            checks[name] = {"error": str(e)[:300]}
        rec.note(f"w375.{name}", checks[name])
    def open_nav(tab):
        W.dismiss_coach(pg)
        if not pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger"); pg.wait_for_timeout(500)
        pg.click(f"#navGroups .nav-item[data-tab='{tab}']"); pg.wait_for_timeout(600)
        if pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger"); pg.wait_for_timeout(300)
    surf("home", lambda: open_nav("home"), "#tab-home")
    shot(pg, "U-375-home-en")
    def to_diag():
        open_nav("home")
        pg.evaluate("() => 0")
        W.dismiss_coach(pg)
        if not pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger"); pg.wait_for_timeout(500)
        pg.click(".sb-foot button[onclick=\"showTab('settings')\"]"); pg.wait_for_timeout(600)
        if pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger"); pg.wait_for_timeout(300)
        pg.click("#set-subtabs [data-tab='advanced']"); pg.wait_for_timeout(600)
        sel = "#set-advanced details.adv-sec[data-adv='diagnostics']"
        if not pg.evaluate(f"() => document.querySelector(\"{sel}\").open"):
            pg.click(f"{sel} > summary"); pg.wait_for_timeout(600)
        pg.locator("#set-advanced button[onclick='loadPatternsGate()']").scroll_into_view_if_needed()
        pg.click("#set-advanced button[onclick='loadPatternsGate()']"); pg.wait_for_timeout(1200)
        pg.locator("#patterns-gate").scroll_into_view_if_needed()
    surf("diagnostics-gate", to_diag, "#set-advanced details.adv-sec[data-adv='diagnostics']")
    shot(pg, "U-375-patterns-gate-en")
    def to_data():
        pg.click("#set-subtabs [data-tab='data']"); pg.wait_for_timeout(700)
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
    surf("analysis-price", to_price, "#tab-analyze")
    shot(pg, "U-375-price-Dy-en")
    surf("agenda", lambda: (open_nav("agenda"), pg.click("#agenda-views [data-tab='month']")), "#tab-agenda")
    surf("law", lambda: (open_nav("law"), pg.click("#gov-subtabs [data-tab='law']")), "#gov-law")
    surf("help", lambda: pg.click("button.icon-btn[onclick=\"showTab('help')\"]"), "#tab-help")
    rec.note("plane_fill_end", plane_filled(pg))
    rec.save(); br.close()
print("page_errors", rec.page_errors); print("console_errors", rec.console_errors)
print("http_errors", rec.http_errors); print("junk", rec.junk)
