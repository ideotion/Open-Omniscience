"""Walk the Import dialog through a failed import, then a real one, watching every change.

Env: OO_WALK_BASE, OO_WALK_OUT, LOC (ui language), W (viewport width), BK (backup folder),
SCEN = "fail-then-ok" | "stop-then-ok" | "reimport".
Each snapshot records the dialog's text, pairs of text boxes that overlap, text that runs
past the dialog's edge, leftover placeholders, and (off English) Latin words for review.
"""
import json, os, re, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8745")
OUT = os.environ["OO_WALK_OUT"]; os.makedirs(OUT, exist_ok=True)
LOC = os.environ.get("LOC", "en"); W = int(os.environ.get("W", "1366"))
BK = os.environ.get("BK", "/tmp/claude-0/imp/bk"); SCEN = os.environ.get("SCEN", "fail-then-ok")
GOOD = "walk-passphrase-1"

PROBE = r"""() => {
  const dlg = document.getElementById('ux-import');
  if (!dlg || !dlg.open) return null;
  const dr = dlg.getBoundingClientRect();
  const boxes = [];
  const walker = document.createTreeWalker(dlg, NodeFilter.SHOW_TEXT);
  let n; let idx = 0;
  while ((n = walker.nextNode())) {
    const s = n.textContent.replace(/\s+/g, ' ').trim();
    if (!s) continue;
    const el = n.parentElement;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || el.closest('[hidden]')) continue;
    if (el.checkVisibility && !el.checkVisibility({contentVisibilityAuto: true, visibilityProperty: true, opacityProperty: true})) continue;
    const det = el.closest('details:not([open])');
    if (det && !el.closest('summary')) continue;
    if (el.closest('option,select,script,style')) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const b of r.getClientRects()) {
      if (b.width < 1 || b.height < 1) continue;
      boxes.push({i: idx, t: s.slice(0, 60), x: b.left, y: b.top, r: b.right, b: b.bottom});
    }
    idx++;
  }
  const overlaps = [];
  for (let a = 0; a < boxes.length; a++) for (let c = a + 1; c < boxes.length; c++) {
    const A = boxes[a], C = boxes[c];
    if (A.i === C.i) continue;
    const w = Math.min(A.r, C.r) - Math.max(A.x, C.x), h = Math.min(A.b, C.b) - Math.max(A.y, C.y);
    if (w > 2 && h > 3) overlaps.push([A.t, C.t, Math.round(w), Math.round(h)]);
  }
  const outside = boxes.filter(b => b.x < dr.left - 1 || b.r > dr.right + 1).map(b => b.t);
  return {
    text: dlg.innerText,
    overlaps, outside: [...new Set(outside)],
    hscroll: dlg.scrollWidth - dlg.clientWidth,
    dialog: [Math.round(dr.left), Math.round(dr.top), Math.round(dr.width), Math.round(dr.height)],
    page_hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}"""
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]|\{[a-z_]+\}")
PATHISH = re.compile(r"(/[\w./-]+|\w*OpenOmniscience\w*|\d{12}\w*)")

snaps, events = [], []
last = {"text": None}

def snap(pg, tag, force=False):
    p = pg.evaluate(PROBE)
    if p is None:
        return None
    changed = p["text"] != last["text"]
    if not (changed or force or p["overlaps"]):
        return p
    last["text"] = p["text"]
    k = len(snaps)
    shot = None
    shape = re.sub(r"[\d\u2068\u2069 ,.]+", "#", p["text"])
    if (force or p["overlaps"] or shape != last.get("shape")) and last.get("shots", 0) < 90:
        last["shape"] = shape; last["shots"] = last.get("shots", 0) + 1
        shot = f"{OUT}/{k:02d}-{tag}.png"
        pg.locator("#ux-import").screenshot(path=shot)
    latin = []
    if LOC not in ("en", "fr", "de", "es", "pt", "id"):
        clean = PATHISH.sub(" ", p["text"])
        latin = sorted(set(w for w in re.findall(r"[A-Za-z]{3,}", clean)))
    snaps.append({"k": k, "t": round(time.time() - T0, 1), "tag": tag, "shot": shot and os.path.basename(shot),
                  "text": p["text"], "overlaps": p["overlaps"], "outside": p["outside"],
                  "hscroll": p["hscroll"], "page_hscroll": p["page_hscroll"], "dialog": p["dialog"],
                  "junk": sorted(set(m.group(0) for m in JUNK.finditer(p["text"]))), "latin": latin})
    return p

