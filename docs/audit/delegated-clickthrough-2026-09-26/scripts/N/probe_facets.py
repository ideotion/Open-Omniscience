import json, sys, re
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    page = ctx.new_page()
    reqs = []
    ctx.on("request", lambda r: reqs.append(r.url) if "facets" in r.url or "/api/articles" in r.url else None)
    page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(3000); close_dialogs(page)
    for term in ["climate", "election"]:
        ap = open_analysis_new_tab(ctx, page, term)
        select_subtab(ap, "articles")
        tot = wait_art_total(ap)
        seq = []
        for i in range(8):
            chips = [c for c in ap.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]
            seq.append(chips)
            ap.wait_for_timeout(1000)
        tabs = ap.evaluate("() => { try { return JSON.parse(localStorage.getItem('oo.an.tabs.v1')||'null'); } catch(e) { return String(e); } }")
        print(term, "total", tot, "chips over time", seq[0], seq[-1])
        print("  tabs in workspace:", [ (t.get('label') or t.get('title') or t.get('q'), t.get('id')) for t in (tabs or {}).get('tabs', tabs if isinstance(tabs, list) else [])] if tabs else tabs)
        print("  tab strip:", ap.eval_on_selector_all("#an-tabs button, .an-tab", "e=>e.map(x=>x.innerText.trim().slice(0,30))"))
        ap.close()
    print("\n".join(u for u in reqs if "facets" in u))
    r = page.evaluate("async () => (await fetch('/api/insights/corpus-source-language-facets?query=election')).json()")
    print("API literal election facets:", r.get("languages"))
    b.close()
