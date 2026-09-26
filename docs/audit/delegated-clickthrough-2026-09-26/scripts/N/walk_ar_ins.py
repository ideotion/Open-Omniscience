"""N11 (ar) remainder: Insights Trends hover + the watch row in Arabic. Recreates the N8 watch
through the UI (en), reads it in ar, then deletes it in en."""
import json, re, sys, traceback
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright

R: dict = {}
rec = Recorder("ar-ins")
with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    rec.attach_context(ctx, "arins")
    page = ctx.new_page(); rec.attach(page, "main")
    dialogs = []; accept = {"on": False}
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept() if accept["on"] else d.dismiss()))
    try:
        page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(4000); close_dialogs(page)
        # en: add the watch exactly as N8 does
        page.click("#navGroups button[data-tab=insights]")
        page.wait_for_selector("#ins-subtabs button[data-tab=watches]", state="visible", timeout=30000)
        page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(1200)
        page.fill("#wt-name", "Climate"); page.fill("#wt-query", "climate"); page.fill("#wt-threshold", "2"); page.fill("#wt-window", "30")
        page.locator("#ins-watches button", has_text="Add watch").first.click(); page.wait_for_timeout(2500)
        R["en_watch_list"] = text(page, "#wt-list")
        set_lang(page, "ar")
        page.wait_for_timeout(1500)
        R["coach_after_lang_switch"] = page.evaluate("() => { const c=document.getElementById('net-coach'); if(!c||!c.classList.contains('show')) return null; const r=c.getBoundingClientRect(); return [Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom)]; }")
        if R["coach_after_lang_switch"]:
            ins = page.evaluate("() => { const r=document.querySelector('#navGroups button[data-tab=insights]').getBoundingClientRect(); return [Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom)]; }")
            R["insights_nav_rect"] = ins
            shot(page, "N-N11-coach-rtl-ar")
            dismiss_coach(page)
        R["watch_list_ar"] = text(page, "#wt-list")
        con = page.locator("#wt-list .hint span").first
        R["watch_concept_span"] = con.inner_text().strip() if con.count() else None
        if con.count():
            con.hover(); page.wait_for_timeout(900)
            R["watch_concept_tip_ar"] = page.evaluate("() => { const e=document.getElementById('oo-tip'); return e && e.classList.contains('show') ? e.textContent.trim() : ''; }")
        R["rtl"] = page.evaluate("() => ({dir: document.documentElement.dir, sidebar_left: Math.round(document.getElementById('sidebar').getBoundingClientRect().left)})")
        R["overflow_watches"] = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        shot(page, "N-N11-watch-ar")
        page.click("#ins-subtabs button[data-tab=trends]")
        page.wait_for_selector("#trd-rising a.tb-label, #trd-top a.tb-label", timeout=60000); page.wait_for_timeout(1500)
        loc = page.locator("#trd-rising a.tb-label, #trd-top a.tb-label").filter(has_text=re.compile(r"^climate$"))
        R["climate_rows"] = loc.count()
        if loc.count():
            el = loc.first; el.scroll_into_view_if_needed(); el.hover(); page.wait_for_timeout(3000)
            R["ins_hover_ar"] = page.evaluate("() => { const e=document.getElementById('oo-tip'); return e && e.classList.contains('show') ? e.textContent.trim() : ''; }")
            shot(page, "N-N11-insights-hover-ar")
        R["overflow_trends"] = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        rec.junk_scan(page, "#tab-insights", "N11 insights ar")
        # delete in en
        set_lang(page, "en")
        page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(1500)
        card = page.locator("#wt-list .card").filter(has_text="Climate")
        accept["on"] = True
        card.first.locator("button", has_text="Delete").click(); page.wait_for_timeout(2500)
        accept["on"] = False
        R["after_delete"] = text(page, "#wt-list")
    except Exception as e:  # noqa: BLE001
        R["exception"] = f"{type(e).__name__}: {str(e)[:400]}"; R["trace"] = traceback.format_exc()[-1000:]
        shot(page, "N-N11-ar-ins-exception")
    R["dialogs"] = dialogs
    b.close()
rec.data = R; rec.save()
(OUT / "R-ar-ins.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1)); print("PE", rec.page_errors, "CE", rec.console_errors, "HTTP", rec.http_errors, "JUNK", rec.junk)
