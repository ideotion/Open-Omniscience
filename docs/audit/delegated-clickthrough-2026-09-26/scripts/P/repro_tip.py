"""Isolate the stale-hover defect: fresh reload, then the gauge (#rate-toggle) as a second control."""
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import EXE, TOAST_INIT, Rec, attr, close_guide, dismiss_coach, save, tip, wstate  # noqa: E402

BASE = "http://127.0.0.1:8838"
R = {}
rec = Rec("A-repro")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking", "--disable-component-update"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    ctx.add_init_script(TOAST_INIT)
    pg = ctx.new_page()
    rec.attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_timeout(3000)
    close_guide(pg)
    dismiss_coach(pg)
    R["W_after_reload"] = wstate(pg)
    R["W_tip_after_reload"] = tip(pg, "#wiki-toggle")
    # The gauge: a loopback setting, no consent involved.
    R["rate_title_0"] = attr(pg, "#rate-toggle", "title")
    R["rate_cls_0"] = attr(pg, "#rate-toggle", "class")
    R["rate_tip_0"] = tip(pg, "#rate-toggle")
    pg.click("#rate-toggle")
    pg.wait_for_timeout(1500)
    R["rate_cls_1"] = attr(pg, "#rate-toggle", "class")
    R["rate_title_attr_1_while_hovered"] = attr(pg, "#rate-toggle", "title")
    R["rate_tip_1_rehover"] = tip(pg, "#rate-toggle")
    R["rate_cfg_1"] = pg.evaluate("() => fetch('/api/scheduler/config').then(r => r.json()).then(c => c.governor_mode || c.rate_mode || null)")
    # restore the gauge
    pg.click("#rate-toggle")
    pg.wait_for_timeout(1500)
    R["rate_cls_2"] = attr(pg, "#rate-toggle", "class")
    R["rate_tip_2_rehover"] = tip(pg, "#rate-toggle")
    # after a reload, fresh titles again
    pg.reload(wait_until="domcontentloaded")
    pg.wait_for_timeout(3000)
    close_guide(pg)
    R["rate_tip_after_reload"] = tip(pg, "#rate-toggle")
    R["errors"] = rec.dump()
    save("repro_tip.json", R)
    br.close()
