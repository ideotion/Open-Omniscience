"""Confirm with Playwright's own hit-test (trial clicks: actionability only, no state change) which
top-bar controls the offline coach intercepts when it is first shown in Arabic."""
import json
from playwright.sync_api import sync_playwright
from recheck import A, ARGS, PASS, COACH_STATE, unlock, close_guide, switch_lang, shot, rec

R = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=ARGS)
    for vw in (1440, 1024):
        ctx = br.new_context(viewport={"width": vw, "height": 950}); pg = ctx.new_page(); rec.watch(pg, f"trial-{vw}")
        unlock(pg, A, PASS); close_guide(pg)
        switch_lang(pg, "ar", rec)
        pg.reload(wait_until="networkidle")
        pg.wait_for_function("() => document.getElementById('net-coach').classList.contains('show')", timeout=15000)
        pg.wait_for_timeout(800)
        o = R[vw] = {"coach": pg.evaluate(COACH_STATE)}
        for sel in ("#tm-open", "#rate-toggle", "#wiki-toggle", "#net-toggle", "#lang-switch", "#app-shutdown"):
            try:
                pg.click(sel, trial=True, timeout=2000)
                o[sel] = "reachable"
            except Exception as exc:
                m = str(exc)
                o[sel] = "INTERCEPTED by coach" if "coach" in m else ("timeout: " + m[:200])
        # a REAL click on the task-manager icon: it must open the task manager tab
        try:
            with ctx.expect_page(timeout=4000) as newp:
                pg.click("#tm-open", timeout=3000)
            newp.value.close(); o["tm_open_real_click"] = "opened the task manager"
        except Exception as exc:
            o["tm_open_real_click"] = "did not open: " + str(exc)[:160]
        shot(pg, f"Orc-coach-covers-topbar-{vw}-ar.png")
        # the coach's own dismiss restores the cluster
        pg.click("#net-coach-dismiss"); pg.wait_for_timeout(500)
        try:
            pg.click("#tm-open", trial=True, timeout=2000); o["tm_open_after_not_now"] = "reachable"
        except Exception as exc:
            o["tm_open_after_not_now"] = str(exc)[:120]
        ctx.close()
    br.close()
R["page_errors"], R["http"] = rec.page_errors, rec.http
json.dump(R, open("raw-rtl-trial.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
