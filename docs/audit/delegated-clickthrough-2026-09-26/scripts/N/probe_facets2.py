import json, sys, re
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright

def chips(ap):
    return [c for c in ap.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]

with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    page = ctx.new_page()
    page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(3000); close_dialogs(page)
    ap = open_analysis_new_tab(ctx, page, "climate")
    select_subtab(ap, "articles"); wait_art_total(ap)
    for attempt in range(4):
        page.bring_to_front()
        ep = open_analysis_new_tab(ctx, page, "election")
        seen = []
        ep.on("response", lambda r: seen.append((r.url.split('?')[1][:40], r.status)) if "corpus-source-language-facets" in r.url else None)
        select_subtab(ep, "articles")
        tot = wait_art_total(ep)
        c0 = chips(ep)
        ep.wait_for_timeout(4000)
        c1 = chips(ep)
        active = ep.evaluate("() => { const b=document.querySelector('.an-tab.active, #an-tabs .active'); return b && b.innerText.trim().slice(0,30); }")
        print(attempt, "total", tot, "chips@total", c0, "chips+4s", c1, "active", active, "facet responses", seen)
        ep.screenshot(path=f"/tmp/claude-0/walk/N/shots/probe-election-{attempt}.png")
        ep.close()
    b.close()
