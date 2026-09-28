"""Row I walk, phase 3: relaunch after the mid-re-index shutdown (I9), then I10, I11, I12 and
the 375 px pass, on the same throwaway."""
import json, time
from playwright.sync_api import sync_playwright
from common import *

TITLE = "Batch r elections 0"
start_server()
t_boot = time.time()

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = br.new_context(viewport={"width": 1440, "height": 950}, locale="en-US")
    page = ctx.new_page(); wire(page, "app"); page.on("dialog", on_dialog)
    ctx.on("page", lambda pg: (wire(pg, "popup:" + pg.url), pg.on("dialog", on_dialog)))

    # ---- I9 relaunch + unlock ----
    page.goto(BASE + "/", wait_until="domcontentloaded"); page.wait_for_timeout(1500)
    ev("I9_relaunch_url", url=page.url, lock=api("/api/system/lock-state"))
    page.wait_for_selector("#view-unlock:not(.hidden)", timeout=30000)
    page.screenshot(path=f"{SHOTS}/I-I9-unlock-en.png")
    page.fill("#pw", PASS); page.click("#btn-unlock")
    for _ in range(60):
        page.wait_for_timeout(1000)
        if "/unlock" not in page.url:
            break
    t_unlock = time.time()
    page.wait_for_timeout(2000)
    ev("I9_unlocked", url=page.url)
    close_wizard(page)
    # Tasks & system -> Processes, no click on anything re-index related
    with ctx.expect_page() as pinfo:
        page.click("#tm-open")
    tm = pinfo.value; wire(tm, "tasks"); tm.wait_for_load_state("domcontentloaded")
    seen = None; tsamples = []
    for i in range(60):
        tm.wait_for_timeout(2000)
        body = tm.inner_text("#jobs-body") if tm.is_visible("#jobs-body") else ""
        rx = api("/api/backup/reindex-backlog/resume/status")
        tsamples.append({"s_after_unlock": round(time.time() - t_unlock, 1), "body": body[:300],
                         "rx": {k: rx.get(k) for k in ("state", "done", "total")},
                         "pending": (rx.get("backlog") or {}).get("articles_pending")})
        if "finishing the re-index" in body and seen is None:
            seen = time.time() - t_unlock
            tm.screenshot(path=f"{SHOTS}/I-I9-taskmanager-resumed-en.png")
        if seen is not None and len([x for x in tsamples if "finishing the re-index" in x["body"]]) >= 3:
            break
        if rx.get("state") == "done" and (rx.get("backlog") or {}).get("articles_pending") == 0 and i > 3:
            break
    ev("I9_tasks", first_seen_s_after_unlock=seen, samples=tsamples)

    # Import dialog after the restart
    page.bring_to_front()
    goto_data(page); open_import(page)
    s0 = snap(page); ev("I9_import_dialog_0s", **s0)
    page.wait_for_timeout(3000)
    s3 = snap(page); ev("I9_import_dialog_3s", **s3)
    page.screenshot(path=f"{SHOTS}/I-I9-import-after-restart-en.png")
    close_import(page)
    # title search through the omni bar
    page.click(".omni"); page.wait_for_timeout(400)
    page.keyboard.type(TITLE, delay=20)
    page.wait_for_timeout(3000)
    pal = page.inner_text("#pal-list")
    ev("I9_search", query=TITLE, found=TITLE in pal, results=pal[:800])
    page.screenshot(path=f"{SHOTS}/I-I9-search-en.png")
    page.keyboard.press("Escape"); page.wait_for_timeout(400)

    # wait for the resumed re-index to finish (bounded), then report the task manager end state
    for i in range(60):
        rx = api("/api/backup/reindex-backlog/resume/status")
        if rx.get("state") != "running":
            break
        time.sleep(2)
    tm.wait_for_timeout(2500)
    ev("I9_reindex_end", rx={k: rx.get(k) for k in ("state", "done", "total", "result")},
       pending=(rx.get("backlog") or {}).get("articles_pending"), tasks_body=tm.inner_text("#jobs-body")[:300])
    tm.screenshot(path=f"{SHOTS}/I-I9-taskmanager-end-en.png")

    # ---- I10: history ----
    page.bring_to_front()
    page.click("#set-subtabs button[data-tab='advanced']"); page.wait_for_timeout(600)
    page.click("#set-subtabs button[data-tab='data']"); page.wait_for_timeout(1500)
    hist_html = page.inner_html("#imp-history"); hist = page.inner_text("#imp-history")
    ev("I10_history", text=hist, reports=api("/api/backup/import-reports"))
    page.locator("#imp-history").scroll_into_view_if_needed()
    page.screenshot(path=f"{SHOTS}/I-I10-history-en.png")
    junk_scan(page, "#set-data", "I10 set-data en")
    first = page.locator("#imp-history a").first
    with ctx.expect_page() as pinfo:
        first.click()
    rp = pinfo.value
    try:
        rp.wait_for_load_state("domcontentloaded", timeout=10000)
        body = rp.inner_text("body")
    except Exception as e:
        body = "ERR " + str(e)
    ev("I10_report_tab", url=rp.url, head=body[:900])
    try:
        rp.screenshot(path=f"{SHOTS}/I-I10-report-en.png")
    except Exception:
        pass
    rp.close()
    # also open the dialog's Last import line for comparison
    open_import(page); ev("I10_dialog_last_line", last=snap(page)["last"]); close_import(page)

    # ---- I11: locales ----
    for code in ("fr", "ar", "zh", "en"):
        set_lang(page, code)
        page.wait_for_timeout(800)
        open_import(page)
        s = snap(page)
        dstyle = page.evaluate("""() => { const d = document.getElementById('ux-import'); const r = d.querySelector('#ux-imp-stages > div');
             const dot = r ? r.querySelector('span') : null;
             return {dir: getComputedStyle(d).direction, textAlign: getComputedStyle(d.querySelector('#ux-imp-statements')).textAlign,
                     dotLeft: dot ? dot.getBoundingClientRect().left : null, rowLeft: r ? r.getBoundingClientRect().left : null, rowRight: r ? r.getBoundingClientRect().right : null,
                     dlgScroll: d.scrollWidth - d.clientWidth}; }""")
        ev(f"I11_dialog_{code}", dialog=s, style=dstyle)
        junk_scan(page, "#ux-import", f"I11 dialog {code}")
        page.screenshot(path=f"{SHOTS}/I-I11-dialog-{code}.png")
        close_import(page)
        page.hover("#set-checkpoint-k"); page.wait_for_timeout(900)
        tip = page.evaluate("() => { const t = document.getElementById('oo-tip'); return t ? t.innerText : null; }")
        hsec = page.evaluate("() => { const h = document.getElementById('imp-history').parentElement; return h.innerText; }")
        lbl = page.inner_text("label[for=set-checkpoint-k]")
        hint = page.evaluate("() => document.getElementById('set-checkpoint-k').closest('.row').nextElementSibling.innerText")
        ev(f"I11_settings_{code}", tip=tip, history_section=hsec[:900], k_label=lbl, k_hint=hint)
        page.locator("#imp-history").scroll_into_view_if_needed()
        page.screenshot(path=f"{SHOTS}/I-I11-history-{code}.png")
        junk_scan(page, "#set-data", f"I11 set-data {code}")

    # ---- I12: K override ----
    page.fill("#set-checkpoint-k", "1"); page.locator("#set-checkpoint-k").press("Tab")
    page.wait_for_timeout(2000)
    msg = page.inner_text("#set-checkpoint-k-msg")
    settings_k = api("/api/settings").get("import_checkpoint_k")
    open_import(page); sent = snap(page)["checkpoint"]
    page.screenshot(path=f"{SHOTS}/I-I12-k1-dialog-en.png"); close_import(page)
    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(2500); close_wizard(page); goto_data(page)
    k_after_reload = page.input_value("#set-checkpoint-k")
    ev("I12_k1", msg=msg, settings_k=settings_k, dialog_sentence=sent, k_after_reload=k_after_reload,
       queue_k=api("/api/backup/import-queue/status").get("checkpoint"))
    page.fill("#set-checkpoint-k", "3"); page.locator("#set-checkpoint-k").press("Tab")
    page.wait_for_timeout(2000)
    ev("I12_undo", msg=page.inner_text("#set-checkpoint-k-msg"), k=page.input_value("#set-checkpoint-k"),
       settings_k=api("/api/settings").get("import_checkpoint_k"))

    # ---- 375 px pass (en) ----
    m = br.new_context(viewport={"width": 375, "height": 800}, locale="en-US")
    mp = m.new_page(); wire(mp, "mobile"); mp.on("dialog", on_dialog)
    mp.goto(BASE + "/#settings", wait_until="domcontentloaded"); mp.wait_for_timeout(2500); close_wizard(mp)
    res = {}
    try:
        mp.click("#set-subtabs button[data-tab='data']"); mp.wait_for_timeout(1500)
        res["settings_scroll"] = mp.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        mp.locator("#imp-history").scroll_into_view_if_needed()
        mp.screenshot(path=f"{SHOTS}/I-375-settings-en.png")
        mp.click("#set-data button[onclick='openUnifiedImport()']"); mp.wait_for_timeout(1800)
        res["dialog_scroll"] = mp.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        res["dialog_inner_overflow"] = mp.evaluate("""() => { const d = document.getElementById('ux-import'); const out = [];
            d.querySelectorAll('*').forEach(e => { if (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible' ) out.push((e.id || e.tagName) + ':' + (e.scrollWidth - e.clientWidth)); });
            const r = d.getBoundingClientRect(); return {clipped: out.slice(0, 10), dlgLeft: r.left, dlgRight: r.right, vw: innerWidth, dlgScroll: d.scrollWidth - d.clientWidth}; }""")
        mp.screenshot(path=f"{SHOTS}/I-375-dialog-en.png", full_page=False)
    except Exception as e:
        res["err"] = str(e)
    ev("W375", **res)
    br.close()
