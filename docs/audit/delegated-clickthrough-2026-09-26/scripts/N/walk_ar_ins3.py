import json, re, sys
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright
R = {}
with sync_playwright() as p:
    b = launch(p); ctx = b.new_context(viewport={"width": 1440, "height": 950}); page = ctx.new_page()
    acc = {"on": False}; page.on("dialog", lambda d: d.accept() if acc["on"] else d.dismiss())
    page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(4000); close_dialogs(page); dismiss_coach(page)
    page.click("#navGroups button[data-tab=insights]")
    page.wait_for_selector("#ins-subtabs button[data-tab=watches]", state="visible", timeout=30000)
    page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(1200)
    if page.locator("#wt-list .card").count() == 0:
        page.fill("#wt-name", "Climate"); page.fill("#wt-query", "climate"); page.fill("#wt-threshold", "2"); page.fill("#wt-window", "30")
        page.locator("#ins-watches button", has_text="Add watch").first.click(); page.wait_for_timeout(2500)
    R["existing_cards"] = page.locator("#wt-list .card").count()
    set_lang(page, "ar")
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(4000); dismiss_coach(page)
    page.click("#navGroups button[data-tab=insights]")
    page.wait_for_selector("#ins-subtabs button[data-tab=watches]", state="visible", timeout=30000)
    page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(2500)
    R["lang"] = page.evaluate("() => document.documentElement.lang")
    R["watch_list_ar_after_reload"] = text(page, "#wt-list")
    shot(page, "N-N11-watch-ar-reload")
    page.click("#ins-subtabs button[data-tab=trends]"); page.wait_for_selector("#trd-rising a.tb-label, #trd-top a.tb-label", timeout=60000); page.wait_for_timeout(1500)
    el = page.locator("#trd-rising a.tb-label, #trd-top a.tb-label").filter(has_text=re.compile(r"^climate$")).first
    el.hover(); page.wait_for_timeout(3000)
    R["ins_hover_ar_after_reload"] = page.evaluate("() => { const e=document.getElementById('oo-tip'); return e && e.classList.contains('show') ? e.textContent.trim() : ''; }")
    shot(page, "N-N11-insights-hover-ar")
    (OUT / "R-ar-ins3.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
    set_lang(page, "en")
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(4000); dismiss_coach(page)
    page.click("#navGroups button[data-tab=insights]")
    page.wait_for_selector("#ins-subtabs button[data-tab=watches]", state="visible", timeout=30000)
    page.click("#ins-subtabs button[data-tab=watches]"); page.wait_for_timeout(2500)
    R["list_before_delete_en"] = text(page, "#wt-list")
    acc["on"] = True
    page.locator("#wt-list .card").filter(has_text="“climate”").first.locator("button", has_text="Delete").click(); page.wait_for_timeout(2500)
    R["after_delete"] = text(page, "#wt-list")
    b.close()
(OUT / "R-ar-ins3.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1))
