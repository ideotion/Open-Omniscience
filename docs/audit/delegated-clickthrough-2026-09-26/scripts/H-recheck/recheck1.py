"""Row H recheck, part 1: unlock (encrypted, LOCKED at boot), the #oo-tip-behind-top-layer
claim (P1), keyboard focus (P2), Local AI transparent text (P3), Discover-by-topic heading (P3).

Independent of the walker's harness: own instance on 8812, own measurements. Beyond the
pixel diff, it asks the browser directly WHICH element is painted at the bubble's centre
(document.elementsFromPoint ignores pointer-events:none? no -- it skips them, so we use a
different probe: temporarily flip the bubble to pointer-events:auto for the hit test only)."""
import json
import os
import sys

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8812"
OUT = "/tmp/claude-0/walk/H-recheck"
PASS = "walk-pass-2026"
VW, VH = 1440, 950
rep = {"notes": [], "page_errors": [], "console_errors": [], "http_errors": []}


def attach(pg):
    pg.on("pageerror", lambda e: rep["page_errors"].append(str(e)[:300]))
    pg.on("console", lambda m: rep["console_errors"].append(m.text[:300]) if m.type == "error" else None)
    pg.on("response", lambda r: rep["http_errors"].append(f"{r.status} {r.url}") if r.status >= 400 else None)


def api(pg, path, method="GET", body=None):
    return pg.evaluate("""([p, m, b]) => fetch(p, {method: m, headers: {'Content-Type': 'application/json'},
        body: b === null ? undefined : JSON.stringify(b)}).then(r => r.json())""", [path, method, body])


def crop(path, r):
    im = Image.open(path).convert("RGB")
    x0, y0 = max(0, int(r["x"])), max(0, int(r["y"]))
    x1, y1 = min(VW, int(r["x"] + r["w"])), min(VH, int(r["y"] + r["h"]))
    if x1 <= x0 or y1 <= y0:
        return None
    return np.asarray(im.crop((x0, y0, x1, y1))).astype(int)


def diff(a_path, b_path, r):
    a, b = crop(a_path, r), crop(b_path, r)
    if a is None or b is None:
        return None
    d = np.abs(a - b).sum(axis=2)
    return {"changed": int((d > 30).sum()), "total": int(d.size), "ratio": round(float((d > 30).sum()) / max(1, d.size), 4)}


