#!/usr/bin/env python3
"""Row J click-through walk (export folder + completion panel), staged.

Usage: walk.py <stage> [port]
Each stage writes results/<stage>.json with observations + the run's errors.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

STAGE = sys.argv[1]
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8818
URL = f"http://127.0.0.1:{PORT}"
ROOT = Path("/tmp/claude-0/walk/J")
SHOTS = ROOT / "shots"
RES = ROOT / "results"
SHOTS.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)
EXPORTS = Path(os.environ.get("J_EXPORTS", str(ROOT / "exports")))
PASS = "walk-pass-2026"
EXPORT_PASS = os.environ.get("J_EXPORT_PASS", "walk-pass-2026")

obs: dict = {"stage": STAGE, "port": PORT, "steps": {}}
page_errors: list[str] = []
console_errors: list[str] = []
http_errors: list[str] = []
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")


def note(key, val):
    obs["steps"][key] = val
    print(f"[{key}] {json.dumps(val, ensure_ascii=False)[:1500]}")


def attach(page):
    page.on("pageerror", lambda e: page_errors.append(f"{page.url} :: {e}"))
    page.on("console", lambda m: console_errors.append(f"{page.url} :: {m.text}") if m.type == "error" else None)
    page.on("response", lambda r: http_errors.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)


def unlock_if_needed(page):
    page.goto(URL + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if page.locator("#pw").count() and page.locator("#pw").is_visible():
        page.fill("#pw", PASS)
        page.click("#btn-unlock")
        page.wait_for_url(re.compile(r".*/#home.*|.*/$"), timeout=120000)
        page.wait_for_timeout(2500)
        obs.setdefault("unlocked_via_form", True)
    page.wait_for_timeout(1500)
    close_wizard(page)


def close_wizard(page):
    for _ in range(3):
        open_ = page.evaluate("() => { const w = document.getElementById('guide-wizard'); return !!(w && w.open); }")
        if not open_:
            return
        page.evaluate("() => document.getElementById('guide-wizard').close()")
        page.wait_for_timeout(400)


def set_lang(page, lang):
    close_wizard(page)
    page.click("#lang-switch")
    page.wait_for_timeout(300)
    page.click(f"#lang-menu [data-lang={lang}]")
    page.wait_for_function(f"() => document.documentElement.lang === '{lang}'", timeout=15000)
    page.wait_for_timeout(1200)


def open_export(page):
    # Settings (sidebar foot) -> Data & backup -> Export / Back up…
    if page.viewport_size and page.viewport_size["width"] <= 600:
        page.click("#hamburger")
        page.wait_for_timeout(600)
    page.click(".sb-foot button[onclick=\"showTab('settings')\"]")
    page.wait_for_timeout(800)
    page.click('#set-subtabs button[data-tab="data"]')
    page.wait_for_timeout(800)
    page.click('#set-data button[onclick="openUnifiedExport()"]')
    page.wait_for_function("() => document.getElementById('ux-export').open", timeout=10000)
    # wait for inventory to load
    page.wait_for_function(
        "() => document.querySelector('#ux-checklist input#ux-c-corpus') !== null", timeout=30000)
    page.wait_for_timeout(1500)


def close_export(page):
    page.click("#ux-export .row button.secondary:has-text('Close'), #ux-export button[onclick*=\"ux-export').close\"]")
    page.wait_for_timeout(500)


def hover_text(page, locator):
    loc = page.locator(locator).first
    loc.scroll_into_view_if_needed()
    page.mouse.move(0, 0)
    page.wait_for_timeout(150)
    loc.hover()
    page.wait_for_timeout(400)
    txt = page.evaluate("() => { const t = document.getElementById('oo-tip'); return t && t.classList.contains('show') ? t.textContent : null; }")
    title = page.evaluate("(s) => { const e = document.querySelector(s); return e ? (e.getAttribute('title') || e.dataset.ooTip || '') : null; }", locator)
    page.mouse.move(0, 0)
    page.wait_for_timeout(200)
    return {"bubble": txt, "title_attr": title}


def checklist(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#ux-checklist label')).map(l => {
        const i = l.querySelector('input');
        return {text: l.textContent.trim().replace(/\\s+/g,' '), id: i && i.id, checked: i && i.checked,
                disabled: i && i.disabled, cats: i && i.dataset.cats, title: l.getAttribute('title') || l.dataset.ooTip || ''};
    })""")


