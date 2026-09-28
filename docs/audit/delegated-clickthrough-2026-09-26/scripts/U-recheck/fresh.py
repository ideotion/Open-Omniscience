# -*- coding: utf-8 -*-
"""Recheck D1 (data-location step) + D7 (stacked first-run dialogs) on a FRESH instance (8853)."""
import json, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/U-recheck")
from common import *
BASE = "http://127.0.0.1:8853"
rec = Rec("fresh")
ctrl = json.loads(open("/tmp/claude-0/walk/U-recheck/handler_fresh.json").read())

def to_legal(pg):
    pg.goto(BASE, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(1200)
    if vis(pg, "#view-language"):
        pg.click("#lang-list button[lang='en']")
    pg.wait_for_selector("#view-legal:not(.hidden)", timeout=20000)
    pg.wait_for_function("() => (document.getElementById('lg-accept').textContent || '').trim().length > 0", timeout=20000)
    pg.check("#lg-check"); pg.wait_for_timeout(200)

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
    # --- A: the real flow, no interception ---
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.attach(pg)
    dl_resp = []
    pg.on("response", lambda r: dl_resp.append({"status": r.status, "body": (r.text() if "data-location" in r.url else None)}) if "/api/system/data-location" in r.url else None)
    to_legal(pg)
    pg.click("#lg-accept")
    pg.wait_for_selector("#view-datadir:not(.hidden), #view-create:not(.hidden)", timeout=20000)
    pg.wait_for_timeout(800)
    rec.note("A.datadir_visible", vis(pg, "#view-datadir"))
    rec.note("A.create_visible", vis(pg, "#view-create"))
    rec.note("A.data_location_responses", dl_resp)
    shot(pg, "U-D1-after-accept-real-en")
    ctx.close()
    # --- B: control -- the SAME page, the endpoint answered as its own handler answers for `fresh` ---
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.attach(pg)
    pg.route("**/api/system/data-location", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(ctrl)))
    to_legal(pg)
    pg.click("#lg-accept")
    pg.wait_for_selector("#view-datadir:not(.hidden), #view-create:not(.hidden)", timeout=20000)
    pg.wait_for_timeout(800)
    rec.note("B.control_datadir_visible", vis(pg, "#view-datadir"))
    if vis(pg, "#view-datadir"):
        rec.note("B.control_datadir_text", pg.eval_on_selector("#view-datadir", "e => e.innerText.replace(/\\s+/g,' ').slice(0,400)"))
        rec.note("B.default_checked", pg.is_checked("#dl-default"))
    shot(pg, "U-D1-control-200-datadir-en")
    ctx.close()
    # --- C: real flow to the end: create passphrase, land, which first-run dialogs are open ---
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.attach(pg)
    # instrument showModal ORDER only (no behaviour change): which dialog entered the top layer last
    pg.add_init_script("""(() => { const o = HTMLDialogElement.prototype.showModal;
      HTMLDialogElement.prototype.showModal = function() { (window.__modalOrder = window.__modalOrder || []).push(this.id + '@' + Math.round(performance.now())); return o.apply(this, arguments); }; })()""")
    to_legal(pg)
    pg.click("#lg-accept")
    pg.wait_for_selector("#view-create:not(.hidden)", timeout=20000)
    pg.fill("#pw1", "amber river quiet lantern walk"); pg.fill("#pw2", "amber river quiet lantern walk")
    pg.click("#btn-create")
    pg.wait_for_url("**/?wikiwizard=1**", timeout=120000)
    pg.wait_for_timeout(5000)
    st = pg.evaluate("""() => {
      const w = document.getElementById('wiki-wizard'), g = document.getElementById('guide-wizard');
      const topAt = (d) => { if (!d || !d.open) return null; const r = d.getBoundingClientRect();
        const e = document.elementFromPoint(r.left + r.width/2, r.top + 20); return e ? (e.closest('dialog') || {}).id || e.tagName : null; };
      return {url: location.href, wiki_open: !!(w && w.open), guide_open: !!(g && g.open),
              hit_at_wiki_center: topAt(w), hit_at_guide_center: topAt(g), modal_order: window.__modalOrder || []}; }""")
    rec.note("C.dialogs_after_entry", st)
    shot(pg, "U-D7-stacked-dialogs-en")
    rec.save()
    br.close()
