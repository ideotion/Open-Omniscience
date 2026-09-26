"""Phase A: unlock (encrypted), M1 + M2 (fold job, report)."""
import json
import sys
import time

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa

BASE = "http://127.0.0.1:8826"
R = {}
DIALOGS = []
MODE = {"accept": True}


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message, "accepted": MODE["accept"]})
    if MODE["accept"]:
        d.accept()
    else:
        d.dismiss()


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    R["unlocked_via_form"] = unlock_if_needed(page, BASE)
    R["url_after_unlock"] = page.url
    R["guide_open"] = page.evaluate("() => { const d=document.getElementById('guide-wizard'); return !!(d && d.open); }")
    shot(page, "M-M0-unlocked-en.png")
    close_guide(page)
    R["plane_fill"] = page.evaluate("() => { const s=document.querySelector('#net-toggle svg path, #net-toggle svg'); return s ? (s.getAttribute('fill')||'') : null; }")
    R["net_state"] = page.evaluate("async () => (await fetch('/api/system/network')).json()")
    open_settings_advanced(page)
    open_adv(page, "diagnostics")
    page.locator("#kw-fold-btn").scroll_into_view_if_needed()
    R["fold_btn_title"] = page.get_attribute("#kw-fold-btn", "title")
    R["fold_btn_text"] = page.inner_text("#kw-fold-btn")
    R["status_initial"] = page.inner_text("#kw-fold-status")
    # M1(a): report before any fold
    with ctx.expect_page() as pinfo:
        page.click("#kw-fold-report")
    rp = pinfo.value
    attach(rp, "report-tab-1")
    rp.wait_for_load_state()
    rp.wait_for_timeout(800)
    R["M1a_report_tab_url"] = rp.url
    R["M1a_report_tab_text"] = rp.inner_text("body")[:600]
    rp.screenshot(path=log_path("M-M1a-noreport-en.png"))
    rp.close()
    # M1(b): fold, capture the confirm
    MODE["accept"] = True
    page.click("#kw-fold-btn")
    seen = []
    t0 = time.time()
    last = None
    while time.time() - t0 < 180:
        s = page.inner_text("#kw-fold-status")
        if s != last:
            seen.append([round(time.time() - t0, 2), s])
            last = s
        dis = page.evaluate("() => document.getElementById('kw-fold-btn').disabled")
        if not dis and time.time() - t0 > 2 and s:
            break
        page.wait_for_timeout(250)
    R["M1_dialogs"] = list(DIALOGS)
    R["M1c_status_sequence"] = seen
    R["M1c_final"] = page.inner_text("#kw-fold-status")
    R["M1_status_api"] = page.evaluate("async () => (await fetch('/api/insights/keyword-fold-job/status')).json()")
    shot(page, "M-M1-foldline-en.png", selector="#kw-fold-status >> xpath=..")
    # M2: report now
    with ctx.expect_page() as pinfo:
        page.click("#kw-fold-report")
    rp = pinfo.value
    attach(rp, "report-tab-2")
    rp.wait_for_load_state()
    rp.wait_for_timeout(800)
    txt = rp.inner_text("body")
    rp.screenshot(path=log_path("M-M2-report-en.png"))
    rp.close()
    try:
        rep = json.loads(txt)
    except Exception:
        rep = {"_raw": txt[:2000]}
    with open(log_path("fold_report_first.json"), "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    R["M2_report_keys"] = list(rep.keys()) if isinstance(rep, dict) else None
    # second fold
    DIALOGS.clear()
    page.click("#kw-fold-btn")
    seen = []
    t0 = time.time()
    last = None
    while time.time() - t0 < 180:
        s = page.inner_text("#kw-fold-status")
        if s != last:
            seen.append([round(time.time() - t0, 2), s])
            last = s
        dis = page.evaluate("() => document.getElementById('kw-fold-btn').disabled")
        if not dis and time.time() - t0 > 2:
            break
        page.wait_for_timeout(250)
    R["M2_second_dialogs"] = list(DIALOGS)
    R["M2_second_sequence"] = seen
    R["M2_second_final"] = page.inner_text("#kw-fold-status")
    rep2 = page.evaluate("async () => (await fetch('/api/insights/keyword-fold-job/report')).json()")
    with open(log_path("fold_report_second.json"), "w") as f:
        json.dump(rep2, f, indent=1, ensure_ascii=False)
    shot(page, "M-M2-second-fold-en.png", selector="#kw-fold-status >> xpath=..")
    R["junk_diag"] = junk_in(page, "details.adv-sec[data-adv=diagnostics]")
    b.close()

with open(log_path("walk_a.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_a_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:5000])
