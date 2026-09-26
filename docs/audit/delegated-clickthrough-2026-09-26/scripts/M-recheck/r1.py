"""Recheck phase 1: fold job, task-manager controls, second fold (idempotence), bulletin nesting."""
import json
import sys
import time

sys.path.insert(0, "/tmp/claude-0/walk/M-recheck")
from harness import *  # noqa

BASE = "http://127.0.0.1:8828"
R = {}
DIALOGS = []


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message})
    d.accept()


def run_fold(page, tm, tag):
    DIALOGS.clear()
    page.click("#kw-fold-btn")
    seq, tm_rows = [], []
    t0 = time.time()
    last = None
    while time.time() - t0 < 240:
        s = page.inner_text("#kw-fold-status")
        if s != last:
            seq.append([round(time.time() - t0, 2), s])
            last = s
        if tm is not None and len(tm_rows) < 6:
            try:
                rows = tm.evaluate("""() => [...document.querySelectorAll('.job')].map(j => ({
                    text: j.innerText.replace(/\\s+/g,' ').slice(0,160),
                    buttons: [...j.querySelectorAll('button')].map(b => b.textContent)}))""")
                api = tm.evaluate("async () => (await (await fetch('/api/jobs')).json()).jobs.filter(j=>j.kind==='keyword-fold').map(j=>({state:j.state, actions:j.actions, label:j.label}))")
                if api:
                    tm_rows.append({"t": round(time.time() - t0, 2), "dom": [r for r in rows if 'keyword' in r['text'].lower() or 'fold' in r['text'].lower()], "api": api})
            except Exception as e:
                tm_rows.append({"err": str(e)[:200]})
        dis = page.evaluate("() => document.getElementById('kw-fold-btn').disabled")
        if not dis and time.time() - t0 > 3 and s:
            break
        page.wait_for_timeout(300)
    R[tag + "_dialogs"] = list(DIALOGS)
    R[tag + "_seq"] = seq
    R[tag + "_final"] = page.inner_text("#kw-fold-status")
    R[tag + "_tm"] = tm_rows
    rep = page.evaluate("async () => (await fetch('/api/insights/keyword-fold-job/report')).json()")
    with open(log_path(f"fold_report_{tag}.json"), "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    return rep


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    R["unlocked"] = unlock_if_needed(page, BASE)
    close_guide(page)
    R["net"] = page.evaluate("async () => (await fetch('/api/system/network')).json()")
    open_settings_advanced(page)
    open_adv(page, "diagnostics")
    page.locator("#kw-fold-btn").scroll_into_view_if_needed()
    # the standalone task manager (what the top-bar button opens)
    tm = ctx.new_page()
    attach(tm, "tm")
    tm.goto(BASE + "/tasks", wait_until="domcontentloaded")
    tm.wait_for_timeout(1500)
    page.bring_to_front()
    rep1 = run_fold(page, tm, "first")
    tm.screenshot(path=log_path("Mr-M11-taskmanager-en.png"))
    rep2 = run_fold(page, None, "second")
    shot(page, "Mr-M2-second-fold-en.png", selector="#kw-fold-status >> xpath=..")
    R["first_fold_counts"] = rep1.get("fold")
    R["second_fold_counts"] = rep2.get("fold")
    R["second_largest"] = rep2.get("largest_folds")
    R["first_fila"] = [e for e in (rep1.get("largest_folds") or []) if e.get("from") in ("fila", "filas", "cooperativa", "cooperativas", "errors", "errores")]
    # bulletin nesting
    R["bulletin"] = page.evaluate("""() => {
        const d = document.querySelector('details.adv-sec[data-adv=bulletin]');
        if (!d) return null;
        const par = d.parentElement.closest('details');
        return {parent_details: par ? par.dataset.adv : null, parent_open: par ? par.open : null,
                visible: !!(d.offsetWidth || d.offsetHeight), in_phead: !!d.closest('.phead'),
                top_level_advs: [...document.querySelectorAll('#set-advanced > details.adv-sec, details.adv-sec')].filter(x => !x.parentElement.closest('details.adv-sec')).map(x => x.dataset.adv)};
    }""")
    page.locator("details.adv-sec[data-adv=uninstall] > summary").scroll_into_view_if_needed()
    page.locator("details.adv-sec[data-adv=uninstall] > summary").click()
    page.wait_for_timeout(800)
    R["bulletin_after_uninstall_open"] = page.evaluate("() => { const d=document.querySelector('details.adv-sec[data-adv=bulletin]'); const r=d.getBoundingClientRect(); const w=[...document.querySelectorAll('#uninstall-panel button.danger')].map(b=>b.textContent); return {visible: !!(d.offsetWidth||d.offsetHeight), danger_buttons: w}; }")
    page.locator("details.adv-sec[data-adv=bulletin]").scroll_into_view_if_needed()
    shot(page, "Mr-M8h-bulletin-inside-uninstall-en.png")
    b.close()

with open(log_path("r1.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("r1_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:8000])
