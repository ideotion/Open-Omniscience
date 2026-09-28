"""Row O independent recheck: the four reported defects, reproduced on fresh encrypted instances.

Every step drives the real UI (sidebar, subtabs, top-bar language switcher, buttons). page.evaluate
is used only to READ the DOM / loopback API, to read OOI18N.t() as a pure dictionary lookup for
diagnosis (clearly labelled), and to close the unrelated first-run guide.
"""
import json
import sys

from playwright.sync_api import sync_playwright

import re
from lib import OUT, Rec, close_guide, junk, shot, switch_lang, tip_of, unhover, api
from lib import unlock as _unlock


def unlock(pg, base, pw):
    """The server stays unlocked after the first browser unlocks it: then '/' serves the app."""
    pg.goto(base + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(1500)
    if pg.locator("#pw").count() or pg.locator("#view-language").count() or pg.locator("#view-legal").count():
        return _unlock(pg, base, pw)
    pg.wait_for_load_state("networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    return {"already_unlocked": True, "url": pg.url}

PASS = "walk-pass-2026"
A = "http://127.0.0.1:8836"
B = "http://127.0.0.1:8837"
ARGS = ["--no-sandbox", "--disable-background-networking", "--no-proxy-server"]
R = {}
rec = Rec()

COACH_STATE = """() => { const c = document.getElementById('net-coach'); if (!c) return null;
  const r = c.getBoundingClientRect();
  let st = null; try { st = JSON.parse(localStorage.getItem('oo_net_coach_v1')); } catch (e) {}
  return {cls: c.className, visible: getComputedStyle(c).display !== 'none',
          rect: [r.left, r.top, r.right, r.bottom].map(Math.round), z: getComputedStyle(c).zIndex,
          store: st, guide_open: !!(document.getElementById('guide-wizard') || {}).open}; }"""

COVERED = """(sel) => { const c = document.getElementById('net-coach');
  const out = [];
  for (const b of document.querySelectorAll(sel)) {
    const r = b.getBoundingClientRect(); if (!r.width || !r.height) continue;
    // sample 5 points of the control: centre + 4 inset corners
    const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 3, r.top + 3], [r.right - 3, r.top + 3],
                 [r.left + 3, r.bottom - 3], [r.right - 3, r.bottom - 3]];
    const hits = pts.map(([x, y]) => { const h = document.elementFromPoint(x, y); return !!(h && c && c.contains(h)); });
    out.push({id: b.id || b.dataset.tab || b.getAttribute('data-lang') || b.textContent.trim().slice(0, 30),
              text: b.textContent.trim().slice(0, 40), rect: [r.left, r.top, r.right, r.bottom].map(Math.round),
              centre_covered: hits[0], any_point_covered: hits.some(Boolean)});
  }
  return out; }"""


def coach_report(pg, where):
    return {
        "where": where,
        "lang": pg.evaluate("() => document.documentElement.lang"),
        "viewport": pg.viewport_size,
        "coach": pg.evaluate(COACH_STATE),
        "topbar": pg.evaluate(COVERED, "#net-toggle, #lang-switch, #tm-open, #app-shutdown"),
        "set_subtabs": pg.evaluate(COVERED, "#set-subtabs button"),
        "living_subtabs": pg.evaluate(COVERED, "#living-subtabs button"),
    }


def open_settings(pg):
    close_guide(pg)
    sel = ".sb-foot button.secondary"
    onscreen = pg.evaluate("(s) => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.left >= 0 && r.right <= innerWidth; }", sel)
    if not onscreen and pg.is_visible("#hamburger"):
        pg.click("#hamburger")
        pg.wait_for_timeout(500)
    pg.click(sel)
    pg.wait_for_timeout(1200)


def open_living(pg):
    close_guide(pg)
    sel = ".nav-item[data-tab='living']"
    onscreen = pg.evaluate("(s) => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.left >= 0 && r.right <= innerWidth; }", sel)
    if not onscreen and pg.is_visible("#hamburger"):
        pg.click("#hamburger")
        pg.wait_for_timeout(500)
    pg.click(sel)
    pg.wait_for_timeout(2500)


def try_click(pg, sel, label):
    """A REAL click with Playwright's actionability check; report what intercepted it."""
    try:
        pg.click(sel, timeout=2500)
        return {"control": label, "clicked": True}
    except Exception as exc:
        msg = str(exc)
        return {"control": label, "clicked": False, "intercepted_by_coach": "coach" in msg, "error": msg[:260]}


def phase_coach_wide(br):
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page()
    rec.watch(pg, "A-coach")
    R["unlock_A"] = unlock(pg, A, PASS)
    out = R["coach_1440"] = {"launch1_after_unlock": pg.evaluate(COACH_STATE)}
    close_guide(pg)
    out["launch1_after_guide_closed"] = pg.evaluate(COACH_STATE)
    # Second launch in the same browser profile (a reload: the guide is done now)
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(2500)
    out["launch2"] = pg.evaluate(COACH_STATE)
    shot(pg, "Orc-coach-home-launch2-en.png")
    for loc in ("en", "fr", "ar"):
        if loc != "en":
            switch_lang(pg, loc, rec)  # the coach must not cover the switcher (the guarded cluster)
        open_settings(pg)
        rep = coach_report(pg, "settings")
        rep["click_data_subtab"] = try_click(pg, "#set-subtabs button[data-tab='data']", "settings data subtab")
        rep["click_advanced_subtab"] = try_click(pg, "#set-subtabs button[data-tab='advanced']", "settings advanced subtab")
        shot(pg, f"Orc-coach-settings-{loc}.png")
        open_living(pg)
        rep_l = coach_report(pg, "living")
        rep_l["click_law_subtab"] = try_click(pg, "#living-subtabs button[data-tab='law']", "living law subtab")
        rep_l["click_osm_subtab"] = try_click(pg, "#living-subtabs button[data-tab='osm']", "living maps subtab")
        shot(pg, f"Orc-coach-living-{loc}.png")
        out[f"settings_{loc}"] = rep
        out[f"living_{loc}"] = rep_l
    switch_lang(pg, "en", rec)
    ctx.close()


def phase_coach_narrow(br):
    ctx = br.new_context(viewport={"width": 375, "height": 800})
    pg = ctx.new_page()
    rec.watch(pg, "A-coach-375")
    unlock(pg, A, PASS)
    out = R["coach_375"] = {"launch1": pg.evaluate(COACH_STATE)}
    close_guide(pg)
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(2500)
    out["launch2"] = pg.evaluate(COACH_STATE)
    open_living(pg)
    rep = coach_report(pg, "living")
    rep["click_law_subtab"] = try_click(pg, "#living-subtabs button[data-tab='law']", "living law subtab")
    out["living_en"] = rep
    shot(pg, "Orc-coach-living-375-en.png")
    ctx.close()


def phase_i18n(br):
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page()
    rec.watch(pg, "A-i18n")
    unlock(pg, A, PASS)
    close_guide(pg)
    pg.wait_for_timeout(800)
    # this context shows no coach on launch 1 (the guide was open); confirm, then proceed
    R["i18n_coach_state"] = pg.evaluate(COACH_STATE)
    if R["i18n_coach_state"] and "show" in (R["i18n_coach_state"]["cls"] or ""):
        pg.click("#net-coach-dismiss")
    out = R["i18n"] = {}
    for loc in ("en", "fr", "ar", "zh"):
        o = out[loc] = {}
        if loc != "en":
            assert switch_lang(pg, loc, rec)
        o["main_lang"] = pg.evaluate("() => document.documentElement.lang")
        o["main_title"] = pg.title()
        # ---- D4: the task manager tab's title ----
        with ctx.expect_page(timeout=15000) as newp:
            pg.click("#tm-open")
        tm = newp.value
        rec.watch(tm, f"tasks-{loc}")
        tm.wait_for_load_state("networkidle", timeout=30000)
        tm.wait_for_timeout(2000)
        o["tm_title_2s"] = tm.title()
        tm.wait_for_timeout(5000)
        o["tm_title_7s"] = tm.title()
        o["tm_lang"] = tm.evaluate("() => document.documentElement.lang")
        o["tm_dir"] = tm.evaluate("() => document.documentElement.dir")
        o["tm_h1"] = tm.evaluate("() => (document.querySelector('h1') || {}).innerText || null")
        o["tm_tabs"] = tm.evaluate("() => [...document.querySelectorAll('#tm-tabs button')].map(b => b.innerText.trim())")
        # DIAGNOSTIC (pure dictionary lookups, no state change): is the key there, and does t() know it?
        o["diag_t_title_key"] = tm.evaluate("() => OOI18N.t('Task manager · FOOS')")
        o["diag_title_node_parent"] = tm.evaluate("() => document.querySelector('title').parentNode.nodeName")
        tm.screenshot(path=f"{OUT}/Orc-tm-{loc}.png")
        tm.close()
        # ---- D1: the Export dialog's Living sources row hover ----
        open_settings(pg)
        pg.click("#set-subtabs button[data-tab='data']")
        pg.wait_for_timeout(1200)
        pg.locator("#set-data button[onclick='openUnifiedExport()']").click()
        pg.wait_for_function("() => document.getElementById('ux-export').open && document.querySelectorAll('#ux-checklist label').length > 2", timeout=15000)
        pg.wait_for_timeout(1000)
        o["export_rows"] = pg.evaluate("""() => [...document.querySelectorAll('#ux-checklist label')].map(l => {
            const i = l.querySelector('input'); return {text: l.innerText.trim(), checked: i && i.checked, disabled: i && i.disabled,
            title: l.getAttribute('title')}; })""")
        lab = pg.locator("#ux-checklist label:has(#ux-c-lanes)")
        o["living_row_tip"] = tip_of(pg, lab, wait=900) if lab.count() else "row not found"
        o["diag_t_reason"] = pg.evaluate("() => OOI18N.t('a lane is a live encrypted database; its backup format is not settled yet')")
        o["diag_t_label"] = pg.evaluate("() => OOI18N.t('Living sources')")
        o["dialog_status"] = pg.evaluate("() => (document.getElementById('ux-inv-status') || {}).innerText")
        shot(pg, f"Orc-export-{loc}.png")
        unhover(pg)
        pg.locator("#ux-export button[onclick*='close()']").first.click()
        pg.wait_for_timeout(500)
    switch_lang(pg, "en", rec)
    R["inventory_A"] = json.loads(api(pg, "/api/backup/inventory")["body"]).get("lanes")
    ctx.close()


def phase_absent(br):
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page()
    rec.watch(pg, "B")
    R["unlock_B"] = unlock(pg, B, PASS)
    close_guide(pg)
    st = pg.evaluate(COACH_STATE)
    if st and "show" in (st["cls"] or ""):
        pg.click("#net-coach-dismiss")
    out = R["absent"] = {}
    open_settings(pg)
    pg.click("#set-subtabs button[data-tab='data']")
    pg.wait_for_function("() => document.querySelectorAll('#storage-lanes tbody tr').length >= 4", timeout=20000)
    pg.wait_for_timeout(800)
    out["storage_rows"] = pg.evaluate("() => [...document.querySelectorAll('#storage-lanes tbody tr')].map(r => r.innerText.replace(/\\s+/g, ' ').trim())")
    pg.locator("#set-data button[onclick='openUnifiedExport()']").click()
    pg.wait_for_function("() => document.getElementById('ux-export').open && document.querySelectorAll('#ux-checklist label').length > 2", timeout=15000)
    pg.wait_for_timeout(1000)
    out["export_rows"] = pg.evaluate("""() => [...document.querySelectorAll('#ux-checklist label')].map(l => {
        const i = l.querySelector('input'); return {text: l.innerText.trim(), checked: i && i.checked, disabled: i && i.disabled,
        title: l.getAttribute('title')}; })""")
    lab = pg.locator("#ux-checklist label:has(#ux-c-lanes)")
    out["living_row_tip"] = tip_of(pg, lab, wait=900) if lab.count() else "row not found"
    shot(pg, "Orc-export-absent-en.png")
    unhover(pg)
    out["junk_dialog"] = junk(pg, "#ux-export")
    pg.locator("#ux-export button[onclick*='close()']").first.click()
    out["inventory"] = json.loads(api(pg, "/api/backup/inventory")["body"])
    out["storage_api_wiki"] = [x for x in json.loads(api(pg, "/api/storage/lanes")["body"]).get("lanes", []) if x.get("kind") == "wiki"]
    ctx.close()


phases = sys.argv[1:] or ["coach", "narrow", "i18n", "absent"]
if __name__ != "__main__":
    phases = []
if phases:
  with sync_playwright() as p:
      br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=ARGS)
      try:
          if "coach" in phases:
              phase_coach_wide(br)
          if "narrow" in phases:
              phase_coach_narrow(br)
          if "i18n" in phases:
              phase_i18n(br)
          if "absent" in phases:
              phase_absent(br)
      finally:
          R["page_errors"], R["console_errors"], R["http"] = rec.page_errors, rec.console_errors, rec.http
          with open(f"{OUT}/raw-{'-'.join(phases)}.json", "w", encoding="utf-8") as fh:
              json.dump(R, fh, ensure_ascii=False, indent=1)
          br.close()
  print("done", phases)