def switch(pg, loc):
    if loc == "en":
        return
    pg.evaluate("(l) => OOI18N.setLang(l)", loc)
    pg.wait_for_function("(l) => document.documentElement.lang === l", arg=loc, timeout=8000)
    pg.wait_for_timeout(800)

def watch(pg, tag, until_terminal=True, extra_s=0, max_s=600):
    t_end = None; t0 = time.time()
    while time.time() - t0 < max_s:
        snap(pg, tag)
        st = pg.evaluate("() => fetch('/api/backup/import-queue/status').then(r => r.json())")
        if st.get("state") != "running" and t_end is None and time.time() - t0 > 2:
            t_end = time.time()
        if t_end is not None and time.time() - t_end >= extra_s:
            break
        pg.wait_for_timeout(350)
    pg.wait_for_timeout(1200)
    snap(pg, tag + "-end", force=True)

def open_import(pg):
    pg.evaluate("() => { showTab('settings'); showSetCat('data'); }")
    pg.wait_for_timeout(500)
    pg.click("#set-data button[data-on-click='openUnifiedImport()']")
    pg.wait_for_selector("#ux-import[open]")
    pg.wait_for_timeout(1200)

def scan(pg):
    pg.fill("#ux-imp-src", BK)
    pg.click("#ux-import button[data-on-click='_uxImScan(this)']")
    pg.wait_for_function("() => !document.getElementById('ux-imp-run').disabled", timeout=20000)
    pg.wait_for_timeout(400)

def run(pg, passphrase):
    pg.fill("#ux-imp-pass", passphrase)
    pg.click("#ux-imp-run")
    # What the dialog shows the instant the click lands, before any request returns.
    snap(pg, "clicked", force=True)

T0 = time.time()
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    ctx = br.new_context(viewport={"width": W, "height": int(os.environ.get("H", "1500"))})
    pg = ctx.new_page()
    errs, bad = [], []
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errs.append(f"console.error: {m.text[:240]}") if m.type == "error" else None)
    pg.on("response", lambda r: bad.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
    pg.on("dialog", lambda d: (events.append(f"native {d.type}: {d.message[:300]}"), d.accept()))
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    switch(pg, LOC)
    open_import(pg)
    snap(pg, "open", force=True)
    scan(pg)
    snap(pg, "scanned", force=True)
    if SCEN == "fail-then-ok":
        run(pg, "wrong-passphrase")
        watch(pg, "wrongpass")
        run(pg, GOOD)
        watch(pg, "second", extra_s=25)
    elif SCEN == "stop-then-ok":
        run(pg, GOOD)
        pg.wait_for_function("() => /./.test(document.getElementById('ux-imp-stages').innerText)", timeout=20000)
        pg.wait_for_timeout(2500)
        snap(pg, "before-stop", force=True)
        pg.click("#ux-imp-stop")
        watch(pg, "stopped")
        run(pg, GOOD)
        watch(pg, "after-stop", extra_s=25)
    elif SCEN == "reimport":
        run(pg, GOOD)
        watch(pg, "reimport", extra_s=10)
    # A reopen is a fresh page (R1).
    pg.click("#ux-import button[data-on-click=\"ooCloseDialog('ux-import')\"]")
    pg.wait_for_timeout(500)
    open_import(pg)
    snap(pg, "reopened", force=True)
    pg.screenshot(path=f"{OUT}/page-after.png")
    br.close()

json.dump({"loc": LOC, "w": W, "scen": SCEN, "errors": errs, "bad": bad, "events": events, "snaps": snaps},
          open(f"{OUT}/report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({"loc": LOC, "scen": SCEN, "snaps": len(snaps), "errors": errs[:5], "bad": bad[:8], "events": events,
                  "overlap_snaps": [s["k"] for s in snaps if s["overlaps"]],
                  "outside_snaps": [s["k"] for s in snaps if s["outside"]],
                  "junk": sorted({j for s in snaps for j in s["junk"]})}, ensure_ascii=False, indent=1))
