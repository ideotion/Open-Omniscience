"""Phase J (M11, part 2): after restart, the paused fold, the Continue confirm, final line, report."""
import json
import sys
import time

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa

BASE = "http://127.0.0.1:8827"
R = {}
DIALOGS = []


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message})
    d.accept()


JOBS_JS = """() => [...document.querySelectorAll('.job')].map(j => ({
    state: (j.querySelector('.pill')||{}).textContent, label: (j.querySelector('.label')||{}).textContent,
    buttons: [...j.querySelectorAll('button')].map(b=>b.textContent), text: j.innerText.replace(/\\s+/g,' ').slice(0,200)}))"""

with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page(); attach(page, "main")
    page.on("dialog", on_dialog)
    R["unlocked"] = unlock_if_needed(page, BASE)
    close_guide(page)
    R["status_api_after_restart"] = page.evaluate("async () => (await fetch('/api/insights/keyword-fold-job/status')).json()")
    R["jobs_api_after_restart"] = page.evaluate("async () => { const d = await (await fetch('/api/jobs')).json(); return (d.jobs||d||[]).filter ? (d.jobs||d).filter(j => /fold/i.test(j.kind||'') || /fold/i.test(j.label||'')) : d; }")
    with ctx.expect_page() as pi:
        page.click("#tm-open")
    tm = pi.value; attach(tm, "tasks")
    tm.wait_for_load_state(); tm.wait_for_timeout(2500)
    R["tm_after_restart"] = [j for j in tm.evaluate(JOBS_JS) if j["label"] and "fold" in j["label"].lower()]
    R["tm_all_after_restart"] = tm.evaluate(JOBS_JS)[:10]
    tm.screenshot(path=log_path("M-M11-taskmanager-paused-en.png"))
    page.bring_to_front()
    page.click(".sb-foot button.secondary"); page.wait_for_timeout(500); dismiss_coach(page)
    page.click("#set-subtabs [data-tab=advanced]"); page.wait_for_timeout(600)
    open_adv(page, "diagnostics")
    page.locator("#kw-fold-btn").scroll_into_view_if_needed()
    page.click("#kw-fold-btn")
    t0 = time.time(); last = None; seq = []; tmrows = []
    while time.time() - t0 < 180:
        s = page.inner_text("#kw-fold-status")
        if s != last:
            seq.append([round(time.time() - t0, 2), s]); last = s
        jobs = [j for j in tm.evaluate(JOBS_JS) if j["label"] and ("fold" in j["label"].lower() or "language" in j["label"].lower())]
        if jobs and (not tmrows or tmrows[-1][1] != jobs):
            tmrows.append([round(time.time() - t0, 2), jobs])
        dis = page.evaluate("() => document.getElementById('kw-fold-btn').disabled")
        if not dis and time.time() - t0 > 2:
            break
        page.wait_for_timeout(300)
    R["continue_dialogs"] = DIALOGS
    R["status_sequence"] = seq
    R["tm_rows_during"] = tmrows
    R["final_line"] = page.inner_text("#kw-fold-status")
    shot(page, "M-M11-final-line-en.png", selector="#kw-fold-status >> xpath=..")
    with ctx.expect_page() as pi:
        page.click("#kw-fold-report")
    rp = pi.value; rp.wait_for_load_state(); rp.wait_for_timeout(800)
    txt = rp.inner_text("body")
    rp.screenshot(path=log_path("M-M11-report-en.png"))
    rp.close()
    try:
        rep = json.loads(txt)
    except Exception:
        rep = {"_raw": txt[:1500]}
    with open(log_path("keyword_fold_report-2026-09-26.json"), "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    R["report_keys"] = list(rep.keys())
    b.close()

with open(log_path("walk_j.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_j_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:7000])
