# Fresh page loaded AT 375 px (no 1440 render first): Commodities and Help horizontal scroll.
from playwright.sync_api import sync_playwright
from common import *
rec = Rec("probe375fresh")
WID = """() => { let best = null; document.querySelectorAll('body *').forEach(e => { if (!e.getClientRects().length) return;
    const b = e.getBoundingClientRect(); if (b.right > innerWidth + 1 && (!best || b.right > best.r)) best = {r: Math.round(b.right), tag: e.tagName, id: e.id, cls: String(e.className).slice(0,60), parent: e.parentElement ? (e.parentElement.id || e.parentElement.className) : '', text: (e.textContent||'').trim().slice(0,50)}; });
    return best; }"""
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
    for tab in ["markets", "help"]:
        ctx = br.new_context(viewport={"width": 375, "height": 812})
        pg = ctx.new_page(); rec.attach(pg)
        pg.goto("http://127.0.0.1:8850/", wait_until="domcontentloaded"); pg.wait_for_timeout(4000)
        close_unrelated_dialogs(pg)
        if tab == "help":
            pg.click("button.icon-btn[onclick=\"showTab('help')\"]")
        else:
            pg.click("#hamburger"); pg.wait_for_timeout(500)
            pg.click(f"#navGroups .nav-item[data-tab='{tab}']"); pg.wait_for_timeout(500)
            if pg.evaluate("() => document.body.classList.contains('nav-open')"):
                pg.click("#hamburger", force=True)
        pg.wait_for_timeout(3000)
        close_unrelated_dialogs(pg)
        rec.note(f"{tab}.hscroll", hscroll(pg))
        rec.note(f"{tab}.widest", pg.evaluate(WID))
        shot(pg, f"U-375-fresh-{tab}-en")
        pg.mouse.wheel(600, 0); pg.wait_for_timeout(300)
        rec.note(f"{tab}.scrollX_after_wheel", pg.evaluate("() => scrollX"))
        ctx.close()
    br.close()
rec.save()
