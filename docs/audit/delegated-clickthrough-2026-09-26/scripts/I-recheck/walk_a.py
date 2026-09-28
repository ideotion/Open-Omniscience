"""Row I RECHECK, run A: K sentence vs setting (D5), 4-backup K=3 import with the dialog open
(D2 start claims, D9 blink/overlap, D1 freeze at end, D6 overcount, D14 done-row stage),
reopen (D3, D1), history (D7), fr/ar/zh (D11, D12), 375 px (D13)."""
import json, sys, time
from playwright.sync_api import sync_playwright
from common import *

PARENT = f"{W}/backups"
SH = f"{W}/shots"
import os; os.makedirs(SH, exist_ok=True)

ANIM_JS = r"""() => {
  if (window.__anim) return;
  window.__anim = [];
  document.addEventListener('animationstart', (e) => {
    const t = e.target;
    const inNote = !!(t.closest && t.closest('#ux-imp-queue-note'));
    if (inNote) window.__anim.push({t: Math.round(performance.now()), cls: t.className, text: (t.innerText||'').slice(0,80)});
  }, true);
}"""

OVERLAP_JS = r"""() => {
  const note = document.getElementById('ux-imp-queue-note');
  if (!note) return null;
  const b = note.querySelector('b'); const sp = note.querySelector('span.note');
  if (!b || !sp) return {b: !!b, sp: !!sp};
  const rb = b.getBoundingClientRect(), rs = sp.getBoundingClientRect();
  const cs = getComputedStyle(sp);
  return {b: [rb.top, rb.bottom, rb.left, rb.right], sp: [rs.top, rs.bottom, rs.left, rs.right],
          overlap_px: Math.max(0, rb.bottom - rs.top), display: cs.display, padding: cs.padding,
          anim: cs.animationName, bg: cs.backgroundColor, shadow: cs.boxShadow.slice(0, 40)};
}"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = br.new_context(viewport={"width": 1440, "height": 950}, locale="en-US")
    page = ctx.new_page(); wire(page, "app"); page.on("dialog", on_dialog)
    DIALOG_MODE["accept"].add("Another job is writing")
    unlock_if_needed(page)
    ev("A_unlocked", url=page.url, lock=api("/api/system/lock-state"))
    goto_data(page)
    kbox = page.input_value("#set-checkpoint-k")
    ev("A_k_box_initial", k=kbox, setting=api("/api/settings").get("import_checkpoint_k"),
       q=(api("/api/backup/import-queue/status").get("checkpoint") or {}).get("k"))
    open_import(page)
    ev("A_dialog_fresh", **snap(page))
    close_import(page)

    # ---- D5: set K=1, then open the dialog ----
    page.fill("#set-checkpoint-k", "1"); page.keyboard.press("Tab"); page.wait_for_timeout(1500)
    ev("D5_k1_saved", msg=page.inner_text("#set-checkpoint-k-msg"), setting=api("/api/settings").get("import_checkpoint_k"),
       q=(api("/api/backup/import-queue/status").get("checkpoint") or {}).get("k"))
    open_import(page)
    s = snap(page); ev("D5_dialog_after_k1", checkpoint=s["checkpoint"])
    page.screenshot(path=f"{SH}/D5-k1-dialog-en.png")
    close_import(page)
    page.fill("#set-checkpoint-k", "3"); page.keyboard.press("Tab"); page.wait_for_timeout(1500)
    ev("D5_k3_restored", setting=api("/api/settings").get("import_checkpoint_k"))

    # ---- Run A ----
    open_import(page)
    page.fill("#ux-imp-src", PARENT)
    page.click("#ux-import button[onclick='_uxImScan(this)']")
    page.wait_for_function("() => /What do you want|Nothing importable|Scan failed/.test(document.getElementById('ux-imp-status').innerText)", timeout=30000)
    boxes = page.evaluate("() => Array.from(document.querySelectorAll('#ux-imp-checklist input[type=checkbox]')).map(b => [b.id, b.checked])")
    for bid, chk in boxes:
        if bid != "ux-i-corpus" and chk: page.uncheck("#" + bid)
    page.fill("#ux-imp-pass", BPASS)
    page.evaluate(ANIM_JS)
    rx0 = api("/api/backup/reindex-backlog/resume/status")
    ev("A_rx_before", rx=rx0)
    page.click("#ux-imp-run")
    t0 = time.time()
    samples = []; flags = {}
    last_api = 0; api_state = "running"; t_term = None
    while True:
        now = time.time()
        s = snap(page); s["dt"] = round(now - t0, 2)
        if now - last_api > 0.5:
            last_api = now
            try:
                q = api("/api/backup/import-queue/status"); api_state = q.get("state")
                rx = api("/api/backup/reindex-backlog/resume/status")
                s["api"] = {"state": api_state, "items": [(i.get("label"), i.get("state"), i.get("stage")) for i in q.get("items", [])],
                            "stages": [(r.get("key"), r.get("state")) for r in q.get("stages", [])], "k": (q.get("checkpoint") or {}).get("k")}
                s["rx"] = {"state": rx.get("state"), "done": rx.get("done"), "total": rx.get("total"),
                           "pending": (rx.get("backlog") or {}).get("articles_pending")}
            except Exception as e:
                s["api_err"] = str(e)
        samples.append(s)
        st = s.get("stages") or []
        rows = s.get("rows") or []
        if len(st) == 4 and "start" not in flags:
            flags["start"] = s; ev("D2_first_stages", dt=s["dt"], stages=[x["text"] for x in st], statements=s["statements"], note=s["note"], api=s.get("api"))
            page.screenshot(path=f"{SH}/D2-start-en.png")
        if any("not yet saved" in r["text"] for r in rows) and "staged" not in flags:
            flags["staged"] = s
            page.wait_for_timeout(200)
            ov = page.evaluate(OVERLAP_JS)
            ev("D9_first_staged", dt=s["dt"], note=s["note"], overlap=ov)
            page.screenshot(path=f"{SH}/D9-staged-en.png")
            try:
                page.locator("#ux-imp-queue-note").screenshot(path=f"{SH}/D9-staged-note-crop-en.png")
            except Exception as e:
                ev("crop_err", err=str(e))
        if rows and all("— Done" in r["text"] for r in rows) and "alldone" not in flags:
            flags["alldone"] = s; ev("A_all_done_ui", dt=s["dt"], stages=[x["text"] for x in st], statements=s["statements"], rows=[r["text"] for r in rows])
        if api_state != "running" and t_term is None:
            t_term = now; ev("A_api_terminal", dt=s["dt"], state=api_state)
        if t_term and now - t_term > 7:
            break
        if now - t0 > 900:
            ev("timeout"); break
        page.wait_for_timeout(100)
    with open(f"{W}/runA_samples.jsonl", "w") as f:
        for x in samples: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    anims = page.evaluate("() => window.__anim")
    ev("D9_anims", n=len(anims), anims=anims[:40])
    end = snap(page)
    rxe = api("/api/backup/reindex-backlog/resume/status")
    ev("D1_end_ui", stages=[x["text"] for x in end["stages"]], statements=end["statements"], summary=end["summary"],
       rows=[r["text"] for r in end["rows"]], toasts=end["toasts"])
    ev("D1_end_api", rx_state=rxe.get("state"), rx_done=rxe.get("done"), rx_total=rxe.get("total"),
       pending=(rxe.get("backlog") or {}).get("articles_pending"))
    page.screenshot(path=f"{SH}/D1-end-open-en.png", full_page=False)
    # keep watching the open dialog for 8 more seconds: does row 4 ever update?
    page.wait_for_timeout(8000)
    end2 = snap(page); rxe2 = api("/api/backup/reindex-backlog/resume/status")
    ev("D1_end_plus8", row4=[x["text"] for x in end2["stages"] if x["key"] == "reindex"], stmt=end2["statements"],
       rx_state=rxe2.get("state"), rx_done=rxe2.get("done"), rx_total=rxe2.get("total"), pending=(rxe2.get("backlog") or {}).get("articles_pending"))
    # the summaries the queue carries: per-item reindex_deferred
    q = api("/api/backup/import-queue/status")
    per = []
    for it in q.get("items", []):
        sm = it.get("summary") or {}
        rep = sm.get("report") or sm
        rd = rep.get("reindex_deferred") if isinstance(rep, dict) else None
        per.append((it.get("label"), it.get("state"), (rd or {}).get("articles_pending")))
    ev("D6_per_item_pending", per=per)
    close_import(page)

    # ---- reopen (D3 / D1) ----
    open_import(page)
    r0 = snap(page); ev("D3_reopen_immediate", **r0)
    page.screenshot(path=f"{SH}/D3-reopen-en.png")
    page.wait_for_timeout(7000)
    r7 = snap(page); rx7 = api("/api/backup/reindex-backlog/resume/status")
    ev("D1_reopen_7s", row4=[x["text"] for x in r7["stages"] if x["key"] == "reindex"], stmt=r7["statements"],
       rx_state=rx7.get("state"), rx_done=rx7.get("done"), rx_total=rx7.get("total"))
    close_import(page)

    # ---- history (D7) ----
    goto_data(page)
    page.wait_for_timeout(1500)
    hist = page.inner_text("#imp-history")
    reps = api("/api/backup/import-reports")
    ev("D7_history", text=hist, reports=[(r.get("filename"), r.get("articles"), r.get("outcome")) for r in reps.get("reports", [])])
    page.locator("#imp-history").screenshot(path=f"{SH}/D7-history-en.png")

    # ---- languages (D11, D12) ----
    for lang in ("fr", "ar", "zh"):
        set_lang(page, lang)
        open_import(page)
        sl = snap(page)
        ev("D11_" + lang, rows=[r["text"] for r in sl["rows"]], stages=[x["text"] for x in sl["stages"]], dir=sl["dir"])
        page.screenshot(path=f"{SH}/D11-dialog-{lang}.png")
        if lang == "ar":
            try:
                page.locator("#ux-imp-queue-rows").screenshot(path=f"{SH}/D12-rows-ar.png")
            except Exception as e:
                ev("crop_err", err=str(e))
        close_import(page)
    set_lang(page, "en")

    # ---- 375 px (D13) ----
    page.set_viewport_size({"width": 375, "height": 800}); page.wait_for_timeout(800)
    open_import(page)
    page.fill("#ux-imp-src", PARENT)
    m = page.evaluate(r"""() => {
      const d = document.getElementById('ux-import'); const i = document.getElementById('ux-imp-src');
      const ri = i.getBoundingClientRect(); const rd = d.getBoundingClientRect();
      const rows = Array.from(document.querySelectorAll('#ux-imp-queue-rows > div')).map(r => ({sw: r.scrollWidth, cw: r.clientWidth, right: r.getBoundingClientRect().right}));
      return {page_over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
              dlg_sw: d.scrollWidth, dlg_cw: d.clientWidth, dlg_right: rd.right, input_w: ri.width, rows};
    }""")
    ev("D13_375", **m)
    page.screenshot(path=f"{SH}/D13-375-dialog-en.png")
    close_import(page)
    page.set_viewport_size({"width": 1440, "height": 950})
    br.close()
