import sys, json
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = launch(p); ctx = b.new_context(viewport={"width": 375, "height": 800}); page = ctx.new_page()
    page.goto(URL + "/", wait_until="domcontentloaded"); page.wait_for_timeout(3000); close_dialogs(page); dismiss_coach(page)
    page.click("#hamburger"); page.wait_for_timeout(600); page.click("#navGroups button[data-tab=insights]")
    page.wait_for_selector("#ins-subtabs button[data-tab=trends]", state="visible", timeout=30000)
    print("explore overflow", page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"))
    for tab in ["trends", "watches"]:
        page.click(f"#ins-subtabs button[data-tab={tab}]"); page.wait_for_timeout(3000)
        ov = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        wide = page.evaluate("""() => { const vw=document.documentElement.clientWidth; const out=[];
          for (const e of document.querySelectorAll('#tab-insights *')) { const r=e.getBoundingClientRect(); if (r.right > vw+2 && r.width>0) out.push([e.tagName, e.id, (e.className||'').toString().slice(0,30), Math.round(r.left), Math.round(r.right), e.textContent.trim().slice(0,40)]); }
          return out.slice(0,12); }""")
        print(tab, "overflow", ov); [print("  ", w) for w in wide]
        page.screenshot(path=f"/tmp/claude-0/walk/N/shots/N-375-insights-{tab}-en.png")
    b.close()
