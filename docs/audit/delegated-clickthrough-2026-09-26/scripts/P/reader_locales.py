import sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import EXE, Rec, close_guide, dismiss_coach, save, shot, switch_lang, junk_in
BASE = "http://127.0.0.1:8839"
URL = BASE + "/api/articles/448/view"
R = {}
rec = Rec("reader-loc")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-background-networking", "--disable-component-update"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page(); rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded"); pg.wait_for_timeout(3500); close_guide(pg); dismiss_coach(pg)
    rd = ctx.new_page(); rec.attach(rd)
    rd.goto(URL, wait_until="domcontentloaded"); rd.wait_for_timeout(2000)
    for lg in ["ar", "zh", "fr"]:
        switch_lang(pg, lg, rec)
        rd.reload(wait_until="domcontentloaded"); rd.wait_for_timeout(2500)
        R[lg] = rd.evaluate("""() => { const l = document.querySelector('.licence');
          return {html_lang: document.documentElement.lang, dir: document.documentElement.dir, body_dir: getComputedStyle(document.body).direction,
                  text: l ? l.innerText : null, links: l ? [...l.querySelectorAll('a')].map(a => a.innerText + ' | ' + a.className) : []}; }""")
        R[lg]["junk"] = junk_in(R[lg]["text"])
        if rd.locator(".licence").count():
            rd.locator(".licence").scroll_into_view_if_needed()
            shot(rd, f"P11-reader-licence-{lg}", clip_sel=".licence")
        # confirm text language on click, then cancel
        n0 = len(rec.dialogs)
        rd.locator(".licence a.ext").nth(1).click(); rd.wait_for_timeout(800)
        R[lg]["confirm"] = rec.dialogs[n0:]
    R["errors"] = rec.dump()
    save("reader_locales.json", R)
    br.close()
