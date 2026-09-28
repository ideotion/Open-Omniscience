import sys, json, re
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright
R = {}
with sync_playwright() as p:
    b = launch(p); ctx = b.new_context(viewport={"width": 1440, "height": 950}); page = ctx.new_page()
    page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(3000); close_dialogs(page); dismiss_coach(page)
    ap = open_analysis_new_tab(ctx, page, "climate")
    ensure_term(ap, "climate", "en", "misc")
    ap.click("#an-xlang button[onclick='_anSetExpand(false)']"); ap.wait_for_timeout(3000)
    R["literal_total"] = wait_art_total(ap)
    ap.click("#an-subtabs [data-tab=mindmap]"); ap.wait_for_timeout(2500)
    R["mm_buttons_literal"] = ap.eval_on_selector_all("#an-mindmap button", "e=>e.map(b=>b.innerText.trim())")
    cb = ap.locator("#an-mindmap button[onclick*='concept:true']")
    if cb.count():
        cb.first.click(); ap.wait_for_timeout(2500)
        R["concept_texts_literal"] = ap.eval_on_selector_all("#an-mindmap svg text", "e=>e.map(x=>x.textContent.trim())")
        shot(ap, "N-N7-concept-literal-en")
    ap.click("#an-subtabs [data-tab=articles]"); ap.wait_for_timeout(1500)
    ap.click("#an-xlang button[onclick='_anSetExpand(true)']"); ap.wait_for_timeout(2500)
    ap.close()
    page.bring_to_front()
    set_lang(page, "fr"); dismiss_coach(page)
    open_palette_type(page, "climat")
    rows = page.query_selector_all(".pal-item")
    for r in rows:
        t = r.inner_text().strip()
        if "“climat”" in t and "↗" not in t:
            R["boolean_row_fr"] = t; r.click(); break
    page.wait_for_function("() => /\\d/.test((document.getElementById('search-meta')||{}).textContent||'')", timeout=30000)
    page.wait_for_timeout(800)
    R["search_meta_fr"] = text(page, "#search-meta")
    R["search_block_fr"] = page.evaluate("() => !!document.querySelector('#tab-search #an-xlang, #tab-search .xlang')")
    shot(page, "N-N11-search-fr")
    set_lang(page, "en")
    b.close()
print(json.dumps(R, ensure_ascii=False, indent=1))
(OUT / "R-misc.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
