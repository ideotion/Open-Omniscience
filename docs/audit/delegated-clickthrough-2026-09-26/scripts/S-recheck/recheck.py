"""Row S RECHECK -- independent reproduction of the walker's eight defects.

Real Chromium, real clicks, against a LOCKED encrypted throwaway served by the console
script from the repo root (port 8844). Reads of the API are for confirmation only.
Order matters: the read-only probes (F5, F2, F4, F6, F8-wrap) run before the one
mutation (Undo, F1/F8-microseconds); the merge probe (F3) writes nothing server-side.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://127.0.0.1:8844"
OUT = Path("/tmp/claude-0/walk/S-recheck")
SHOTS = OUT / "shots"
DL = OUT / "downloads"
SHOTS.mkdir(parents=True, exist_ok=True)
DL.mkdir(parents=True, exist_ok=True)
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
PASS = "walk-pass-2026"
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")

R: dict = {"steps": {}, "console_errors": [], "page_errors": [], "http_errors": [], "junk": []}
WHERE = {"v": "boot"}

INIT = """
(() => {
  window.__toasts = [];
  const hook = () => {
    const host = document.getElementById('toast');
    if (!host) { setTimeout(hook, 200); return; }
    new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes)
      if (n.nodeType === 1) window.__toasts.push({t: Date.now(), text: n.textContent}); })
      .observe(host, {childList: true});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', hook); else hook();
})();
"""


def save():
    (OUT / "raw_recheck.json").write_text(json.dumps(R, indent=2, ensure_ascii=False))


def step(k):
    return R["steps"].setdefault(k, {})


def attach(page):
    page.on("console", lambda m: R["console_errors"].append({"where": WHERE["v"], "text": m.text})
            if m.type == "error" else None)
    page.on("pageerror", lambda e: R["page_errors"].append({"where": WHERE["v"], "text": str(e)}))
    page.on("response", lambda r: R["http_errors"].append({"where": WHERE["v"], "url": r.url, "status": r.status})
            if r.status >= 400 else None)
    page.on("dialog", lambda d: d.dismiss())


def unlock(page):
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    if page.locator("#pw").count() and page.locator("#pw").is_visible():
        page.fill("#pw", PASS)
        page.click("#btn-unlock")
        page.wait_for_url(re.compile(r".*#home.*"), timeout=90000)
    page.wait_for_selector("#home-stats", timeout=90000)
    for _ in range(6):
        page.wait_for_timeout(500)
        if page.locator("#guide-wizard[open]").count():
            page.click("#gw-close")
        c = page.locator("#net-coach-dismiss")
        if c.count() and c.is_visible():
            c.click()


def api(page, path):
    return page.evaluate(f"async () => (await (await fetch({json.dumps(path)})).json())")


def open_quality(page):
    if not page.locator("#set-subtabs").is_visible():
        if page.locator("#hamburger").is_visible() and not page.locator("button[onclick=\"showTab('settings')\"]").is_visible():
            page.click("#hamburger")
            page.wait_for_timeout(500)
        page.click("button[onclick=\"showTab('settings')\"]")
    page.wait_for_selector("#set-subtabs", state="visible", timeout=15000)
    page.click("#set-subtabs button[data-tab='advanced']")
    page.wait_for_selector("details[data-adv='qualification'] > summary", state="visible", timeout=15000)
    d = page.locator("details[data-adv='qualification']")
    if not d.evaluate("e => e.open"):
        page.click("details[data-adv='qualification'] > summary")
    wait_loaded(page)


def wait_loaded(page):
    for sel in ("qual-state", "qual-admission", "qual-overlay", "qualify-bulk-status"):
        page.wait_for_function(
            f"() => {{ const e = document.getElementById('{sel}');"
            f" return e && e.textContent.trim() && !/^(Loading…|Chargement)/.test(e.textContent.trim()); }}",
            timeout=30000)
    page.wait_for_function("() => document.getElementById('qual-scope-count').textContent.trim().length > 0",
                           timeout=15000)
    page.wait_for_timeout(600)


def switch_lang(page, code):
    page.click("#lang-switch")
    page.wait_for_selector("#lang-menu:not([hidden])", timeout=5000)
    page.click(f"#lang-menu [data-lang='{code}']")
    page.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=15000)


def panel(page):
    return page.evaluate("""() => {
      const g = (id) => { const e = document.getElementById(id); return e ? e.innerText.trim() : null; };
      return {state: g('qual-state'), scope: g('qual-scope-count'), retired: g('qual-scope-retired'),
              retired_hidden: (document.getElementById('qual-scope-retired')||{}).hidden,
              enabled_hint: g('qual-enabled-hint'), criteria: g('qual-criteria'),
              admission: g('qual-admission'), overlay: g('qual-overlay'), bulk: g('qualify-bulk-status'),
              merge_out: g('qual-ov-merge-out'), lang: document.documentElement.lang};
    }""")


def shot(page, sel, name):
    loc = page.locator(sel)
    loc.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    loc.screenshot(path=str(SHOTS / name))


def junk(page, where, sel):
    txt = page.evaluate(f"() => {{ const e = document.querySelector({json.dumps(sel)}); return e ? e.innerText : ''; }}")
    for m in JUNK.finditer(txt or ""):
        R["junk"].append({"where": where, "sel": sel, "ctx": txt[max(0, m.start() - 50):m.end() + 50]})


def main():
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = br.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        attach(page)

        # ---------------------------------------------------------------- boot
        s = step("boot")
        WHERE["v"] = "en"
        unlock(page)
        s["url"] = page.url
        s["network"] = api(page, "/api/system/network")
        s["plane_fill"] = page.get_attribute("#net-plane", "fill")
        s["lang"] = page.evaluate("() => document.documentElement.lang")
        if s["lang"] != "en":
            switch_lang(page, "en")
            page.reload(wait_until="domcontentloaded"); unlock(page)
        save()

        # ---------------------------------------------------------------- F5 + baseline
        s = step("F5_retired_path")
        open_quality(page)
        en = panel(page)
        s["panel_en"] = en
        s["config_scope"] = api(page, "/api/sources/qualification/config").get("scope")
        s["set_subtabs"] = page.evaluate("() => Array.from(document.querySelectorAll('#set-subtabs button')).map(b => b.dataset.tab + ':' + b.innerText.trim())")
        s["adv_sections"] = page.evaluate("() => Array.from(document.querySelectorAll('#set-advanced details.adv-sec > summary .adv-sec-t')).map(e => e.innerText.trim())")
        s["admission_heading_parent_section"] = page.evaluate("""() => { const h = Array.from(document.querySelectorAll('#set-advanced h3')).find(x => /Admission audit/.test(x.textContent));
            const d = h && h.closest('details.adv-sec'); return d ? d.dataset.adv + ' / ' + d.querySelector('summary .adv-sec-t').innerText : null; }""")
        shot(page, "#qual-scope-retired", "S-F5-retired-line-en.png")
        junk(page, "en quality", "#qualification-panel")
        # F8 wrap probe (seeded rows, pre-mutation, en, 1440)
        s8 = step("F8_timestamp")
        s8["rows_en_1440"] = page.evaluate("""() => Array.from(document.querySelectorAll('#qual-admission .row')).map(r => {
            const ts = r.querySelector('span[dir=ltr]'); const info = r.children[0], act = r.children[1];
            return {text: r.innerText.replace(/\\s+/g,' ').trim(), ts: ts ? ts.textContent : null,
                    ts_line_boxes: ts ? ts.getClientRects().length : null,
                    info_w: Math.round(info.getBoundingClientRect().width), act_w: Math.round(act.getBoundingClientRect().width),
                    row_w: Math.round(r.getBoundingClientRect().width)}; })""")
        shot(page, "#qual-admission", "S-F8-admission-seeded-en.png")
        save()

        # ---------------------------------------------------------------- F2 live switch
        s = step("F2_live_switch")
        s["panel_open"] = page.locator("details[data-adv='qualification']").evaluate("e => e.open")
        n_req_before = len(R["http_errors"])
        switch_lang(page, "fr")
        WHERE["v"] = "fr-live"
        reads = {}
        for wait_ms in (1500, 5000, 10000):
            page.wait_for_timeout(wait_ms if wait_ms == 1500 else wait_ms - (1500 if wait_ms == 5000 else 5000))
            reads[f"after_{wait_ms}ms"] = panel(page)
        s["reads"] = reads
        fr = reads["after_10000ms"]
        def lines(x):
            return [l.strip() for l in "\n".join(v for v in x.values() if isinstance(v, str)).split("\n") if l.strip()]
        en_lines = set(lines(en))
        s["english_left_after_10s"] = [l for l in lines(fr) if l in en_lines and re.search(r"[A-Za-z]{4,}", l)]
        s["english_fragments"] = {
            "state_has_Collecting_now": "Collecting now" in (fr["state"] or ""),
            "state_has_Judged_so_far": "Judged so far" in (fr["state"] or ""),
            "scope_has_This_will_scrape": "This will scrape" in (fr["scope"] or ""),
            "admission_has_Showing": "Showing" in (fr["admission"] or ""),
            "admission_has_Collection_was": "Collection was" in (fr["admission"] or ""),
            "bulk_has_candidates_awaiting": "candidates awaiting" in (fr["bulk"] or ""),
            "hint_has_sources_per": "sources per collection pass" in (fr["enabled_hint"] or ""),
            "criteria_has_absolute_floor": "absolute floor" in (fr["criteria"] or ""),
        }
        # the keys exist in fr? (so it is a repaint gap, not a missing translation)
        s["fr_keys_present"] = page.evaluate("""() => { const T = (k) => (window.OOI18N && OOI18N.t) ? OOI18N.t(k) : null;
            return {'Collecting now': T('Collecting now'), 'Judged so far': T('Judged so far'), 'qualified': T('qualified'),
                    'This will scrape {n} sources (of {total} enabled).': T('This will scrape {n} sources (of {total} enabled).'),
                    'Showing {shown} of {total} admissions': T('Showing {shown} of {total} admissions'),
                    'Collection was': T('Collection was'), 'candidates awaiting qualification': T('candidates awaiting qualification'),
                    'sources per collection pass': T('sources per collection pass')}; }""")
        shot(page, "#qualification-panel", "S-F2-live-switch-fr.png")
        # does the same panel render French after a reload? (control)
        page.reload(wait_until="domcontentloaded"); unlock(page)
        WHERE["v"] = "fr-reload"
        open_quality(page)
        s["after_reload"] = panel(page)
        shot(page, "#qual-state", "S-F2-after-reload-fr.png")
        # back to en (live), then reload so the rest runs in en
        switch_lang(page, "en")
        page.reload(wait_until="domcontentloaded"); unlock(page)
        WHERE["v"] = "en"
        save()

        # ---------------------------------------------------------------- F4 Home strip
        s = step("F4_home")
        page.click("#navGroups button.nav-item[data-tab='home']")
        page.wait_for_function("() => document.querySelectorAll('#home-stats .s').length > 0", timeout=30000)
        page.wait_for_timeout(1500)
        s["home_items"] = page.evaluate("() => Array.from(document.querySelectorAll('#home-stats .s')).map(e => e.textContent.replace(/\\s+/g,' ').trim())")
        s["home_innerText"] = page.evaluate("() => document.getElementById('home-stats').innerText")
        s["db_stats_counts"] = api(page, "/api/database/stats").get("counts")
        s["qual_config_counts"] = api(page, "/api/sources/qualification/config").get("counts")
        shot(page, "#home-stats", "S-F4-home-strip-en.png")
        save()

        # ---------------------------------------------------------------- F6 Library tiles
        s = step("F6_library")
        page.click("#navGroups button.nav-item[data-tab='library']")
        page.wait_for_timeout(800)
        page.click("#library-views button[data-tab='storage']")
        page.wait_for_selector("#db-stats .stat", timeout=30000)
        page.wait_for_timeout(3000)
        s["tiles_en"] = page.evaluate("() => Array.from(document.querySelectorAll('#db-stats .stat')).map(e => e.querySelector('.k').textContent.trim())")
        shot(page, "#db-stats", "S-F6-library-tiles-en.png")
        save()

        # ---------------------------------------------------------------- F3 export / merge
        s = step("F3_merge")
        open_quality(page)
        page.locator("#qual-ov-export").scroll_into_view_if_needed()
        with page.expect_download(timeout=20000) as dl:
            page.click("#qual-ov-export")
        exp = DL / ("export-" + dl.value.suggested_filename)
        dl.value.save_as(str(exp))
        s["export_name"] = dl.value.suggested_filename
        s["export_head"] = exp.read_text()[:400]
        s["picker_accept"] = page.get_attribute("#qual-ov-files", "accept")
        # (a) the exported YAML into the picker
        pe0, ce0 = len(R["page_errors"]), len(R["console_errors"])
        page.set_input_files("#qual-ov-files", str(exp))
        got = None
        try:
            with page.expect_download(timeout=6000) as d3:
                page.click("#qual-ov-merge")
            got = d3.value.suggested_filename
        except PWTimeout:
            pass
        page.wait_for_timeout(10000)   # generous: rule out a slow render
        s["yaml_probe"] = {"download": got, "merge_out_after_16s": page.evaluate("() => document.getElementById('qual-ov-merge-out').innerText"),
                           "btn_disabled": page.evaluate("() => document.getElementById('qual-ov-merge').disabled"),
                           "page_errors": R["page_errors"][pe0:], "console_errors": R["console_errors"][ce0:]}
        shot(page, "#qual-ov-merge-out", "S-F3-merge-yaml-stuck-en.png")
        # (b) a file the picker DOES accept (.json) that is not an export: same path?
        bad = DL / "not-an-export.json"
        bad.write_text(json.dumps({"hello": "world"}))
        pe0, ce0 = len(R["page_errors"]), len(R["console_errors"])
        page.set_input_files("#qual-ov-files", str(bad))
        got = None
        try:
            with page.expect_download(timeout=6000) as d4:
                page.click("#qual-ov-merge")
            got = d4.value.suggested_filename
        except PWTimeout:
            pass
        page.wait_for_timeout(8000)
        s["json_probe"] = {"download": got, "merge_out_after_14s": page.evaluate("() => document.getElementById('qual-ov-merge-out').innerText"),
                           "page_errors": R["page_errors"][pe0:], "console_errors": R["console_errors"][ce0:]}
        shot(page, "#qual-ov-merge-out", "S-F3-merge-json-stuck-en.png")
        page.set_input_files("#qual-ov-files", [])
        save()

        # ---------------------------------------------------------------- F1 + F8 Undo (mutation)
        s = step("F1_undo")
        page.reload(wait_until="domcontentloaded"); unlock(page)
        open_quality(page)
        s["before"] = panel(page)
        s["api_before"] = api(page, "/api/sources/qualification/config").get("counts")
        row = page.locator("#qual-admission .row", has_text="admitted-live.example")
        btn = row.locator("button[data-undo]")
        btn.scroll_into_view_if_needed()
        btn.click()
        page.wait_for_function("() => document.querySelectorAll('#qual-admission button[data-undo]').length === 0", timeout=15000)
        page.wait_for_timeout(2000)
        s["after_2s"] = panel(page)
        page.wait_for_timeout(8000)
        s["after_10s"] = panel(page)
        s["api_after"] = api(page, "/api/sources/qualification/config").get("counts")
        s["toasts"] = page.evaluate("() => (window.__toasts||[]).map(x => x.text)")
        page.locator("#qual-state").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, "#qualification-panel", "S-F1-after-undo-stale-en.png")
        s8 = step("F8_timestamp")
        s8["rows_after_undo"] = page.evaluate("""() => Array.from(document.querySelectorAll('#qual-admission .row')).map(r => r.innerText.replace(/\\s+/g,' ').trim())""")
        s8["audit_api_after_undo"] = [{k: e.get(k) for k in ("domain", "occurred_at", "undone_at")} for e in api(page, "/api/sources/admission/audit?limit=25").get("events", [])]
        shot(page, "#qual-admission", "S-F8-admission-after-undo-en.png")
        page.reload(wait_until="domcontentloaded"); unlock(page)
        open_quality(page)
        s["after_reload"] = panel(page)
        save()

        # ---------------------------------------------------------------- F7 375px Home
        s = step("F7_375")
        ctx2 = br.new_context(viewport={"width": 375, "height": 800})
        ctx2.add_init_script(INIT)
        p2 = ctx2.new_page()
        attach(p2)
        WHERE["v"] = "en-375"
        unlock(p2)
        p2.wait_for_timeout(2000)
        s["overflow_home"] = p2.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        s["widest"] = p2.evaluate("""() => { const out = []; document.querySelectorAll('#tab-home *').forEach(e => {
             if (!e.offsetParent) return; const r = e.getBoundingClientRect();
             if (r.right > document.documentElement.clientWidth + 1) out.push({id: e.id, cls: String(e.className).slice(0,40), right: Math.round(r.right), w: Math.round(r.width), ws: getComputedStyle(e).whiteSpace, text: (e.innerText||'').slice(0,90)}); });
             return out.slice(0, 12); }""")
        s["home_tier"] = p2.evaluate("() => { const e = document.getElementById('home-tier'); if (!e) return null; const r = e.getBoundingClientRect(); return {hidden: e.hidden, text: e.innerText, left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width), ws: getComputedStyle(e).whiteSpace}; }")
        p2.screenshot(path=str(SHOTS / "S-F7-home-375-en.png"))
        try:
            p2.locator("#home-tier").screenshot(path=str(SHOTS / "S-F7-home-tier-375-en.png"))
        except Exception as e:  # noqa: BLE001
            s["tier_shot_err"] = str(e)
        ctx2.close()
        save()
        br.close()
    save()
    print("done")


if __name__ == "__main__":
    main()