def dialog_text(page):
    return page.evaluate("() => document.getElementById('ux-export').innerText")


def panel(page):
    return page.evaluate("""() => {
      const h = document.getElementById('ux-summary');
      if (!h) return null;
      const first = h.querySelector(':scope > div.note');
      const rows = Array.from(h.querySelectorAll(':scope > div:nth-child(2) > div.row')).map(r => {
        const sp = r.querySelectorAll(':scope > span');
        return {label: sp[0] && sp[0].textContent.trim(), label_title: sp[0] && (sp[0].getAttribute('title') || sp[0].dataset.ooTip || ''),
                value: sp[1] && sp[1].innerText.trim().replace(/\\s+/g,' '),
                sub_titles: sp[1] ? Array.from(sp[1].querySelectorAll('[title],[data-oo-tip]')).map(e => e.getAttribute('title') || e.dataset.ooTip) : []};
      });
      return {
        first_text: first && first.textContent.trim(),
        first_is_err: first && first.classList.contains('err'),
        first_color: first && getComputedStyle(first).color,
        first_title: first && (first.getAttribute('title') || first.dataset.ooTip || ''),
        rows,
        caveat: (h.querySelector('.card-caveat') || {}).textContent || null,
        summary_line: (Array.from(h.querySelectorAll(':scope > div.muted')).pop() || {}).textContent || null,
        all_text: h.innerText,
      };
    }""")


def progress_text(page):
    return page.evaluate("() => document.getElementById('ux-progress').innerText")


def run_export(page, dest_parent, *, verify=True, untick_large=True, sample_progress=True):
    page.fill("#ux-dest", dest_parent)
    page.fill("#ux-pass", EXPORT_PASS)
    if untick_large:
        for cid in ("ux-c-models", "ux-c-maps", "ux-c-wiki"):
            loc = page.locator(f"#{cid}")
            if loc.count() and loc.is_checked() and not loc.is_disabled():
                loc.uncheck()
    vb = page.locator("#ux-verify")
    if vb.is_checked() != verify:
        vb.set_checked(verify)
    clicked_at = time.time()
    local_clicked = time.strftime("%Y%m%d%H%M", time.localtime(clicked_at))
    page.click("#ux-run")
    seen = []
    last = None
    t0 = time.time()
    while time.time() - t0 < 300:
        txt = progress_text(page)
        if txt != last:
            seen.append({"t": round(time.time() - t0, 2), "text": txt})
            last = txt
        done = page.evaluate("() => !document.getElementById('ux-run').disabled")
        if done and ("Backup complete" in txt or "failed" in txt.lower() or "Sauvegarde terminée" in txt
                     or "échec" in txt.lower() or "→" in txt):
            # wait for panel render
            page.wait_for_timeout(1200)
            break
        page.wait_for_timeout(60 if sample_progress else 300)
    final = progress_text(page)
    return {"clicked_local_minute": local_clicked, "clicked_epoch": clicked_at,
            "progress_seen": seen, "final_progress": final, "elapsed_s": round(time.time() - t0, 2)}


def junk_scan(text):
    return sorted(set(m.group(0) for m in JUNK.finditer(text or "")))


def finish(ctx, br):
    obs["page_errors"] = page_errors
    obs["console_errors"] = console_errors
    obs["http_errors"] = http_errors
    (RES / f"{STAGE}.json").write_text(json.dumps(obs, indent=2, ensure_ascii=False))
    ctx.close()
    br.close()


def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        vw = {"width": 1440, "height": 950}
        if STAGE.startswith("phone"):
            vw = {"width": 375, "height": 800}
        ctx = br.new_context(viewport=vw)
        page = ctx.new_page()
        attach(page)
        try:
            unlock_if_needed(page)
            globals()["stage_" + STAGE](page)
        except Exception as e:  # noqa: BLE001
            obs["exception"] = repr(e)
            try:
                page.screenshot(path=str(SHOTS / f"J-{STAGE}-exception.png"))
            except Exception:
                pass
            raise
        finally:
            finish(ctx, br)


