"""P5's last part in folder A: quit with the power icon, (re)start is done by the shell, then unlock."""
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import EXE, PASS, TOAST_INIT, Rec, close_guide, dismiss_coach, plane_filled, save, shot, text, tip, wstate  # noqa: E402

BASE = "http://127.0.0.1:8838"
mode = sys.argv[1]
R = {}
rec = Rec("A-" + mode)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking", "--disable-component-update"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    ctx.add_init_script(TOAST_INIT)
    pg = ctx.new_page()
    rec.attach(pg, dialog_policy="accept")
    if mode == "quit":
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)
        close_guide(pg)
        dismiss_coach(pg)
        pg.click("#app-shutdown")
        pg.wait_for_timeout(3000)
        R["overlay_text"] = pg.evaluate("() => document.body.innerText.slice(-400)")
        shot(pg, "P5-shutdown-en")
    else:
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_timeout(1500)
        R["landed"] = pg.url
        pg.wait_for_selector("#pw", timeout=20000)
        pg.fill("#pw", PASS)
        pg.click("#btn-unlock")
        pg.wait_for_url("**/#home", timeout=90000)
        R["after_unlock_url"] = pg.url
        pg.wait_for_timeout(3500)
        R["dialogs_open"] = pg.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)")
        close_guide(pg)
        dismiss_coach(pg)
        R["plane_filled"] = plane_filled(pg)
        R["network"] = pg.evaluate("() => fetch('/api/system/network').then(r => r.json())")
        R["w"] = wstate(pg)
        R["w_tip"] = tip(pg, "#wiki-toggle")
        R["sched_status_wiki"] = pg.evaluate("() => fetch('/api/scheduler/status').then(r => r.json()).then(s => s.wiki_lane)")
        shot(pg, "P5-after-restart-en", clip_sel="header")
    R["errors"] = rec.dump()
    save(f"restart_a_{mode}.json", R)
    br.close()
