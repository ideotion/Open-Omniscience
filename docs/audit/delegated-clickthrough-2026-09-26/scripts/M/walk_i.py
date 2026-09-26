"""Phase I (M11, part 1): export backup on 8827, start the fold, watch /tasks, shut down mid-run."""
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


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page(); attach(page, "main")
    page.on("dialog", on_dialog)
    R["unlocked"] = unlock_if_needed(page, BASE)
    close_guide(page)
    # ---- backup via the app's own export ----
    dismiss_coach(page)
    page.click(".sb-foot button.secondary"); page.wait_for_timeout(600); dismiss_coach(page)
    page.click("#set-subtabs [data-tab=data]"); page.wait_for_timeout(1200)
    page.click("button:has-text('Export / Back up…')")
    page.wait_for_selector("#ux-export[open]")
    page.wait_for_timeout(2500)
    page.fill("#ux-dest", "/tmp/claude-0/walk/M/backup2")
    if page.locator("#ux-pass").is_visible():
        page.fill("#ux-pass", "backup-pass-2026")
    page.click("#ux-run")
    t0 = time.time(); last = None; seq = []
    while time.time() - t0 < 300:
        s = page.inner_text("#ux-progress")
        if s != last:
            seq.append([round(time.time() - t0, 1), s[:200]]); last = s
        if page.locator("#ux-summary").inner_text().strip() and not page.evaluate("() => document.getElementById('ux-run').disabled"):
            break
        page.wait_for_timeout(1000)
    R["backup_progress"] = seq[-6:]
    R["backup_summary"] = page.inner_text("#ux-summary")[:800]
    shot(page, "M-M11-backup-en.png", selector="#ux-export")
    page.click("#ux-export button.secondary:has-text('Close')")
    page.wait_for_timeout(500)
    # ---- open the task manager (separate tab) ----
    with ctx.expect_page() as pi:
        page.click("#tm-open")
    tm = pi.value; attach(tm, "tasks")
    tm.wait_for_load_state(); tm.wait_for_timeout(1500)
    R["tm_url"] = tm.url
    # ---- start the fold ----
    page.click(".sb-foot button.secondary"); page.wait_for_timeout(500); dismiss_coach(page)
    page.click("#set-subtabs [data-tab=advanced]"); page.wait_for_timeout(600)
    open_adv(page, "diagnostics")
    page.locator("#kw-fold-btn").scroll_into_view_if_needed()
    page.click("#kw-fold-btn")
    rows = []
    t0 = time.time()
    shot_done = False
    shutdown_at = None
    while time.time() - t0 < 60:
        tm.wait_for_timeout(700)
        jobs = tm.evaluate("""() => [...document.querySelectorAll('.job')].map(j => ({
            state: (j.querySelector('.pill')||{}).textContent, label: (j.querySelector('.label')||{}).textContent,
            buttons: [...j.querySelectorAll('button')].map(b=>b.textContent), text: j.innerText.replace(/\\s+/g,' ').slice(0,200),
            group: (j.closest('section, .grp, details')||{}).querySelector ? ((j.closest('section, .grp, details').querySelector('h2,h3,summary')||{}).textContent||'') : ''}))""")
        fold = [j for j in jobs if j["label"] and ("fold" in j["label"].lower() or "keyword" in j["label"].lower() or "Setting each" in j["label"])]
        st = page.evaluate("async () => (await fetch('/api/insights/keyword-fold-job/status')).json()")
        rows.append({"t": round(time.time() - t0, 1), "fold_rows": fold, "api_done": st.get("keywords_done"), "api_total": st.get("keywords_total"), "api_state": st.get("state"), "phase": st.get("phase")})
        if fold and not shot_done:
            tm.screenshot(path=log_path("M-M11-taskmanager-fold-en.png")); shot_done = True
        if st.get("keywords_done", 0) and st.get("keywords_done") > 500 and st.get("state") == "running":
            shutdown_at = {"done": st.get("keywords_done"), "total": st.get("keywords_total")}
            break
    R["tm_rows"] = rows
    R["shutdown_at"] = shutdown_at
    R["status_line_before_shutdown"] = page.inner_text("#kw-fold-status")
    # ---- shut down with the top-bar power icon ----
    page.click("#app-shutdown")
    page.wait_for_timeout(3000)
    R["dialogs"] = DIALOGS
    shot(page, "M-M11-shutdown-en.png")
    b.close()

with open(log_path("walk_i.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_i_log.json")
print(json.dumps({k: v for k, v in R.items() if k != "tm_rows"}, indent=1, ensure_ascii=False)[:4000])
print(json.dumps(R["tm_rows"][:4], ensure_ascii=False)[:3000])
print(json.dumps(R["tm_rows"][-2:], ensure_ascii=False)[:2000])