# ---------------------------------------------------------------------------- stages
def stage_j1(page):
    note("lang", page.evaluate("() => document.documentElement.lang"))
    note("sidebar_version", page.evaluate("() => (document.getElementById('version')||{}).textContent"))
    open_export(page)
    note("inv_status", page.locator("#ux-inv-status").inner_text())
    note("checklist", checklist(page))
    note("dialog_text", dialog_text(page))
    note("hint_hover", hover_text(page, "#ux-export .hint[title]"))
    note("verify_checked", page.locator("#ux-verify").is_checked())
    note("verify_hover", hover_text(page, "#ux-export label.switch:has(#ux-verify)"))
    # Living sources row: find the label whose text starts with Living sources
    liv = page.evaluate("""() => { const ls = Array.from(document.querySelectorAll('#ux-checklist label'));
       const i = ls.findIndex(l => /Living sources/.test(l.textContent)); return i; }""")
    note("living_index", liv)
    if liv >= 0:
        note("living_hover", hover_text(page, f"#ux-checklist label:nth-of-type({liv + 1})"))
    note("inside_hover", hover_text(page, "#ux-checklist label:has(#ux-c-inside)"))
    sched = re.findall(r"(?i)\b(schedul\w*|repeat\w*|timer|daily|automatic\w*|every day|weekly|cron)\b", dialog_text(page))
    note("schedule_words_in_dialog", sched)
    note("dialog_inputs", page.evaluate("() => Array.from(document.querySelectorAll('#ux-export input, #ux-export select')).map(e => e.id + ':' + e.type)"))
    note("junk_dialog", junk_scan(dialog_text(page)))
    page.screenshot(path=str(SHOTS / "J-J1-dialog-en.png"))
    # API cross-check
    inv = page.evaluate("async () => (await fetch('/api/backup/inventory')).json()")
    note("inventory_api", inv)
    close_export(page)
    # Help -> User Manual -> find 'never scheduled'
    page.click("button.icon-btn[onclick=\"showTab('help')\"]")
    page.wait_for_function("() => { const p = document.getElementById('doc-prose'); return p && p.innerText.length > 5000; }", timeout=30000)
    note("help_active_doc", page.evaluate("() => (document.querySelector('.doc-link.active')||{}).textContent"))
    page.fill("#doc-find", "never scheduled")
    page.wait_for_timeout(1500)
    marks = page.evaluate("""() => Array.from(document.querySelectorAll('#doc-prose mark')).map(m => {
        const blk = m.closest('li,p') || m.parentElement; return blk.innerText.slice(0, 300); })""")
    note("manual_marks", marks)
    page.screenshot(path=str(SHOTS / "J-J1-manual-en.png"))


def stage_j2(page):
    open_export(page)
    note("checklist_before", checklist(page))
    r = run_export(page, str(EXPORTS))
    note("run", r)
    p = panel(page)
    note("panel", p)
    # hovers on the panel
    note("verdict_hover", hover_text(page, "#ux-summary > div.note"))
    lic_titles = page.evaluate("""() => { const rows = Array.from(document.querySelectorAll('#ux-summary div.row'));
        const r = rows.find(x => /Licen/.test(x.textContent)); if (!r) return null;
        return Array.from(r.querySelectorAll('div')).map(d => ({text: d.textContent, title: d.getAttribute('title') || d.dataset.ooTip}))}""")
    note("licence_lines", lic_titles)
    enc_title = page.evaluate("""() => { const rows = Array.from(document.querySelectorAll('#ux-summary div.row'));
        const r = rows.find(x => /Encryption/.test(x.textContent)); if (!r) return null; const s = r.querySelector('span');
        return s.getAttribute('title') || s.dataset.ooTip}""")
    note("encryption_row_title", enc_title)
    note("junk_panel", junk_scan((p or {}).get("all_text", "") + progress_text(page)))
    note("sidebar_version", page.evaluate("() => (document.getElementById('version')||{}).textContent"))
    page.locator("#ux-summary").scroll_into_view_if_needed()
    page.screenshot(path=str(SHOTS / "J-J2-panel-en.png"), full_page=False)
    # dialog-only screenshot
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J2-dialog-panel-en.png"))
    # server facts for the dest
    dest = re.search(r"→\s*(\S+)", r["final_progress"])
    if dest:
        d = dest.group(1)
        facts = page.evaluate("async (d) => (await fetch('/api/backup/export-summary?dir=' + encodeURIComponent(d))).json()", d)
        note("server_facts", facts)


