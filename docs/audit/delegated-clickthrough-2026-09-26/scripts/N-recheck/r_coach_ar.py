import json, sys
sys.path.insert(0, "/tmp/claude-0/walk/N-recheck")
from lib import *  # noqa
from r_coach import HIT, wait_coach
from playwright.sync_api import sync_playwright
R = {}
with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    page = ctx.new_page()
    unlock_if_locked(page); close_dialogs(page)
    R["coach_shown_en"] = wait_coach(page)
    R["before_switch"] = page.evaluate(HIT, ".nav-item[data-tab=insights]")
    set_lang(page, "ar")
    page.wait_for_timeout(1500)
    R["dir"] = page.evaluate("() => document.documentElement.dir")
    R["after_switch"] = page.evaluate(HIT, ".nav-item[data-tab=insights]")
    shot(page, "N-recheck-coach-after-switch-ar")
    try:
        page.click(".nav-item[data-tab=insights]", timeout=4000); R["click"] = "clicked"
    except Exception as e:
        R["click"] = "blocked: " + str(e).split("\n")[0][:200]
    dismiss_coach(page)
    set_lang(page, "en")
    b.close()
(OUT / "R-coach-ar.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1))
