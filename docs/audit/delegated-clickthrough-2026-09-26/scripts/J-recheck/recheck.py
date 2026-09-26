#!/usr/bin/env python3
"""Row J independent recheck of the walker's defects. Usage: recheck.py <stage> [port]"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

STAGE = sys.argv[1]
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8820
URL = f"http://127.0.0.1:{PORT}"
ROOT = Path("/tmp/claude-0/walk/J-recheck")
SHOTS = ROOT / "shots"
RES = ROOT / "results"
SHOTS.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)
PASS = "walk-pass-2026"

obs: dict = {"stage": STAGE, "port": PORT, "steps": {}}
page_errors: list[str] = []
console_errors: list[str] = []
http_errors: list[str] = []


def note(key, val):
    obs["steps"][key] = val
    print(f"[{key}] {json.dumps(val, ensure_ascii=False)[:2000]}", flush=True)


def attach(page):
    page.on("pageerror", lambda e: page_errors.append(f"{page.url} :: {e}"))
    page.on("console", lambda m: console_errors.append(f"{page.url} :: {m.text}") if m.type == "error" else None)
    page.on("response", lambda r: http_errors.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)


def dismiss_coach(page):
    try:
        if page.locator("#net-coach-dismiss").is_visible():
            page.click("#net-coach-dismiss")
            page.wait_for_timeout(300)
    except Exception:
        pass


def close_wizard(page):
    dismiss_coach(page)
    for _ in range(3):
        if not page.evaluate("() => { const w = document.getElementById('guide-wizard'); return !!(w && w.open); }"):
            return
        page.evaluate("() => document.getElementById('guide-wizard').close()")
        page.wait_for_timeout(400)


def unlock_if_needed(page):
    page.goto(URL + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if page.locator("#pw").count() and page.locator("#pw").is_visible():
        page.fill("#pw", PASS)
        page.click("#btn-unlock")
        page.wait_for_url(re.compile(r".*/#home.*|.*/$"), timeout=120000)
        page.wait_for_timeout(2500)
        obs["unlocked_via_form"] = True
    page.wait_for_timeout(1500)
    close_wizard(page)


def set_lang(page, lang):
    close_wizard(page)
    page.click("#lang-switch")
    page.wait_for_timeout(300)
    page.click(f"#lang-menu [data-lang={lang}]")
    page.wait_for_function(f"() => document.documentElement.lang === '{lang}'", timeout=15000)
    page.wait_for_timeout(1200)


def open_export(page):
    close_wizard(page)
    if page.viewport_size and page.viewport_size["width"] <= 600:
        page.click("#hamburger")
        page.wait_for_timeout(600)
    page.click(".sb-foot button[onclick=\"showTab('settings')\"]")
    page.wait_for_timeout(800)
    page.click('#set-subtabs button[data-tab="data"]')
    page.wait_for_timeout(800)
    page.click('#set-data button[onclick="openUnifiedExport()"]')
    page.wait_for_function("() => document.getElementById('ux-export').open", timeout=10000)
    page.wait_for_function("() => document.querySelector('#ux-checklist input#ux-c-corpus') !== null", timeout=30000)
    page.wait_for_timeout(2500)


def close_export(page):
    page.evaluate("() => document.getElementById('ux-export').close()")
    page.wait_for_timeout(400)


def checklist(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#ux-checklist label')).map(l => {
        const i = l.querySelector('input');
        return {text: l.textContent.trim().replace(/\\s+/g,' '), id: i && i.id, checked: i && i.checked,
                disabled: i && i.disabled, title: l.getAttribute('title') || ''};
    })""")


def panel(page):
    return page.evaluate("""() => {
      const h = document.getElementById('ux-summary');
      if (!h) return null;
      const first = h.querySelector(':scope > div.note');
      const rows = Array.from(h.querySelectorAll('div.row')).map(r => {
        const sp = r.querySelectorAll(':scope > span');
        return {label: sp[0] && sp[0].textContent.trim(), label_title: sp[0] && (sp[0].getAttribute('title') || ''),
                value: sp[1] && sp[1].innerText.trim().replace(/\\s+/g,' ')};
      });
      return {first_text: first && first.textContent.trim(), first_is_err: first && first.classList.contains('err'),
              first_title: first && first.getAttribute('title'), rows, all_text: h.innerText};
    }""")