def stage_j4(page):
    open_export(page)
    runs = []
    for i in range(3):
        r = run_export(page, str(EXPORTS), sample_progress=False)
        p = panel(page)
        runs.append({"run": r, "verdict": p and p["first_text"], "first_is_err": p and p["first_is_err"],
                     "volumes_row": p and next((x["value"] for x in p["rows"] if x["label"] == "Encrypted volumes"), None),
                     "summary_line": p and p["summary_line"]})
        print(runs[-1])
    note("runs", runs)
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J4-dialog-after-3-en.png"))


def stage_j5(page):
    # (1) reload + reopen without exporting
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    close_wizard(page)
    open_export(page)
    page.wait_for_timeout(2500)
    note("reopen_progress", progress_text(page))
    note("reopen_panel", panel(page))
    note("reopen_verify_checked", page.locator("#ux-verify").is_checked())
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J5-reopen-en.png"))
    close_export(page)
    for lang in ("fr", "ar", "zh"):
        set_lang(page, lang)
        open_export(page)
        page.wait_for_timeout(2500)
        d = {
            "dir": page.evaluate("() => document.documentElement.dir || getComputedStyle(document.documentElement).direction"),
            "dialog_direction": page.evaluate("() => getComputedStyle(document.getElementById('ux-export')).direction"),
            "dialog_text_align": page.evaluate("() => getComputedStyle(document.getElementById('ux-inv-status')).textAlign"),
            "inv_status": page.locator("#ux-inv-status").inner_text(),
            "checklist": checklist(page),
            "dialog_text": dialog_text(page),
            "hint_hover": hover_text(page, "#ux-export .hint[title]"),
            "verify_hover": hover_text(page, "#ux-export label.switch:has(#ux-verify)"),
            "progress": progress_text(page),
            "panel": panel(page),
        }
        liv = page.evaluate("""() => Array.from(document.querySelectorAll('#ux-checklist label')).findIndex(l => l.querySelector('input') && l.querySelector('input').disabled && !/ux-c-inside/.test(l.querySelector('input').id) && /\\(\\d/.test(l.textContent) && !l.querySelector('#ux-c-corpus'))""")
        if liv >= 0:
            d["living_hover"] = hover_text(page, f"#ux-checklist label:nth-of-type({liv + 1})")
        try:
            d["verdict_hover"] = hover_text(page, "#ux-summary > div.note")
        except Exception as e:  # noqa: BLE001
            d["verdict_hover"] = repr(e)
        rows_titles = page.evaluate("""() => Array.from(document.querySelectorAll('#ux-summary div.row > span[title], #ux-summary div.row > span[data-oo-tip]')).map(s => [s.textContent.trim(), s.getAttribute('title') || s.dataset.ooTip])""")
        d["row_label_titles"] = rows_titles
        d["junk"] = junk_scan(d["dialog_text"])
        note(f"lang_{lang}", d)
        page.locator("#ux-export").screenshot(path=str(SHOTS / f"J-J5-dialog-{lang}.png"))
        if lang == "fr":
            r = run_export(page, str(EXPORTS))
            note("fr_run", r)
            p = panel(page)
            note("fr_panel", p)
            note("fr_panel_hover_verdict", hover_text(page, "#ux-summary > div.note"))
            page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J5-export-fr.png"))
        close_export(page)
    set_lang(page, "en")
    note("back_to_en", page.evaluate("() => document.documentElement.lang"))


def stage_j6(page):
    open_export(page)
    r = run_export(page, str(EXPORTS), verify=False)
    note("run", r)
    p = panel(page)
    note("panel", p)
    note("verdict_hover", hover_text(page, "#ux-summary > div.note"))
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J6-noverify-en.png"))
    # close and reopen WITHOUT reload: does the verify box stay unticked? (note 8)
    close_export(page)
    open_export(page)
    page.wait_for_timeout(2500)
    note("reopen_no_reload_verify_checked", page.locator("#ux-verify").is_checked())
    note("reopen_no_reload_panel_first", (panel(page) or {}).get("first_text"))
    close_export(page)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    close_wizard(page)
    open_export(page)
    page.wait_for_timeout(2500)
    note("reload_progress", progress_text(page))
    rp = panel(page)
    note("reload_panel", rp)
    note("reload_verify_checked", page.locator("#ux-verify").is_checked())
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J6-reload-en.png"))


