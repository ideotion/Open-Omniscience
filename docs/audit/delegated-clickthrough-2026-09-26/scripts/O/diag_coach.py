from playwright.sync_api import sync_playwright
from lib import Rec, close_guide, settings_sub, switch_lang, shot, nav
import json
rec = Rec(); out = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox","--disable-background-networking","--no-proxy-server"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.watch(pg, "diag")
    pg.goto("http://127.0.0.1:8834/", wait_until="networkidle"); pg.wait_for_timeout(1500); close_guide(pg)
    for loc in ("en", "fr"):
        switch_lang(pg, loc, rec)
        nav(pg, "settings"); pg.wait_for_timeout(4000)
        out[loc] = pg.evaluate("""() => { const c = document.getElementById('net-coach'); const b = document.querySelector("#set-subtabs button[data-tab='advanced']");
          const cr = c.getBoundingClientRect(), br = b.getBoundingClientRect();
          const hit = document.elementFromPoint(br.left + br.width/2, br.top + br.height/2);
          return {coach_class: c.className, coach: [cr.left, cr.top, cr.right, cr.bottom].map(Math.round),
                  adv: [br.left, br.top, br.right, br.bottom].map(Math.round), hit_is_adv: hit === b || b.contains(hit),
                  hit: hit && (hit.id || hit.className)}; }""")
        shot(pg, f"O-diag-coach-over-advanced-{loc}.png")
    print(json.dumps(out, indent=1)); br.close()