def progress_text(page):
    return page.evaluate("() => document.getElementById('ux-progress').innerText")


def start_phase_probe(page):
    # read-only: poll the job status endpoints from the page and keep every distinct phase
    page.evaluate("""() => {
      window.__phases = []; let last = '';
      window.__probe = setInterval(async () => {
        try {
          const s = await (await fetch('/api/backup/v2/volumes/status')).json();
          const p = (s.progress || {});
          const txt = document.getElementById('ux-progress').innerText;
          const k = s.state + '|' + p.phase + '|' + txt;
          if (k !== last) { last = k; window.__phases.push({t: Date.now(), state: s.state, phase: p.phase,
              vv: p.volumes_verified, vt: p.volumes_total, ui: txt}); }
        } catch (e) {}
      }, 25);
    }""")


def stop_phase_probe(page):
    return page.evaluate("() => { clearInterval(window.__probe); return window.__phases; }")


def run_export(page, parent, *, models=None, inside=False, verify=True, max_s=900):
    page.fill("#ux-dest", parent)
    page.fill("#ux-pass", PASS)
    if models is not None:
        loc = page.locator("#ux-c-models")
        if loc.count() and not loc.is_disabled():
            loc.set_checked(models)
    for cid in ("ux-c-maps", "ux-c-wiki"):
        loc = page.locator(f"#{cid}")
        if loc.count() and not loc.is_disabled() and loc.is_checked():
            loc.uncheck()
    ins = page.locator("#ux-c-inside")
    if ins.count() and not ins.is_disabled():
        ins.set_checked(inside)
    vb = page.locator("#ux-verify")
    if vb.is_checked() != verify:
        vb.set_checked(verify)
    seen, last = [], None
    t0 = time.time()
    page.click("#ux-run")
    while time.time() - t0 < max_s:
        txt = progress_text(page)
        if txt != last:
            seen.append({"t": round(time.time() - t0, 2), "text": txt})
            last = txt
        done = page.evaluate("() => !document.getElementById('ux-run').disabled")
        if done and ("→" in txt or "failed" in txt.lower()):
            page.wait_for_timeout(1500)
            break
        page.wait_for_timeout(40)
    final = progress_text(page)
    m = re.search(r"→\s*(\S+)", final)
    return {"progress_seen": seen, "final": final, "dest": m.group(1) if m else None}


def api_get(page, path):
    return page.evaluate("async (p) => { const r = await fetch(p); return {status: r.status, body: await r.json().catch(() => null)}; }", path)


def ls(d):
    return subprocess.run(["ls", "-la", str(d)], capture_output=True, text=True).stdout


def members(d):
    try:
        m = json.loads((Path(d) / "volumes.json").read_text())
        return [v.get("member") for v in m["volumes"]]
    except Exception as e:  # noqa: BLE001
        return repr(e)


# ------------------------------------------------------------------ stages
EXP = ROOT / "exports"