def stage_phone(page):
    open_export(page)
    page.wait_for_timeout(2500)
    sw = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    note("phone_scroll", sw)
    clipped = page.evaluate("""() => { const out = [];
      document.querySelectorAll('#ux-export *').forEach(e => { const r = e.getBoundingClientRect();
        if (r.width && (r.right > window.innerWidth + 1 || r.left < -1)) out.push((e.id || e.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right) + ' ' + (e.textContent||'').trim().slice(0,60)); });
      const d = document.getElementById('ux-export'); return {dialog_scrollW: d.scrollWidth, dialog_clientW: d.clientWidth, overflow: out.slice(0, 30)}; }""")
    note("phone_clipped", clipped)
    note("phone_panel", panel(page))
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-phone-dialog-en.png"))
    page.screenshot(path=str(SHOTS / "J-phone-viewport-en.png"))


def stage_probe(page):
    note("lang", page.evaluate("() => document.documentElement.lang"))
    open_export(page)
    note("checklist", checklist(page))


def stage_j5b(page):
    for lang in ("fr", "ar", "zh"):
        set_lang(page, lang)
        open_export(page)
        page.wait_for_timeout(2500)
        d = {"living_hover": hover_text(page, "#ux-checklist label:has(#ux-c-lanes)"),
             "living_label": page.locator("#ux-checklist label:has(#ux-c-lanes)").inner_text(),
             "dest_code_dir": page.evaluate("() => { const c = document.querySelector('#ux-summary code'); return c ? [getComputedStyle(c).direction, getComputedStyle(c).unicodeBidi, c.textContent] : null; }"),
             "dest_input_dir": page.evaluate("() => { const i = document.getElementById('ux-dest'); return [getComputedStyle(i).direction, i.getAttribute('dir')]; }"),
             }
        note(f"j5b_{lang}", d)
        # scroll the dialog to the bottom and screenshot the lower half of the panel
        page.evaluate("() => { const d = document.getElementById('ux-export'); d.scrollTop = d.scrollHeight; }")
        page.wait_for_timeout(400)
        page.locator("#ux-export").screenshot(path=str(SHOTS / f"J-J5-panel-bottom-{lang}.png"))
        close_export(page)
    set_lang(page, "en")
    note("back_to_en", page.evaluate("() => document.documentElement.lang"))


