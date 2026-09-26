"""Row I walk, phase 1: first launch of the throwaway, I2, I3, I4-I8, and the I9 shutdown."""
import json, sys, time
from playwright.sync_api import sync_playwright
from common import *

B1 = f"{W}/backups/202609261755_OpenOmniscience_Backup"
PARENT = f"{W}/backups"

start_server()

MUT_JS = r"""() => {
  window.__mut = window.__mut || {};
  for (const id of ['ux-imp-stages', 'ux-imp-queue-rows']) {
    const host = document.getElementById(id);
    if (!host || host.__obs) continue;
    host.__obs = new MutationObserver((ms) => {
      for (const m of ms) {
        let n = m.target.nodeType === 1 ? m.target : m.target.parentElement;
        while (n && n !== host && !(n.getAttribute && n.getAttribute('data-row-key'))) n = n.parentElement;
        const k = (n && n !== host) ? n.getAttribute('data-row-key') : (id + ':host');
        window.__mut[k] = (window.__mut[k] || 0) + 1;
      }
    });
    host.__obs.observe(host, { childList: true, subtree: true, characterData: true, attributes: true });
  }
  return window.__mut;
}"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = br.new_context(viewport={"width": 1440, "height": 950}, locale="en-US")
    page = ctx.new_page(); wire(page, "app"); page.on("dialog", on_dialog)
    ctx.on("page", lambda pg: (wire(pg, "popup:" + pg.url), pg.on("dialog", on_dialog)))

    # ---- first launch: language -> legal -> passphrase ----
    page.goto(BASE + "/", wait_until="domcontentloaded"); page.wait_for_timeout(2000)
    ev("first_url", url=page.url)
    page.wait_for_selector("#view-language:not(.hidden)", timeout=20000)
    page.click("#lang-list button[lang=en]")
    page.wait_for_selector("#view-legal:not(.hidden)", timeout=20000)
    page.check("#lg-check"); page.click("#lg-accept")
    page.wait_for_selector("#view-create:not(.hidden)", timeout=20000)
    page.fill("#pw1", PASS); page.fill("#pw2", PASS); page.click("#btn-create")
    for _ in range(60):
        page.wait_for_timeout(1000)
        if "/unlock" not in page.url:
            break
        if page.is_visible("#view-open"):
            page.click("#view-open button"); page.wait_for_timeout(2000); break
    page.wait_for_timeout(3000)
    ev("after_create", url=page.url, lock=api("/api/system/lock-state"))
    close_wizard(page)

    # ---- I2 ----
    goto_data(page)
    k_val = page.input_value("#set-checkpoint-k")
    k_title = page.get_attribute("#set-checkpoint-k", "title")
    page.hover("#set-checkpoint-k"); page.wait_for_timeout(900)
    tip = page.evaluate("() => { const t = document.getElementById('oo-tip'); return t ? {text: t.innerText, vis: getComputedStyle(t).display !== 'none' && t.getBoundingClientRect().width > 0} : null; }")
    hint = page.evaluate("() => { const e = document.getElementById('set-checkpoint-k').closest('.row').nextElementSibling; return e ? e.innerText : null; }")
    hist = page.inner_text("#imp-history")
    ev("I2_settings", k=k_val, title=k_title, tip=tip, hint=hint, history=hist)
    page.locator("#imp-history").scroll_into_view_if_needed()
    page.screenshot(path=f"{SHOTS}/I-I2-settings-en.png")
    open_import(page)
    s = snap(page); ev("I2_dialog", **s)
    page.screenshot(path=f"{SHOTS}/I-I2-dialog-en.png")
    close_import(page)

    # ---- I3 verify ----
    open_import(page)
    page.fill("#ux-imp-src", B1)
    page.fill("#ux-imp-pass", "") if page.is_visible("#ux-imp-pass") else None
    page.click("#ux-import button[onclick='_uxImVerify(this)']")
    maxbars, progs, stats, t0 = 0, [], [], time.time()
    shot_mid = False
    while time.time() - t0 < 90:
        s = snap(page)
        maxbars = max(maxbars, len(s["bars"]))
        if s["progress"] and (not progs or progs[-1] != s["progress"]):
            progs.append(s["progress"])
        if s["status"] and (not stats or stats[-1] != s["status"]):
            stats.append(s["status"])
        if not shot_mid and s["bars"]:
            page.screenshot(path=f"{SHOTS}/I-I3-verifying-en.png"); shot_mid = True
        if s["summary"]:
            break
        page.wait_for_timeout(100)
    s = snap(page)
    ev("I3_verify", secs=round(time.time() - t0, 1), max_visible_bars=maxbars, progress_seq=progs[:40],
       status_seq=stats, summary=s["summary"], bars_end=s["bars"])
    page.screenshot(path=f"{SHOTS}/I-I3-verified-en.png")
    # ---- I3 scan ----
    page.fill("#ux-imp-src", PARENT)
    page.click("#ux-import button[onclick='_uxImScan(this)']")
    page.wait_for_function("() => /What do you want|Nothing importable|Scan failed/.test(document.getElementById('ux-imp-status').innerText)", timeout=30000)
    page.wait_for_timeout(500)
    scan = page.evaluate("""() => ({
      checklist: document.getElementById('ux-imp-checklist').innerText,
      status: document.getElementById('ux-imp-status').innerText,
      passRow: getComputedStyle(document.getElementById('ux-imp-pass-row')).display,
      passLabel: document.querySelector('label[for=ux-imp-pass]').innerText,
      runEnabled: !document.getElementById('ux-imp-run').disabled,
      trustRow: getComputedStyle(document.getElementById('ux-imp-trust-row')).display,
      boxes: Array.from(document.querySelectorAll('#ux-imp-checklist input[type=checkbox]')).map(b => [b.id, b.checked]) })""")
    ev("I3_scan", **scan)
    page.screenshot(path=f"{SHOTS}/I-I3-scan-en.png")

    # ---- I4..I7: the run ----
    for bid, chk in scan["boxes"]:
        if bid != "ux-i-corpus" and chk:
            page.uncheck("#" + bid)
    page.fill("#ux-imp-pass", BPASS)
    for attempt in range(4):
        page.click("#ux-imp-run")
        page.wait_for_timeout(1500)
        st = api("/api/backup/import-queue/status")
        if st.get("state") == "running" or st.get("items"):
            break
        ev("I4_retry_wait", attempt=attempt, st=st.get("state")); page.wait_for_timeout(8000)
    t_run = time.time()
    ev("I4_started", st=st.get("state"))
    page.evaluate(MUT_JS)

    samples = []
    first_full_shot = selection_done = sel_checked = False
    sel_info = None
    reopen_plan = ["close1", "reopen1", "close2", "reopen2", "reload"]
    next_action_at = None
    all_done_seen = False
    api_state = "running"
    last_api = 0
    toasts_seen = []
    amber_shot = False
    while True:
        now = time.time()
        try:
            s = snap(page)
        except Exception as e:
            s = {"err": str(e)}
        s["dt"] = round(now - t_run, 2)
        samples.append(s)
        for tt in s.get("toasts") or []:
            if tt not in [x[1] for x in toasts_seen]:
                toasts_seen.append((s["dt"], tt))
        if now - last_api > 0.8:
            last_api = now
            try:
                qa = api("/api/backup/import-queue/status"); api_state = qa.get("state")
                samples[-1]["api"] = {"state": qa.get("state"), "items": [(i.get("label"), i.get("state"), i.get("stage")) for i in qa.get("items", [])],
                                      "staged": qa.get("items_staged"), "k": (qa.get("checkpoint") or {}).get("k"),
                                      "stages": [(r.get("key"), r.get("state"), r.get("done")) for r in qa.get("stages", [])]}
            except Exception as e:
                samples[-1]["api_err"] = str(e)
        rows = s.get("rows") or []
        if not first_full_shot and s.get("open") and len(s.get("stages") or []) == 4 and rows:
            page.screenshot(path=f"{SHOTS}/I-I4-running-en.png"); first_full_shot = True
            ev("I4_first_full", **s)
        if not amber_shot and s.get("open") and any("not yet saved" in r["text"] for r in rows):
            page.screenshot(path=f"{SHOTS}/I-I6-staged-en.png"); amber_shot = True
            ev("I6_first_staged", **s)
        # I5 selection test (row 3 -> last backup row), once, early
        if first_full_shot and not selection_done and s.get("open") and s["dt"] > 1.5:
            try:
                r3 = page.locator("#ux-imp-stages [data-row-key=search_index]").bounding_box()
                lr = page.locator("#ux-imp-queue-rows > div").last.bounding_box()
                page.mouse.move(r3["x"] + 3, r3["y"] + r3["height"] / 2); page.mouse.down()
                page.mouse.move(lr["x"] + lr["width"] - 3, lr["y"] + lr["height"] / 2, steps=8); page.mouse.up()
                sel_info = page.evaluate("() => { const s = getSelection(); return {text: s.toString(), a: s.anchorNode && s.anchorNode.isConnected, f: s.focusNode && s.focusNode.isConnected}; }")
                sel_info["t"] = s["dt"]; sel_info["rows_at_select"] = [r["text"] for r in rows]
                ev("I5_select", **sel_info)
                page.screenshot(path=f"{SHOTS}/I-I5-selection-en.png")
            except Exception as e:
                ev("I5_select_err", err=str(e))
            selection_done = True
        if selection_done and not sel_checked and sel_info and s["dt"] - sel_info["t"] >= 10:
            after = page.evaluate("() => { const s = getSelection(); return {text: s.toString(), a: s.anchorNode && s.anchorNode.isConnected, f: s.focusNode && s.focusNode.isConnected, collapsed: s.isCollapsed}; }")
            ev("I5_select_after10s", before=sel_info["text"], after=after, rows_now=[r["text"] for r in rows],
               stage3_now=[x["text"] for x in (s.get("stages") or []) if x["key"] == "search_index"], mut=page.evaluate("() => window.__mut"))
            page.screenshot(path=f"{SHOTS}/I-I5-selection-after10s-en.png")
            sel_checked = True; next_action_at = now + 0.5
        if sel_checked and reopen_plan and next_action_at and now >= next_action_at and api_state == "running":
            act = reopen_plan.pop(0)
            if act.startswith("close"):
                close_import(page); next_action_at = now + 5
            elif act.startswith("reopen"):
                open_import(page); page.evaluate(MUT_JS)
                s2 = snap(page); ev("I5_" + act, immediate=s2)
                page.wait_for_timeout(1300); s3 = snap(page); ev("I5_" + act + "_1.3s", **s3)
                next_action_at = time.time() + 1
            elif act == "reload":
                page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(2500)
                if "/unlock" in page.url:
                    ev("I5_reload_locked", url=page.url)
                close_wizard(page); goto_data(page); open_import(page); page.evaluate(MUT_JS)
                s2 = snap(page); ev("I5_after_reload", **s2)
                page.screenshot(path=f"{SHOTS}/I-I5-after-reload-en.png")
                next_action_at = None
        # I7: all four Done
        if not all_done_seen and len(rows) == 4 and all("— Done" in r["text"] for r in rows):
            all_done_seen = True
            ev("I7_all_done", **s)
            page.screenshot(path=f"{SHOTS}/I-I7-alldone-en.png")
            if s.get("open"):
                close_import(page); ev("I7_closed_after_all_done", dt=s["dt"])
        if api_state != "running" and (time.time() - t_run) > 3:
            # keep sampling a bit for toasts
            if not hasattr(sys, "_endt"):
                sys._endt = time.time(); ev("I7_run_terminal", api_state=api_state, dt=s["dt"])
            if time.time() - sys._endt > 8:
                break
        if time.time() - t_run > 1800:
            ev("timeout"); break
        page.wait_for_timeout(120)

    with open(f"{W}/run_samples.jsonl", "w") as f:
        for x in samples:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    ev("I7_toasts", toasts=toasts_seen, mut=page.evaluate("() => window.__mut || null"))
    s_end = snap(page); ev("I7_end_state_dialog", **s_end)
    if s_end.get("open"):
        page.screenshot(path=f"{SHOTS}/I-I7-end-open-en.png")
        close_import(page)
    ev("api_after_run", queue=api("/api/backup/import-queue/status"), rx=api("/api/backup/reindex-backlog/resume/status"))
    # reopen
    open_import(page)
    s_re = snap(page); ev("I7_reopen", **s_re)
    page.screenshot(path=f"{SHOTS}/I-I7-reopen-en.png")
    page.wait_for_timeout(4000); ev("I7_reopen_4s", **snap(page))

    # ---- I8 ----
    link = page.locator("#ux-imp-stages [data-row-key=reindex] a")
    with ctx.expect_page() as pinfo:
        link.click()
    tm = pinfo.value; wire(tm, "tasks")
    tm.wait_for_load_state("domcontentloaded")
    ev("I8_tab", url=tm.url, title=tm.title())
    seen_rx = False
    tm_samples = []
    for i in range(40):
        tm.wait_for_timeout(500)
        body = tm.inner_text("#jobs-body") if tm.is_visible("#jobs-body") else ""
        rx = api("/api/backup/reindex-backlog/resume/status")
        tm_samples.append({"i": i, "body": body[:700], "rx": {k: rx.get(k) for k in ("state", "done", "total")}, "pending": (rx.get("backlog") or {}).get("articles_pending")})
        if "finishing the re-index" in body:
            if not seen_rx:
                tm.screenshot(path=f"{SHOTS}/I-I8-taskmanager-en.png"); seen_rx = True
            if len([x for x in tm_samples if "finishing the re-index" in x["body"]]) >= 3:
                break
        if i > 12 and not seen_rx and rx.get("state") != "running":
            break
    ev("I8_samples", title=tm.title(), samples=tm_samples)
    if not seen_rx:
        tm.screenshot(path=f"{SHOTS}/I-I8-taskmanager-en.png")

    # ---- I9: shut down while the re-index runs ----
    rx = api("/api/backup/reindex-backlog/resume/status")
    ev("I9_before_shutdown", rx=rx)
    page.bring_to_front()
    close_import(page)
    DIALOG_MODE["accept"].add("Shut down the app?")
    page.click("#app-shutdown")
    for _ in range(30):
        time.sleep(1)
        if not listener_pid():
            break
    ev("I9_shutdown_done", listener=listener_pid(), overlay=page.evaluate("() => document.body.innerText.slice(0, 200)"))
    page.screenshot(path=f"{SHOTS}/I-I9-shutdown-en.png")
    br.close()
