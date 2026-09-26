"""Row I RECHECK, run B/C: Verify during a running import (D8); graceful restart after a
finished run (D10 row 3, D3/Q205 row 4 while the re-index auto-resumes); SIGKILL during
stage 3 (D4)."""
import json, os, signal, sys, threading, time, urllib.request
from playwright.sync_api import sync_playwright
from common import *

SH = f"{W}/shots"
BB = f"{W}/backupB"
BC = f"{W}/backupC"
PHASES = sys.argv[1:] or ["B", "R", "C"]


def start_import(page, folder):
    open_import(page)
    page.fill("#ux-imp-src", folder)
    page.click("#ux-import button[onclick='_uxImScan(this)']")
    page.wait_for_function("() => /What do you want|Nothing importable|Scan failed/.test(document.getElementById('ux-imp-status').innerText)", timeout=30000)
    boxes = page.evaluate("() => Array.from(document.querySelectorAll('#ux-imp-checklist input[type=checkbox]')).map(b => [b.id, b.checked])")
    for bid, chk in boxes:
        if bid != "ux-i-corpus" and chk: page.uncheck("#" + bid)
    page.fill("#ux-imp-pass", BPASS)
    page.click("#ux-imp-run")


def relaunch_and_unlock(page):
    start_server()
    unlock_if_needed(page)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = br.new_context(viewport={"width": 1440, "height": 950}, locale="en-US")
    page = ctx.new_page(); wire(page, "app"); page.on("dialog", on_dialog)
    DIALOG_MODE["accept"].add("Another job is writing")
    verify_resp = []
    page.on("response", lambda r: verify_resp.append((round(time.time(), 2), r.request.method, r.url.split("8816")[-1], r.status))
            if "/v2/volumes/" in r.url else None)
    unlock_if_needed(page)
    goto_data(page)

    if "B" in PHASES:
        ev("B_rx_before", rx={k: v for k, v in api("/api/backup/reindex-backlog/resume/status").items() if k in ("state", "done", "total")})
        start_import(page, BB)
        t0 = time.time()
        page.wait_for_function("() => /Running/.test((document.getElementById('ux-imp-queue-rows')||{}).innerText||'')", timeout=60000)
        s = snap(page); ev("D8_running_before_verify", dt=round(time.time() - t0, 2), rows=[r["text"] for r in s["rows"]], note=s["note"])
        page.click("#ux-import button[onclick='_uxImVerify(this)']")
        tv = time.time()
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{SH}/D8-verify-pressed-en.png")
        samples = []
        while time.time() - tv < 32:
            s = snap(page); q = api("/api/backup/import-queue/status")
            samples.append({"dt": round(time.time() - tv, 1), "status": s["status"], "progress": s["progress"], "note": s["note"],
                            "rows": [r["text"] for r in s["rows"]], "summary": s["summary"][:200], "bars": s["bars"],
                            "api_q": q.get("state"), "api_items": [i.get("state") for i in q.get("items", [])]})
            page.wait_for_timeout(1000)
        with open(f"{W}/d8_samples.jsonl", "w") as f:
            for x in samples: f.write(json.dumps(x, ensure_ascii=False) + "\n")
        ev("D8_first", **samples[0]); ev("D8_mid", **samples[len(samples) // 2]); ev("D8_last", **samples[-1])
        ev("D8_verify_http", resp=verify_resp[:12])
        page.screenshot(path=f"{SH}/D8-after30s-en.png")
        close_import(page)
        # let the post-run drain restart
        for _ in range(30):
            if api("/api/backup/import-queue/status").get("state") != "running": break
            time.sleep(1)
        ev("B_done", q=api("/api/backup/import-queue/status").get("state"))

    if "R" in PHASES:
        # graceful restart while the re-index drain is running
        rx = api("/api/backup/reindex-backlog/resume/status")
        ev("R_before_restart", rx_state=rx.get("state"), done=rx.get("done"), total=rx.get("total"),
           pending=(rx.get("backlog") or {}).get("articles_pending"), q=api("/api/backup/import-queue/status").get("state"))
        pid = listener_pid()
        os.kill(int(pid), signal.SIGTERM)
        for _ in range(60):
            if not listener_pid(): break
            time.sleep(0.5)
        ev("R_stopped", pid=pid, still=listener_pid())
        time.sleep(1)
        relaunch_and_unlock(page)
        goto_data(page)
        open_import(page)
        s0 = snap(page)
        rx = api("/api/backup/reindex-backlog/resume/status")
        ev("R_dialog_after_restart", stages=[x["text"] for x in s0["stages"]], statements=s0["statements"], note=s0["note"],
           rows=[r["text"] for r in s0["rows"]], last=s0["last"], rx_state=rx.get("state"), rx_done=rx.get("done"), rx_total=rx.get("total"))
        page.screenshot(path=f"{SH}/D10-after-restart-en.png")
        page.wait_for_timeout(7000)
        s7 = snap(page); rx = api("/api/backup/reindex-backlog/resume/status")
        ev("R_dialog_after_restart_7s", row3=[x["text"] for x in s7["stages"] if x["key"] == "search_index"],
           row4=[x["text"] for x in s7["stages"] if x["key"] == "reindex"], stmt=s7["statements"],
           rx_state=rx.get("state"), rx_done=rx.get("done"), rx_total=rx.get("total"))
        close_import(page)

    if "C" in PHASES:
        killed = {}
        pid = listener_pid()
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def watcher():
            t_end = time.time() + 300
            seen_running = False
            while time.time() < t_end:
                try:
                    with op.open(BASE + "/api/backup/import-queue/status", timeout=5) as r:
                        q = json.loads(r.read())
                except Exception:
                    time.sleep(0.02); continue
                if q.get("state") == "running":
                    seen_running = True
                stg = {r.get("key"): r.get("state") for r in q.get("stages", [])}
                if seen_running and q.get("state") == "running" and stg.get("search_index") == "running":
                    os.kill(int(pid), signal.SIGKILL)
                    killed.update(t=time.time(), items=[(i.get("label"), i.get("state")) for i in q.get("items", [])],
                                  stages=stg, live=q.get("live"))
                    return
                if seen_running and q.get("state") != "running":
                    killed.update(missed=True, final=q.get("state")); return
                time.sleep(0.01)

        th = threading.Thread(target=watcher, daemon=True); th.start()
        start_import(page, BC)
        th.join(timeout=320)
        ev("D4_kill", **killed)
        try:
            page.screenshot(path=f"{SH}/D4-at-kill-en.png")
        except Exception:
            pass
        time.sleep(2)
        ev("D4_listener_after_kill", pid=listener_pid())
        relaunch_and_unlock(page)
        goto_data(page)
        open_import(page)
        s0 = snap(page)
        q = api("/api/backup/import-queue/status"); rx = api("/api/backup/reindex-backlog/resume/status")
        reps = api("/api/backup/import-reports")
        ev("D4_dialog_after_relaunch", note=s0["note"], stages=[x["text"] for x in s0["stages"]], statements=s0["statements"],
           rows=[r["text"] for r in s0["rows"]], last=s0["last"])
        ev("D4_api_after_relaunch", q_state=q.get("state"), items=[(i.get("label"), i.get("state")) for i in q.get("items", [])],
           rx_state=rx.get("state"), rx_done=rx.get("done"), rx_total=rx.get("total"),
           reports=[(r.get("filename"), r.get("articles"), r.get("outcome")) for r in reps.get("reports", [])][:4])
        page.screenshot(path=f"{SH}/D4-after-relaunch-en.png")
        close_import(page)
    br.close()
