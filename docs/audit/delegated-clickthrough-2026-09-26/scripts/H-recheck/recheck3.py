"""Row H recheck, part 3: the off-row Home strip in fr -- does it EVER translate, and why not?"""
import json
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8812"
OUT = "/tmp/claude-0/walk/H-recheck"
rep = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector("#net-toggle", timeout=60000)
    pg.wait_for_timeout(2500)
    if pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
        pg.click("#gw-close"); pg.wait_for_timeout(400)
    loc = pg.locator("#net-coach-dismiss")
    if loc.count() and loc.is_visible():
        loc.click(); pg.wait_for_timeout(300)
    rep["lang0"] = pg.evaluate("() => document.documentElement.lang")
    if rep["lang0"] != "fr":
        pg.click("#lang-switch"); pg.click("#lang-menu [data-lang='fr']")
        pg.wait_for_function("() => document.documentElement.lang === 'fr'", timeout=8000)
    t0 = time.time()
    rep["t_label_now"] = pg.evaluate("() => [OOI18N.t('Keywords'), homeStatLabel('keywords'), homeStatLabel('sources_qualified'), OOI18N.t('Automatic collection')]")
    rep["active_tab"] = pg.evaluate("() => location.hash")
    samples = []
    for i in range(5):
        samples.append({"t_s": round(time.time() - t0, 1), "strip": pg.inner_text("#home-stats").replace("\n", " | ")[:200],
                        "status": pg.inner_text("#home-status").replace("\n", " ")[:80] if pg.locator("#home-status").count() else None})
        pg.wait_for_timeout(8000)
    rep["samples"] = samples
    pg.screenshot(path=f"{OUT}/H-fr-home-strip-after-40s.png", clip={"x": 250, "y": 70, "width": 1190, "height": 150})
    # back to en
    pg.click("#lang-switch"); pg.click("#lang-menu [data-lang='en']")
    pg.wait_for_function("() => document.documentElement.lang === 'en'", timeout=8000)
    br.close()
json.dump(rep, open(f"{OUT}/recheck3.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1))
