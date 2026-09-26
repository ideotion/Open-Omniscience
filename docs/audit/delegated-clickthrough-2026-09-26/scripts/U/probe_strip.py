# -*- coding: utf-8 -*-
"""Probe: does the Home at-a-glance strip follow a switch to ar? (8851, already unlocked)."""
import sys
from playwright.sync_api import sync_playwright
from common import *

BASE = "http://127.0.0.1:8851"
rec = Rec("probe_strip")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec.attach(pg)
    pg.goto(BASE + "/#home", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(4000)
    close_unrelated_dialogs(pg)
    strip = "#home-stats"
    rec.note("strip_parent", pg.evaluate("() => { const e = document.getElementById('home-stats'); return e ? e.parentElement.outerHTML.slice(0, 600) : null; }"))
    rec.note("strip_en", text_of(pg, strip))
    for seq in [["ar"], ["fr", "ar"], ["zh", "ar"], ["en", "ar"]]:
        for code in seq:
            switch_lang(pg, code)
        for w in (0, 3000, 8000):
            pg.wait_for_timeout(w)
            rec.note(f"strip_{'-'.join(seq)}_+{w}", text_of(pg, strip) + " || " + text_of(pg, "#home-stats + *") if pg.query_selector("#home-stats + *") else text_of(pg, strip))
    rec.save(); br.close()
print(rec.page_errors, rec.console_errors, rec.http_errors)
