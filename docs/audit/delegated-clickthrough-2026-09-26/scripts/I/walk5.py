"""Row I walk, I13(b): a stop during stage 3 (after every backup reads Done and both check
lines are due), using the step's own harsher variant (SIGKILL) because a sub-second stage 3
cannot be reached through a modal dialog + power button + confirm. Then relaunch and look."""
import json, os, signal, threading, time
from playwright.sync_api import sync_playwright
from common import *

SRC = f"{W}/backup6/202609261817_OpenOmniscience_Backup"
killed = {}


def watcher(pid):
    t0 = time.time()
    while time.time() - t0 < 120:
        try:
            qa = api("/api/backup/import-queue/status")
        except Exception:
            time.sleep(0.01); continue
        items = qa.get("items", [])
        st3 = [r for r in qa.get("stages", []) if r.get("key") == "search_index"]
        if items and all(i.get("state") in ("done", "skipped") for i in items) and qa.get("state") == "running":
            os.kill(int(pid), signal.SIGKILL)
            killed.update(dt=round(time.time() - t0, 3), stage3=st3, items=[(i.get("label"), i.get("state")) for i in items],
                          live=qa.get("live"))
            return
        if qa.get("state") in ("done", "error", "stopped"):
            killed.update(missed=True, state=qa.get("state")); return
        time.sleep(0.01)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = br.new_context(viewport={"width": 1440, "height": 950}, locale="en-US")
    page = ctx.new_page(); wire(page, "app"); page.on("dialog", on_dialog)
    unlock_if_needed(page)
    goto_data(page); open_import(page)
    page.fill("#ux-imp-src", SRC)
    page.click("#ux-import button[onclick='_uxImScan(this)']")
    page.wait_for_function("() => /What do you want/.test(document.getElementById('ux-imp-status').innerText)", timeout=30000)
    page.fill("#ux-imp-pass", BPASS)
    pid = listener_pid()
    th = threading.Thread(target=watcher, args=(pid,), daemon=True)
    page.click("#ux-imp-run"); th.start()
    seen = []
    t0 = time.time()
    while th.is_alive() and time.time() - t0 < 120:
        try:
            s = snap(page); s["dt"] = round(time.time() - t0, 2); seen.append(s)
        except Exception:
            pass
        page.wait_for_timeout(100)
    th.join(5)
    ev("I13b_kill", pid=pid, **killed)
    page.wait_for_timeout(1500)
    try:
        page.screenshot(path=f"{SHOTS}/I-I13b-at-kill-en.png")
        ev("I13b_last_dialog_before_kill", **(seen[-1] if seen else {}))
    except Exception as e:
        ev("I13b_shot_err", err=str(e))
    ok_lines_seen = [x["dt"] for x in seen if (x.get("statements") or "").startswith("✓ The import files")]
    stage3_running_seen = [x["dt"] for x in seen if any(r["key"] == "search_index" and "running" in r["text"] for r in x.get("stages") or [])]
    ev("I13b_ui_seen", ok_lines_dt=ok_lines_seen[:5], stage3_running_dt=stage3_running_seen[:5])
    br.close()

time.sleep(2)
start_server()
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = br.new_context(viewport={"width": 1440, "height": 950}, locale="en-US")
    page = ctx.new_page(); wire(page, "app"); page.on("dialog", on_dialog)
    unlock_if_needed(page)
    t_unlock = time.time()
    goto_data(page)
    ev("I13b_history_after", text=page.inner_text("#imp-history"))
    open_import(page); page.wait_for_timeout(1500)
    s = snap(page); ev("I13b_dialog_after_relaunch", **s)
    page.screenshot(path=f"{SHOTS}/I-I13b-after-relaunch-en.png")
    close_import(page)
    rx = None
    for i in range(30):
        rx = api("/api/backup/reindex-backlog/resume/status")
        if rx.get("state") == "running" or (rx.get("backlog") or {}).get("articles_pending") == 0:
            break
        time.sleep(2)
    ev("I13b_reindex_after_relaunch", s_after_unlock=round(time.time() - t_unlock, 1),
       rx={k: rx.get(k) for k in ("state", "done", "total")}, pending=(rx.get("backlog") or {}).get("articles_pending"),
       queue=api("/api/backup/import-queue/status").get("state"))
    br.close()
