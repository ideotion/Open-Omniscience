import json, re, sys
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright
R = {}
with sync_playwright() as p:
    b = launch(p); ctx = b.new_context(viewport={"width": 1440, "height": 950}); page = ctx.new_page()
    errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
    acc = {"on": False}; page.on("dialog", lambda d: d.accept() if acc["on"] else d.dismiss())
    page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(4000); close_dialogs(page); dismiss_coach(page)
    page.click("#navGroups button[data-tab=insights]")
    page.wait_for_selector("#ins-subtabs button[data-tab=watches]", state="visible", timeout=30000)
    page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(1200)
    page.fill("#wt-name", "Climate"); page.fill("#wt-query", "climate"); page.fill("#wt-threshold", "2"); page.fill("#wt-window", "30")
    page.locator("#ins-watches button", has_text="Add watch").first.click(); page.wait_for_timeout(2500)
    # switch language from Trends, then open Watches fresh (a new render)
    page.click("#ins-subtabs button[data-tab=trends]"); page.wait_for_timeout(1500)
    set_lang(page, "ar"); dismiss_coach(page)
    page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(2500)
    R["watch_list_ar_fresh_render"] = text(page, "#wt-list")
    shot(page, "N-N11-watch-ar")
    for lg in ["zh", "ja", "fr"]:
        set_lang(page, lg); dismiss_coach(page)
        page.click("#ins-subtabs button[data-tab=trends]"); page.wait_for_timeout(1500)
        page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(2500)
        R[f"watch_list_{lg}_fresh_render"] = text(page, "#wt-list")
    set_lang(page, "en")
    page.click("#ins-subtabs button[data-tab=trends]"); page.wait_for_timeout(1000)
    page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(2000)
    acc["on"] = True
    page.locator("#wt-list .card").filter(has_text="Climate").first.locator("button", has_text="Delete").click(); page.wait_for_timeout(2500)
    R["after_delete"] = text(page, "#wt-list"); R["errors"] = errs
    b.close()
(OUT / "R-ar-ins2.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1))