def stage_s1(page):
    """D1 (reopen names an older folder), D4 (first export without key), D6 phases."""
    EXP.mkdir(exist_ok=True)
    datadir = Path(os.environ.get("RC_DATA", str(ROOT / "data-enc")))
    note("keys_dir_before_first_export", sorted(p.name for p in (datadir / "keys").glob("*")) if (datadir / "keys").exists() else "absent")
    open_export(page)
    note("checklist", checklist(page))
    start_phase_probe(page)
    a = run_export(page, str(EXP), models=True)
    note("export_A_phases", stop_phase_probe(page))
    note("export_A", a)
    pa = panel(page)
    note("export_A_panel", pa)
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-D1-exportA-panel-en.png"))
    note("keys_dir_after_first_export", sorted(p.name for p in (datadir / "keys").glob("*")) if (datadir / "keys").exists() else "absent")
    note("export_A_listing", ls(a["dest"]))
    note("export_A_members", members(a["dest"]))
    # export B: corpus only
    start_phase_probe(page)
    b = run_export(page, str(EXP), models=False)
    note("export_B_phases", stop_phase_probe(page))
    note("export_B", b)
    note("export_B_panel", panel(page))
    note("export_B_members", members(b["dest"]))
    note("export_B_listing", ls(b["dest"]))
    # job statuses
    note("vol_status", api_get(page, "/api/backup/v2/volumes/status"))
    note("folder_status", api_get(page, "/api/backup/folder/status"))
    # reload + reopen
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    close_wizard(page)
    open_export(page)
    page.wait_for_timeout(2500)
    note("reopen_progress", progress_text(page))
    rp = panel(page)
    note("reopen_panel", rp)
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-D1-reopen-after-corpus-only-en.png"))
    note("facts_A", api_get(page, "/api/backup/export-summary?dir=" + a["dest"]))
    note("facts_B", api_get(page, "/api/backup/export-summary?dir=" + b["dest"]))
    note("summary_A_head", (Path(a["dest"]) / "BACKUP_SUMMARY.md").read_text()[:1500])


def stage_s2(page):
    """D2: reload during an export -> no BACKUP_SUMMARY.md."""
    parent = ROOT / "exports-reload"
    parent.mkdir(exist_ok=True)
    open_export(page)
    page.fill("#ux-dest", str(parent))
    page.fill("#ux-pass", PASS)
    for cid in ("ux-c-models", "ux-c-maps", "ux-c-wiki"):
        loc = page.locator(f"#{cid}")
        if loc.count() and not loc.is_disabled() and loc.is_checked():
            loc.uncheck()
    page.click("#ux-run")
    seen = []
    t0 = time.time()
    while time.time() - t0 < 30:
        txt = progress_text(page)
        seen.append(txt)
        if "Corpus" in txt:
            break
        page.wait_for_timeout(20)
    note("progress_at_reload", seen[-1] if seen else None)
    page.reload(wait_until="domcontentloaded")
    # wait for the job to finish server-side
    for _ in range(120):
        s = api_get(page, "/api/backup/v2/volumes/status")["body"]
        if s and s.get("state") in ("done", "error", "cancelled", "paused"):
            break
        page.wait_for_timeout(500)
    note("vol_status_after", {k: s.get(k) for k in ("state", "mode", "dest")})
    page.wait_for_timeout(1500)
    close_wizard(page)
    open_export(page)
    page.wait_for_timeout(3000)
    note("reopen_progress", progress_text(page))
    note("reopen_panel", panel(page))
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-D2-reopen-after-reload-en.png"))
    dirs = sorted(parent.iterdir())
    note("folders", [d.name for d in dirs])
    page.locator("#ux-export").screenshot(path=str(SHOTS / f"J-D2-reopen-{PORT}-en.png"))
    note("listing", ls(dirs[-1]))
    note("has_summary_file", (dirs[-1] / "BACKUP_SUMMARY.md").exists())
    note("facts_get", api_get(page, "/api/backup/export-summary?dir=" + str(dirs[-1])))
    # after a while, still no file?
    page.wait_for_timeout(5000)
    note("has_summary_file_after_wait", (dirs[-1] / "BACKUP_SUMMARY.md").exists())


