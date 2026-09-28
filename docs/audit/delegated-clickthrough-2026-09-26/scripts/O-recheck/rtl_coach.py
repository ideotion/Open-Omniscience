"""Diagnostic: where the offline coach lands when first shown in Arabic (RTL), and whether a coach
placed in LTR is re-placed after the UI flips to RTL. Real clicks only (sidebar, switcher)."""
import json
from playwright.sync_api import sync_playwright
from recheck import (A, ARGS, PASS, COACH_STATE, COVERED, unlock, close_guide, switch_lang, shot, open_settings,
                     open_living, try_click, rec)

TOP = "#net-toggle, #lang-switch, #tm-open, #app-shutdown, #rate-toggle, #wiki-toggle"
R = {}


def wait_coach(pg, ms=12000):
    try:
        pg.wait_for_function("() => document.getElementById('net-coach').classList.contains('show')", timeout=ms)
        pg.wait_for_timeout(600)
        return True
    except Exception:
        return False


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=ARGS)
    # (a) the coach first shown while the UI is already Arabic
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.watch(pg, "rtl-a")
    unlock(pg, A, PASS); close_guide(pg)
    switch_lang(pg, "ar", rec)
    pg.reload(wait_until="networkidle")
    a = R["first_shown_in_ar"] = {"shown": wait_coach(pg), "coach": pg.evaluate(COACH_STATE),
                                  "topbar": pg.evaluate(COVERED, TOP)}
    shot(pg, "Orc-coach-rtl-home-ar.png")
    open_settings(pg)
    a["settings"] = [x for x in pg.evaluate(COVERED, "#set-subtabs button") if x["any_point_covered"]]
    a["click_data"] = try_click(pg, "#set-subtabs button[data-tab='data']", "settings data subtab (ar)")
    shot(pg, "Orc-coach-rtl-settings-ar.png")
    open_living(pg)
    a["living"] = [x for x in pg.evaluate(COVERED, "#living-subtabs button") if x["any_point_covered"]]
    ctx.close()
    # (b) the coach shown in English, then the UI flips to Arabic
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.watch(pg, "rtl-b")
    unlock(pg, A, PASS); close_guide(pg)
    pg.reload(wait_until="networkidle")
    b = R["shown_in_en_then_ar"] = {"shown": wait_coach(pg), "coach_en": pg.evaluate(COACH_STATE),
                                    "topbar_en": pg.evaluate(COVERED, TOP)}
    switch_lang(pg, "ar", rec)
    pg.wait_for_timeout(1500)
    b["coach_ar"] = pg.evaluate(COACH_STATE)
    b["topbar_ar"] = pg.evaluate(COVERED, TOP)
    b["plane_ar"] = pg.evaluate("() => { const r = document.getElementById('net-toggle').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(Math.round); }")
    shot(pg, "Orc-coach-en-then-ar.png")
    ctx.close()
    br.close()
R["page_errors"], R["http"], R["console"] = rec.page_errors, rec.http, rec.console_errors
json.dump(R, open("raw-rtl-coach.json", "w"), ensure_ascii=False, indent=1)
a = R["first_shown_in_ar"]
print("(a) shown", a["shown"], a["coach"]["cls"], a["coach"]["rect"])
print("   topbar", [(x["id"], x["rect"], x["any_point_covered"]) for x in a["topbar"]])
print("   settings covered", [(x["id"], x["rect"], x["centre_covered"]) for x in a["settings"]], a["click_data"].get("clicked"))
print("   living covered", [(x["id"], x["rect"], x["centre_covered"]) for x in a["living"]])
b = R["shown_in_en_then_ar"]
print("(b) shown", b["shown"], "en", b["coach_en"]["rect"], "ar", b["coach_ar"]["rect"], "plane ar", b["plane_ar"])
print("   topbar en", [(x["id"], x["rect"], x["any_point_covered"]) for x in b["topbar_en"]])
print("   topbar ar", [(x["id"], x["rect"], x["any_point_covered"]) for x in b["topbar_ar"]])
print(R["page_errors"], R["http"])
