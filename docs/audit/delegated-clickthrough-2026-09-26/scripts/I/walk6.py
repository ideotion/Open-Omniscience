"""Row I walk, phase 1: first launch of the throwaway, I2, I3, I4-I8, and the I9 shutdown."""
import json, sys, time
from playwright.sync_api import sync_playwright
import common
common.PORT = 8815; common.BASE = 'http://127.0.0.1:8815'; common.TGT = '/tmp/claude-0/walk/I/tgt3'
from common import *
BASE = common.BASE

B1 = f"{W}/backups2/202609261808_OpenOmniscience_Backup"
PARENT = f"{W}/backups2"

start_server(common.TGT, 8815)

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
    ev("after_create3", url=page.url)
    close_wizard(page)

    goto_data(page)
    open_import(page)
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


    ANIM_JS = """() => { window.__anim = window.__anim || [];
      if (!window.__animHooked) { window.__animHooked = 1;
        document.addEventListener('animationstart', (e) => { const n = e.target; if (n.closest && n.closest('#ux-imp-queue-note'))
          window.__anim.push({t: Math.round(performance.now()), name: e.animationName, text: (n.innerText || '').slice(0, 50)}); }, true); }
      return window.__anim.length; }"""
    page.fill("#ux-imp-pass", BPASS)
    page.click("#ux-imp-run")
    t0 = time.time(); page.evaluate(ANIM_JS)
    reloaded = closed = False; seen = []; toasts = []; t_end = None
    while time.time() - t0 < 120:
        dt = round(time.time() - t0, 2)
        try:
            s = snap(page); s["dt"] = dt; seen.append(s)
        except Exception as e:
            s = {"dt": dt, "err": str(e)}
        for tt in s.get("toasts") or []:
            if tt not in [x[1] for x in toasts]:
                toasts.append((dt, tt))
        qa = api("/api/backup/import-queue/status")
        if not reloaded and dt > 1.5:
            before = [r["text"][:60] for r in s.get("rows") or []]
            page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(1500)
            close_wizard(page); goto_data(page); open_import(page); page.evaluate(ANIM_JS)
            s2 = snap(page)
            ev("I5_reload_in_run", dt_reload=dt, rows_before=before, after=s2, api_state=qa.get("state"))
            page.screenshot(path=f"{SHOTS}/I-I5-after-reload-en.png")
            reloaded = True; continue
        rows = s.get("rows") or []
        if reloaded and not closed and len(rows) == 4 and sum("— Done" in r["text"] for r in rows) >= 3 and s.get("open"):
            anims = page.evaluate("() => window.__anim")
            ev("I7_close_before_end", dt=dt, rows=[r["text"][:60] for r in rows], anim_count=len(anims), anims=anims[:40])
            close_import(page); closed = True
        if qa.get("state") != "running" and t_end is None:
            t_end = time.time(); ev("run3_terminal", dt=dt, state=qa.get("state"), dialog_open=s.get("open"))
        if t_end and time.time() - t_end > 8:
            break
        page.wait_for_timeout(100)
    staged_dts = [x["dt"] for x in seen if "not yet saved" in (x.get("note") or "")]
    ev("I7_toasts_run3", toasts=toasts, staged_window=[staged_dts[0], staged_dts[-1]] if staged_dts else None,
       anims=page.evaluate("() => window.__anim"))
    page.screenshot(path=f"{SHOTS}/I-I7-toast-en.png")
    with open(f"{W}/run3_samples.jsonl", "w") as f:
        for x in seen:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    br.close()
