"""Row O walk, instance B (encrypted, EMPTY, legacy scheduler_settings.json {"mode": "markets"}): O12."""
import sys
import traceback

from playwright.sync_api import sync_playwright

import lib
from lib import Rec, close_guide, junk, living_sub, save, settings_sub, shot, switch_lang, tip_of, txt, unhover, unlock

BASE = "http://127.0.0.1:8835"
rec = Rec()
R = {}


def open_legacy(pg):
    settings_sub(pg, "advanced")
    det = pg.locator("details[data-adv='collect']")
    if not det.evaluate("d => d.open"):
        lib.clear_coach_if_blocking(pg, "details[data-adv='collect'] > summary", "collection summary")
        det.locator("summary").first.click()
        pg.wait_for_timeout(600)
    leg = pg.locator("details.adv-collect", has=pg.locator("#sch-depth"))
    if not leg.evaluate("d => d.open"):
        leg.locator("summary").first.click()
    pg.wait_for_timeout(1800)


def legacy_state(pg):
    return {
        "mode_select_present": pg.evaluate("() => !!document.getElementById('sch-mode') || !!document.querySelector('#tab-settings select[id*=mode]:not(#fetch-mode)')"),
        "notice_visible": pg.is_visible("#sch-retired"),
        "notice_text": txt(pg, "#sch-retired-text"),
        "notice_dir": pg.evaluate("() => getComputedStyle(document.getElementById('sch-retired')).direction"),
        "depth_visible": pg.is_visible("#sch-depth"), "pages_visible": pg.is_visible("#sch-pages"),
        "crawl_hint": pg.evaluate("() => document.getElementById('crawl-fields').nextElementSibling.innerText"),
        "market_rules": pg.is_checked("#sch-market-rules"), "stat_refresh": pg.is_checked("#sch-stat-refresh"),
        "labels": pg.evaluate("() => [document.getElementById('sch-market-rules').parentElement.innerText.trim(), document.getElementById('sch-stat-refresh').parentElement.innerText.trim()]"),
    }


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking",
                                 "--disable-component-update", "--no-proxy-server"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page()
    rec.watch(pg, "B")
    try:
        R["unlock"] = unlock(pg, BASE, "walk-pass-2026")
        R["unlock"]["guide_open"] = pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }")
        close_guide(pg)
        R["sched_before_view"] = lib.api(pg, "/api/scheduler/config")["body"][:1500]
        R["lanes_before"] = lib.api(pg, "/api/storage/lanes")["body"][:2500]
        # (1) Living sources
        lib.living_open(pg)
        o = R["living"] = {}
        o["wiki_facts"] = txt(pg, "#living-wiki-facts")
        f = pg.locator("#living-wiki-facts .living-fact").first
        o["state_tip"] = tip_of(pg, f)
        unhover(pg)
        o["stream"] = txt(pg, "#living-stream")
        o["pages"] = txt(pg, "#living-pages")
        o["junk_wiki"] = junk(pg, "#living-wiki")
        shot(pg, "O-O12-fresh-wiki-en.png", full=True)
        living_sub(pg, "law")
        o["law_facts"] = txt(pg, "#living-law-facts")
        o["law_changes"] = txt(pg, "#living-law-changes")
        living_sub(pg, "osm")
        o["maps_facts"] = txt(pg, "#living-osm-facts")
        o["maps_regions"] = txt(pg, "#living-osm-regions")
        o["junk_all"] = junk(pg, "#tab-living")
        shot(pg, "O-O12-fresh-maps-en.png", full=True)
        # (2) Storage
        settings_sub(pg, "data")
        pg.wait_for_function("() => document.querySelectorAll('#storage-lanes tbody tr').length >= 4", timeout=20000)
        pg.wait_for_timeout(500)
        o = R["storage"] = {}
        o["rows"] = pg.evaluate("() => [...document.querySelectorAll('#storage-lanes tbody tr')].map(r => [...r.children].map(c => c.innerText.trim()))")
        o["wiki_size_tip"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(2) td:nth-child(2) span").first)
        o["corpus_growth_tip"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(1) td:nth-child(4) span").first)
        unhover(pg)
        shot(pg, "O-O12-fresh-storage-en.png")
        # the export row on an absent lane (note 7)
        pg.locator("#set-data button[onclick='openUnifiedExport()']").click()
        pg.wait_for_function("() => document.getElementById('ux-export').open && document.querySelectorAll('#ux-checklist label').length > 2", timeout=15000)
        pg.wait_for_timeout(600)
        o["export_rows"] = pg.evaluate("() => [...document.querySelectorAll('#ux-checklist label')].map(l => l.innerText.trim())")
        pg.locator("#ux-export button[onclick*='close()']").first.click()
        pg.wait_for_timeout(300)
        # (3) Collection -> Advanced (legacy)
        o = R["sched"] = {}
        open_legacy(pg)
        o["en"] = legacy_state(pg)
        pg.locator("#sch-retired").scroll_into_view_if_needed()
        shot(pg, "O-O12-retired-notice-en.png")
        for loc in ("fr", "ar"):
            switch_lang(pg, loc, rec)
            pg.wait_for_timeout(800)
            o[loc] = legacy_state(pg)
            o[loc]["html_dir"] = pg.evaluate("() => document.documentElement.dir")
            o[loc]["preview_line"] = txt(pg, "#sched-targets")
            pg.locator("#sch-retired").scroll_into_view_if_needed()
            shot(pg, f"O-O12-retired-notice-{loc}.png")
        switch_lang(pg, "en", rec)
        pg.wait_for_timeout(800)
        # Dismiss, untick price rules, Save schedule
        pg.locator("#sch-retired button").click()
        pg.wait_for_timeout(1200)
        o["after_dismiss_visible"] = pg.is_visible("#sch-retired")
        pg.uncheck("#sch-market-rules")
        pg.locator("button[onclick='saveScheduler()']").click()
        pg.wait_for_timeout(1500)
        o["save_toast"] = txt(pg, "#toast")
        o["cfg_after_save"] = lib.api(pg, "/api/scheduler/config")["body"][:1500]
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(1500)
        close_guide(pg)
        open_legacy(pg)
        o["after_reload"] = legacy_state(pg)
        shot(pg, "O-O12-after-save-reload-en.png")
        R["lanes_after"] = lib.api(pg, "/api/storage/lanes")["body"][:2500]
    except Exception:
        R["_exception"] = traceback.format_exc()[-3000:]
        print(R["_exception"])
        try:
            shot(pg, "_fail-b.png")
        except Exception:
            pass
    save("raw-b.json", {"R": R, "coach_blocks": lib.COACH_BLOCKS, "page_errors": rec.page_errors,
                        "console_errors": rec.console_errors, "http": rec.http})
    br.close()
print("done b")