TIP = """() => { const t = document.getElementById('oo-tip'); const r = t.getBoundingClientRect();
  const cs = getComputedStyle(t);
  // hit-test probe: the bubble is pointer-events:none, so flip it ON for the probe only
  const pe = t.style.pointerEvents; t.style.pointerEvents = 'auto';
  const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
  const top = document.elementFromPoint(cx, cy);
  t.style.pointerEvents = pe;
  const d = document.getElementById('net-consent');
  return {shown: t.classList.contains('show'), opacity: cs.opacity, text: t.textContent,
    parent: t.parentElement.tagName, inDialog: !!t.closest('dialog'),
    rect: {x: r.x, y: r.y, w: r.width, h: r.height},
    topElementAtCentre: top ? (top.id ? '#' + top.id : top.tagName + '.' + top.className) : null,
    topIsTip: top === t, dialogModal: d ? d.matches(':modal') : null,
    dialogRect: d ? (() => { const q = d.getBoundingClientRect(); return {x: q.x, y: q.y, w: q.width, h: q.height}; })() : null};
}"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": VW, "height": VH})
    pg = ctx.new_page()
    attach(pg)
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector("#pw", state="visible", timeout=60000)
    rep["lock_before"] = api(pg, "/api/system/lock-state")
    pg.fill("#pw", PASS)
    pg.click("#btn-unlock")
    pg.wait_for_function("() => location.hash === '#home'", timeout=120000)
    pg.wait_for_selector("#net-toggle", timeout=60000)
    pg.wait_for_timeout(3000)
    rep["lock_after"] = api(pg, "/api/system/lock-state")
    if pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
        pg.click("#gw-close"); pg.wait_for_timeout(400); rep["notes"].append("closed guide-wizard via #gw-close")
    loc = pg.locator("#net-coach-dismiss")
    if loc.count() and loc.is_visible():
        loc.click(); pg.wait_for_timeout(300); rep["notes"].append("dismissed net coach")
    rep["network_start"] = api(pg, "/api/system/network")

    # ---- CONTROL: the bubble outside any dialog ----
    pg.mouse.move(700, 600); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/_ctl-off.png")
    pg.hover("#net-toggle"); pg.wait_for_timeout(800)
    ctl = pg.evaluate(TIP)
    pg.screenshot(path=f"{OUT}/H-ctl-plane-hover-en.png")
    ctl["pixel_diff"] = diff(f"{OUT}/H-ctl-plane-hover-en.png", f"{OUT}/_ctl-off.png", ctl["rect"])
    rep["control_plane_hover"] = ctl
    pg.mouse.move(700, 600); pg.wait_for_timeout(500)

    # ---- open the popup with a real click ----
    pg.click("#net-toggle")
    pg.wait_for_function("() => { const d = document.getElementById('net-consent'); return d && d.open && "
                         "document.querySelectorAll('#net-consent-lanes .oo-tip-target').length > 10; }", timeout=20000)
    pg.wait_for_timeout(800)
    lanes = pg.evaluate("""() => [...document.querySelectorAll('#net-consent-lanes > div > span:first-child')].map(s => ({
        label: s.textContent.trim(), tabIndex: s.tabIndex, cls: s.className,
        heading: (() => { let e = s.parentElement.previousElementSibling; while (e && !e.classList.contains('muted')) e = e.previousElementSibling; return e ? e.textContent.trim() : null; })(),
        title: s.getAttribute('title') }))""")
    rep["lanes"] = lanes
    pg.mouse.move(5, 5); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/_dlg-off.png")
    hov = {}
    for label in ["Law", "Press collection", "Wikipedia / Wikimedia", "Chain of custody", "Local AI install & weights"]:
        sp = pg.locator("#net-consent-lanes span.oo-tip-target", has_text=label).first
        for attempt, rest in enumerate((800, 1500, 2500)):
            sp.hover(); pg.wait_for_timeout(rest)
            st = pg.evaluate(TIP)
            shot = f"{OUT}/_hov-{label[:6].replace(' ', '_')}-{attempt}.png"
            pg.screenshot(path=shot)
            st["pixel_diff"] = diff(shot, f"{OUT}/_dlg-off.png", st["rect"])
            hov.setdefault(label, []).append({"rest_ms": rest, **st})
            pg.mouse.move(5, 5); pg.wait_for_timeout(400)
    rep["dialog_hovers"] = hov
    # a single clear evidence screenshot: Law hovered
    pg.locator("#net-consent-lanes span.oo-tip-target", has_text="Law").first.hover(); pg.wait_for_timeout(1000)
    pg.screenshot(path=f"{OUT}/H-P1-en-law-hover.png")
    rep["law_hover_final"] = pg.evaluate(TIP)

    # ---- DIAGNOSIS of the proposed fix (not a pass claim): re-parent the bubble into the open dialog ----
    pg.mouse.move(5, 5); pg.wait_for_timeout(400)
    pg.evaluate("() => document.getElementById('net-consent').appendChild(document.getElementById('oo-tip'))")
    pg.locator("#net-consent-lanes span.oo-tip-target", has_text="Law").first.hover(); pg.wait_for_timeout(1000)
    fx = pg.evaluate(TIP)
    pg.screenshot(path=f"{OUT}/H-P1-en-law-hover-FIXPROBE.png")
    fx["pixel_diff"] = diff(f"{OUT}/H-P1-en-law-hover-FIXPROBE.png", f"{OUT}/_dlg-off.png", fx["rect"])
    rep["fix_probe_tip_inside_dialog"] = fx
    pg.mouse.move(5, 5); pg.wait_for_timeout(300)
    pg.evaluate("() => document.body.appendChild(document.getElementById('oo-tip'))")   # restore

    # ---- keyboard: where does Tab go inside the modal? ----
    seq = []
    for i in range(10):
        pg.keyboard.press("Tab"); pg.wait_for_timeout(150)
        seq.append(pg.evaluate("() => { const a = document.activeElement; return (a.id ? '#' + a.id : a.tagName) + (a.textContent ? ':' + a.textContent.trim().slice(0, 20) : ''); }"))
    rep["tab_sequence"] = seq
    rep["tip_after_tabbing"] = pg.evaluate("() => document.getElementById('oo-tip').classList.contains('show')")
    pg.click("#net-consent-cancel"); pg.wait_for_timeout(600)
    rep["network_after_cancel"] = api(pg, "/api/system/network")

    # ---- other modal dialogs with titled content? count the app-wide reach of the same cause ----
    rep["dialogs_with_titled_children"] = pg.evaluate("""() => [...document.querySelectorAll('dialog')].map(d => ({
        id: d.id, titled: d.querySelectorAll('[title], .oo-tip-target').length })).filter(x => x.titled > 0)""")

    # ---- Discover by topic: tick via the REAL settings UI, read the popup heading, revert ----
    rep["safety_before"] = {k: v for k, v in (api(pg, "/api/safety/settings") or {}).items() if k in ("discovery_external_enabled", "fetch_mode")}
    browser_done = True
    br.close()

with open(f"{OUT}/recheck1.json", "w", encoding="utf-8") as fh:
    json.dump(rep, fh, ensure_ascii=False, indent=1)
print(json.dumps({k: rep[k] for k in ("lock_before", "lock_after", "network_start", "network_after_cancel", "tab_sequence", "tip_after_tabbing", "dialogs_with_titled_children")}, ensure_ascii=False, indent=1))
print("CONTROL", {k: rep["control_plane_hover"][k] for k in ("shown", "opacity", "topElementAtCentre", "topIsTip", "pixel_diff", "parent")})
for lab, arr in rep["dialog_hovers"].items():
    for a in arr:
        print(lab, a["rest_ms"], a["shown"], a["opacity"], a["topElementAtCentre"], a["topIsTip"], a["dialogModal"], a["pixel_diff"], a["text"][:60])
f = rep["fix_probe_tip_inside_dialog"]
print("FIXPROBE", f["shown"], f["inDialog"], f["topElementAtCentre"], f["topIsTip"], f["pixel_diff"])
print("errors", rep["page_errors"], rep["console_errors"], rep["http_errors"])
