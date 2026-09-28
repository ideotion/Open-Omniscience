import json, re, sys
sys.path.insert(0, "/tmp/claude-0/walk/N-recheck")
from lib import *  # noqa
from r_race import an_state
from playwright.sync_api import sync_playwright
R = {}
with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    page = ctx.new_page()
    unlock_if_locked(page); close_dialogs(page); dismiss_coach(page)
    ap0 = open_analysis_new_tab(ctx, page, "climate")
    ap0.wait_for_timeout(8000)
    page.bring_to_front()
    ap = open_analysis_new_tab(ctx, page, "election")
    ap.wait_for_timeout(8000)
    ap.click("#an-subtabs [data-tab=articles]")
    held = []
    def hold(route):
        if "query=climate" in route.request.url: held.append(route)
        else: route.continue_()
    ctx.route(re.compile(r".*/api/articles\?.*"), hold)
    ap.locator(".an-tab-label", has_text=re.compile(r"^\s*climate\s*$")).first.click()
    ap.wait_for_timeout(300)
    ap.locator(".an-tab-label", has_text=re.compile(r"^\s*election\s*$")).first.click()
    ap.wait_for_timeout(6000)
    ap.click("#an-subtabs [data-tab=articles]")
    R["before_release"] = an_state(ap)
    R["held"] = len(held)
    for r in held: r.continue_()
    ap.wait_for_timeout(4000)
    R["after_release"] = an_state(ap)
    shot(ap, "N-recheck-inwindow-race-en")
    b.close()
(OUT / "R-inwin.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
for k in ("before_release","after_release"):
    s=R[k]; print(k, s["query_label"], s["strip_active"], s["total"], s["xlang"][:60].replace("\n"," "), s["chips"][:3])
print("held", R["held"])