def stage_phone2(page):
    open_export(page)
    page.wait_for_timeout(2500)
    info = page.evaluate("""() => { const d = document.getElementById('ux-export'); const r = d.getBoundingClientRect();
      const pts = [[187, 770],[187,785],[100,790],[300,790]].map(([x,y]) => { const e = document.elementFromPoint(x,y); return [x,y, e ? (e.id || e.className || e.tagName) : null, e ? (e.closest('dialog') ? e.closest('dialog').id : 'NOT-IN-DIALOG') : null, e ? (e.textContent||'').trim().slice(0,80) : null]; });
      return {rect: [r.top, r.bottom, r.height], scrollH: d.scrollHeight, clientH: d.clientHeight, pts}; }""")
    note("phone2_info", info)
    page.screenshot(path=str(SHOTS / "J-phone2-top-en.png"))
    for i, frac in enumerate((0.5, 1.0)):
        page.evaluate("(f) => { const d = document.getElementById('ux-export'); d.scrollTop = d.scrollHeight * f; }", frac)
        page.wait_for_timeout(500)
        page.screenshot(path=str(SHOTS / f"J-phone2-scroll{i}-en.png"))
    note("phone_scroll_after", page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"))


def pick_folder(page, target):
    page.click("#ux-export button[onclick*=\"ooFolderPicker('ux-dest'\"]")
    page.wait_for_function("() => document.getElementById('folder-picker').open", timeout=10000)
    page.wait_for_timeout(800)
    start = page.locator("#fp-path").inner_text()
    trail = [start]
    for _ in range(12):
        if page.locator("#fp-path").inner_text() == "/":
            break
        page.locator("#fp-list .fp-row").first.click()  # the Parent folder row is first
        page.wait_for_timeout(500)
        trail.append(page.locator("#fp-path").inner_text())
    for part in [x for x in target.split("/") if x]:
        rows = page.locator("#fp-list .fp-row")
        hit = None
        for i in range(rows.count()):
            if rows.nth(i).inner_text().replace("\U0001F4C1", "").strip() == part:
                hit = rows.nth(i); break
        if hit is None:
            raise RuntimeError(f"folder {part!r} not listed at {page.locator('#fp-path').inner_text()}")
        hit.click()
        page.wait_for_timeout(500)
        trail.append(page.locator("#fp-path").inner_text())
    shot = SHOTS / "J-J7-folderpicker-en.png"
    page.locator("#folder-picker").screenshot(path=str(shot))
    use_disabled = page.locator("#fp-use").is_disabled()
    page.click("#fp-use")
    page.wait_for_timeout(500)
    return {"start": start, "trail": trail, "use_disabled": use_disabled, "dest_value": page.locator("#ux-dest").input_value()}


def stage_j7(page):
    open_export(page)
    note("checklist_before", checklist(page))
    note("models_hover", hover_text(page, "#ux-checklist label:has(#ux-c-models)"))
    note("inside_disabled_with_models_ticked", page.locator("#ux-c-inside").is_disabled())
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J7-dialog-before-en.png"))
    note("picker", pick_folder(page, "/tmp/claude-0/walk/J/drive"))
    page.fill("#ux-pass", EXPORT_PASS)
    # keep LLM models ticked, inside unticked, verify on
    assert page.locator("#ux-c-models").is_checked()
    assert not page.locator("#ux-c-inside").is_checked()
    assert page.locator("#ux-verify").is_checked()
    clicked = time.time()
    note("clicked_local_minute_paris", time.strftime("%Y%m%d%H%M", time.localtime(clicked)))
    page.click("#ux-run")
    seen, last, t0 = [], None, time.time()
    while time.time() - t0 < 300:
        txt = progress_text(page)
        if txt != last:
            seen.append({"t": round(time.time() - t0, 3), "text": txt}); last = txt
        if page.evaluate("() => !document.getElementById('ux-run').disabled") and "→" in txt:
            page.wait_for_timeout(1500); break
        page.wait_for_timeout(40)
    note("progress_seen", seen)
    p = panel(page)
    note("panel", p)
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J7-panel-top-en.png"))
    page.evaluate("() => { const d = document.getElementById('ux-export'); d.scrollTop = d.scrollHeight; }")
    page.wait_for_timeout(400)
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J7-panel-bottom-en.png"))
    note("sidebar_version", page.evaluate("() => (document.getElementById('version')||{}).textContent"))
    # NOTE (7): a later corpus-only export in the same app session, then reload + reopen
    page.locator("#ux-c-models").uncheck()
    r2 = run_export(page, "/tmp/claude-0/walk/J/drive", untick_large=True, sample_progress=False)
    note("second_corpus_only_run", r2)
    note("second_panel_first", (panel(page) or {}).get("first_text"))
    close_export(page)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    close_wizard(page)
    open_export(page)
    page.wait_for_timeout(3000)
    note("reopen_progress_after_two", progress_text(page))
    rp = panel(page)
    note("reopen_panel_after_two", rp)
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-J7-reopen-after-corpus-only-en.png"))
    st = page.evaluate("async () => ({vol: await (await fetch('/api/backup/v2/volumes/status')).json(), folder: await (await fetch('/api/backup/folder/status')).json()})")
    note("job_status", st)


def stage_plain(page):
    page.screenshot(path=str(SHOTS / "J-plain-landing-en.png"))
    open_export(page)
    note("checklist", checklist(page))
    r = run_export(page, "/tmp/claude-0/walk/J/exports-plain")
    note("run", r)
    p = panel(page)
    note("panel", p)
    enc = page.evaluate("""() => { const rows = Array.from(document.querySelectorAll('#ux-summary div.row'));
        const r = rows.find(x => /Encryption/.test(x.textContent)); if (!r) return null; const s = r.querySelectorAll('span');
        return [s[1] && s[1].textContent, s[0].getAttribute('title') || s[0].dataset.ooTip]}""")
    note("encryption_row", enc)
    note("encryption_hover", hover_text(page, "#ux-summary div.row:has-text('Encryption') > span.muted"))
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-plain-panel-en.png"))


def stage_reloadmid(page):
    open_export(page)
    page.fill("#ux-dest", "/tmp/claude-0/walk/J/exports-reload")
    page.fill("#ux-pass", EXPORT_PASS)
    page.click("#ux-run")
    page.wait_for_function("() => /Corpus/.test(document.getElementById('ux-progress').innerText)", timeout=15000)
    note("progress_at_reload", progress_text(page))
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    close_wizard(page)
    open_export(page)
    page.wait_for_timeout(3000)
    note("reopen_progress", progress_text(page))
    note("reopen_panel", panel(page))
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-reloadmid-reopen-en.png"))


if __name__ == "__main__":
    main()