def stage_s3(page):
    """D3 ar bidi, D7 English hovers, D9 fr/ar wording."""
    for lang in ("ar", "fr", "zh"):
        set_lang(page, lang)
        open_export(page)
        page.fill("#ux-dest", "/tmp/claude-0/walk/J-recheck/exports")
        page.wait_for_timeout(500)
        d = {
            "html_dir": page.evaluate("() => document.documentElement.dir"),
            "dest_dir_attr": page.evaluate("() => document.getElementById('ux-dest').getAttribute('dir')"),
            "dest_direction": page.evaluate("() => getComputedStyle(document.getElementById('ux-dest')).direction"),
            "hint": page.evaluate("() => { const h = document.querySelector('#ux-export .hint'); return h && {text: h.innerText, title: h.getAttribute('title'), dir: getComputedStyle(h).direction}; }"),
            "checklist": checklist(page),
            "progress": progress_text(page),
            "panel": panel(page),
            "summary_code_direction": page.evaluate("() => { const c = document.querySelector('#ux-summary code'); return c && {dir: getComputedStyle(c).direction, ub: getComputedStyle(c).unicodeBidi, text: c.textContent}; }"),
        }
        note(f"lang_{lang}", d)
        page.locator("#ux-export").screenshot(path=str(SHOTS / f"J-D3-dialog-{lang}.png"))
        if lang == "ar":
            # zoom on the hint + dest input
            try:
                page.locator("#ux-dest").screenshot(path=str(SHOTS / "J-D3-dest-input-ar.png"))
                page.locator("#ux-export .hint").first.screenshot(path=str(SHOTS / "J-D3-hint-ar.png"))
                page.locator("#ux-progress").screenshot(path=str(SHOTS / "J-D3-progress-ar.png"))
            except Exception as e:  # noqa: BLE001
                note("ar_zoom_err", repr(e))
        close_export(page)
    set_lang(page, "en")


def stage_s4(page):
    """D8 Help renderer: wrapped bullets split."""
    page.click("button.icon-btn[onclick=\"showTab('help')\"]")
    page.wait_for_function("() => { const p = document.getElementById('doc-prose'); return p && p.innerText.length > 5000; }", timeout=30000)
    page.fill("#doc-find", "never scheduled")
    page.wait_for_timeout(1500)
    info = page.evaluate("""() => {
      const m = document.querySelector('#doc-prose mark'); if (!m) return null;
      const li = m.closest('li');
      const next = li ? li.closest('ul,ol').nextElementSibling : null;
      return {li_text: li && li.innerText, li_tag: li && li.tagName,
              list_next_tag: next && next.tagName, list_next_text: next && next.innerText.slice(0, 200)};
    }""")
    note("never_scheduled", info)
    page.locator("#doc-prose mark").first.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "J-D8-manual-en.png"))


def stage_s5(page):
    """D5 plaintext wording."""
    parent = ROOT / "exports-plain"
    parent.mkdir(exist_ok=True)
    open_export(page)
    r = run_export(page, str(parent))
    note("run", r)
    p = panel(page)
    note("panel", p)
    enc = [x for x in p["rows"] if x["label"] == "Encryption"]
    note("encryption_row", enc)
    page.locator("#ux-export").screenshot(path=str(SHOTS / "J-D5-plain-panel-en.png"))
    txt = (Path(r["dest"]) / "BACKUP_SUMMARY.md").read_text()
    i = txt.find("## Encryption")
    note("summary_encryption_section", txt[i:i + 700])
    note("vol_manifest_corpus", json.loads((Path(r["dest"]) / "volumes.json").read_text()).get("corpus_member"))


def stage_s6(page):
    """D6: catch the verify-after-write re-read on a big set (blob carried inside)."""
    parent = ROOT / "exports-big"
    parent.mkdir(exist_ok=True)
    open_export(page)
    note("checklist", checklist(page))
    start_phase_probe(page)
    r = run_export(page, str(parent), models=True, inside=True)
    ph = stop_phase_probe(page)
    note("run", {k: r[k] for k in ("final", "dest")})
    note("progress_seen", r["progress_seen"])
    note("phases", ph)
    note("verifying_rows", [x for x in ph if x.get("phase") == "verifying"])
    note("panel_first", (panel(page) or {}).get("first_text"))


def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        ctx = br.new_context(viewport={"width": 1440, "height": 950})
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
            obs["page_errors"] = page_errors
            obs["console_errors"] = console_errors
            obs["http_errors"] = http_errors
            (RES / f"{STAGE}.json").write_text(json.dumps(obs, indent=2, ensure_ascii=False))
            ctx.close()
            br.close()


if __name__ == "__main__":
    main()
