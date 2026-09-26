"""Row I walk, I13(a): press Verify while a single-backup import is in stage 1."""
import json, time
from playwright.sync_api import sync_playwright
from common import *

SRC = f"{W}/backup5b/202609261809_OpenOmniscience_Backup"
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
    page.click("#ux-imp-run")
    t0 = time.time(); pressed = None; samples = []
    while time.time() - t0 < 45:
        s = snap(page); s["dt"] = round(time.time() - t0, 2)
        try:
            qa = api("/api/backup/import-queue/status")
            s["api"] = {"state": qa.get("state"), "items": [(i.get("state"), i.get("stage")) for i in qa.get("items", [])],
                        "stages": [(r.get("key"), r.get("state")) for r in qa.get("stages", [])]}
            vs = api("/api/backup/v2/volumes/status"); s["vol"] = {k: vs.get(k) for k in ("state", "mode", "phase")}
        except Exception as e:
            s["api_err"] = str(e)
        samples.append(s)
        rows = s.get("rows") or []
        if pressed is None and rows and "Running" in rows[0]["text"] and "stage 1 of 4" in rows[0]["text"]:
            page.click("#ux-import button[onclick='_uxImVerify(this)']")
            pressed = time.time() - t0
            ev("I13a_verify_pressed", dt=round(pressed, 2), row=rows[0]["text"])
            page.wait_for_timeout(700)
            page.screenshot(path=f"{SHOTS}/I-I13a-verify-pressed-en.png")
        if pressed is not None and time.time() - t0 > pressed + 30:
            break
        page.wait_for_timeout(200)
    with open(f"{W}/i13a_samples.jsonl", "w") as f:
        for x in samples:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    page.screenshot(path=f"{SHOTS}/I-I13a-after30s-en.png")
    ev("I13a_end", last=samples[-1])
    close_import(page); page.wait_for_timeout(1000)
    open_import(page); page.wait_for_timeout(1500)
    ev("I13a_reopen", **snap(page))
    page.screenshot(path=f"{SHOTS}/I-I13a-reopen-en.png")
    close_import(page)
    br.close()
