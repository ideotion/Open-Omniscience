"""Row S click-through, phase A (S1-S9 + locale + 375px checks).

Runs against the throwaway at BASE (encrypted seed, booted locked, console script,
served from the disposable copy /tmp/claude-0/walk/S/oo-app). Real clicks only.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "http://127.0.0.1:8842"
OUT = Path("/tmp/claude-0/walk/S")
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
DL = OUT / "downloads"
DL.mkdir(parents=True, exist_ok=True)
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
PASS = "walk-pass-2026"
OVERLAY = Path("/tmp/claude-0/walk/S/oo-app/configs/source_qualification.yml")
OVERLAY_TEXT = (
    "generated_at: 2026-09-18\n"
    "verdicts:\n"
    "  - {domain: awaiting.example, status: qualified, qualified_at: 2026-09-18}\n"
    "  - {domain: candidate-0.example, status: qualified, qualified_at: 2026-09-18}\n"
    "  - {domain: candidate-1.example, status: disqualified}\n"
)
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")

R: dict = {"steps": {}, "console_errors": [], "page_errors": [], "http_errors": [],
           "dialogs": [], "junk": [], "toasts": []}
DIALOG_ACTION = {"next": "dismiss"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def step(sid: str) -> dict:
    return R["steps"].setdefault(sid, {})


def save():
    (OUT / "raw_a.json").write_text(json.dumps(R, indent=2, ensure_ascii=False))


INIT = """
(() => {
  window.__toasts = [];
  const hook = () => {
    const host = document.getElementById('toast');
    if (!host) { setTimeout(hook, 200); return; }
    new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes)
      if (n.nodeType === 1) window.__toasts.push({t: Date.now(), cls: n.className, text: n.textContent}); })
      .observe(host, {childList: true});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', hook); else hook();
})();
"""


def attach(page, lang_tag):
    page.on("console", lambda m: R["console_errors"].append(
        {"where": lang_tag["v"], "text": m.text, "loc": str(m.location)}) if m.type == "error" else None)
    page.on("pageerror", lambda e: R["page_errors"].append({"where": lang_tag["v"], "text": str(e)}))
    page.on("response", lambda r: R["http_errors"].append(
        {"where": lang_tag["v"], "url": r.url, "status": r.status}) if r.status >= 400 else None)

    def on_dialog(d):
        act = DIALOG_ACTION["next"]
        R["dialogs"].append({"where": lang_tag["v"], "type": d.type, "message": d.message, "action": act})
        if act == "accept":
            d.accept()
        else:
            d.dismiss()
    page.on("dialog", on_dialog)


def toasts_since(page, t0):
    return [x for x in page.evaluate("() => window.__toasts || []") if x["t"] >= t0]


def now_ms(page):
    return page.evaluate("() => Date.now()")


def unlock_if_needed(page):
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    if page.locator("#pw").count() and page.locator("#pw").is_visible():
        page.fill("#pw", PASS)
        page.click("#btn-unlock")
        page.wait_for_url(re.compile(r".*#home.*|.*/$|.*/#.*"), timeout=90000)
        page.wait_for_selector("#home-stats", timeout=90000)
        return True
    page.wait_for_selector("#home-stats", timeout=60000)
    return False


def settle_chrome(page):
    """Close the first-run guide through its own control and the coachmark with 'Not now'."""
    closed = {"wizard": False, "coach": False}
    for _ in range(6):
        page.wait_for_timeout(500)
        if page.locator("#guide-wizard[open]").count():
            page.click("#gw-close")
            page.wait_for_timeout(400)
            closed["wizard"] = True
        c = page.locator("#net-coach-dismiss")
        if c.count() and c.is_visible():
            c.click()
            closed["coach"] = True
    return closed


def goto_tab(page, tab):
    page.click(f"#navGroups button.nav-item[data-tab='{tab}']")
    page.wait_for_timeout(500)


def open_settings_advanced(page):
    page.click("button[onclick=\"showTab('settings')\"]")
    page.wait_for_selector("#set-subtabs", state="visible", timeout=15000)
    page.click("#set-subtabs button[data-tab='advanced']")
    page.wait_for_selector("details[data-adv='qualification'] > summary", state="visible", timeout=15000)


def expand_quality(page):
    d = page.locator("details[data-adv='qualification']")
    if not d.evaluate("e => e.open"):
        page.click("details[data-adv='qualification'] > summary")
    wait_panel_loaded(page)


def wait_panel_loaded(page):
    for sel in ("qual-state", "qual-admission", "qual-overlay", "qualify-bulk-status"):
        page.wait_for_function(
            f"() => {{ const e = document.getElementById('{sel}');"
            f" return e && e.textContent.trim() && !/^(Loading…|Chargement|加载|جارٍ التحميل)/.test(e.textContent.trim()); }}",
            timeout=30000)
    page.wait_for_function("() => document.getElementById('qual-scope-count').textContent.trim().length > 0",
                           timeout=15000)
    page.wait_for_timeout(400)


def switch_lang(page, code):
    page.click("#lang-switch")
    page.wait_for_selector("#lang-menu:not([hidden])", timeout=5000)
    page.click(f"#lang-menu [data-lang='{code}']")
    page.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=15000)
    page.wait_for_timeout(800)


def panel_read(page):
    return page.evaluate("""() => {
      const g = (id) => { const e = document.getElementById(id); return e ? e.innerText.trim() : null; };
      const rows = Array.from(document.querySelectorAll('#qual-admission .row')).map(r => ({
        text: r.innerText.replace(/\\s+/g, ' ').trim(),
        undo: !!r.querySelector('button[data-undo]'),
        undoLabel: r.querySelector('button[data-undo]') ? r.querySelector('button[data-undo]').innerText.trim() : null,
      }));
      const btn = (id) => { const b = document.getElementById(id); return b ? {text: b.innerText.trim(), disabled: b.disabled} : null; };
      const ret = document.getElementById('qual-scope-retired');
      return {
        state: g('qual-state'), criteria: g('qual-criteria'), gates: g('qual-gates'),
        scope_count: g('qual-scope-count'),
        retired: ret ? {hidden: ret.hidden, text: ret.innerText.trim(), textContent: ret.textContent.trim()} : null,
        admission: g('qual-admission'), rows,
        overlay: g('qual-overlay'),
        buttons: {adopt: btn('qual-ov-adopt'), revert: btn('qual-ov-revert'), export: btn('qual-ov-export'),
                  merge: btn('qual-ov-merge'), bulk: btn('qualify-bulk-btn')},
        merge_out: g('qual-ov-merge-out'),
        bulk: g('qualify-bulk-status'),
        panel: g('qualification-panel'),
        lang: document.documentElement.lang, dir: document.documentElement.dir,
        langBtn: (document.getElementById('lang-flag')||{}).textContent + ' ' + (document.getElementById('lang-code')||{}).textContent,
      };
    }""")


def junk_scan(page, where, sel):
    txt = page.evaluate(f"() => {{ const e = document.querySelector({json.dumps(sel)}); return e ? e.innerText : ''; }}")
    for m in JUNK.finditer(txt or ""):
        s = max(0, m.start() - 60)
        R["junk"].append({"where": where, "sel": sel, "match": m.group(0), "context": txt[s:m.end() + 60]})


def shot_el(page, sel, name):
    loc = page.locator(sel)
    loc.scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    loc.screenshot(path=str(SHOTS / name))


def api_json(page, path):
    return page.evaluate(f"async () => (await (await fetch({json.dumps(path)})).json())")


def main():
    lang_tag = {"v": "en"}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        attach(page, lang_tag)

        # ------------------------------------------------------------------ S1
        s = step("S1")
        s["unlocked_via_ui"] = unlock_if_needed(page)
        s["url_after_unlock"] = page.url
        s["chrome_closed"] = settle_chrome(page)
        s["net_before"] = api_json(page, "/api/system/network")
        s["plane_fill_at_first_read"] = page.get_attribute("#net-plane", "fill")
        try:
            page.wait_for_function("() => document.getElementById('net-plane').getAttribute('fill') === 'none'", timeout=20000)
        except PWTimeout:
            pass
        s["plane_fill_before"] = page.get_attribute("#net-plane", "fill")
        s["net_toggle_title_before"] = page.get_attribute("#net-toggle", "title")
        t0 = now_ms(page)
        if not s["net_before"].get("online", True):
            raise SystemExit("ABORT: already offline -- clicking the plane would go ONLINE")
        page.click("#net-toggle")
        page.wait_for_function("() => (window.__toasts||[]).some(x => /Offline —/.test(x.text))", timeout=15000)
        page.wait_for_timeout(500)
        s["net_toasts"] = [x["text"] for x in toasts_since(page, t0)]
        s["plane_fill_after"] = page.get_attribute("#net-plane", "fill")
        s["net_after"] = api_json(page, "/api/system/network")
        s["consent_dialog_opened"] = page.locator("#net-consent[open]").count() > 0
        page.screenshot(path=str(SHOTS / "S-S1-airplane-en.png"))
        open_settings_advanced(page)
        page.wait_for_timeout(600)
        s["qual_state_before_expand"] = page.evaluate("() => document.getElementById('qual-state').textContent.trim()")
        s["qual_requests_before_expand"] = [r for r in R["http_errors"]]
        expand_quality(page)
        pr = panel_read(page)
        s["panel"] = pr
        # hovers on the four numbers
        hov = []
        nums = page.locator("#qual-state b")
        s["n_numbers"] = nums.count()
        for i in range(nums.count()):
            page.mouse.move(5, 5)
            page.wait_for_timeout(300)
            nums.nth(i).hover()
            try:
                page.wait_for_function("() => { const t = document.getElementById('oo-tip');"
                                       " return t && t.offsetParent !== null && t.textContent.trim(); }", timeout=5000)
            except PWTimeout:
                pass
            page.wait_for_timeout(200)
            tip = page.evaluate("() => { const t = document.getElementById('oo-tip'); return t ? {vis: t.offsetParent !== null || getComputedStyle(t).display !== 'none', text: t.innerText.trim()} : null; }")
            hov.append({"number": nums.nth(i).inner_text(), "title": nums.nth(i).get_attribute("title"), "tip": tip})
            if i == 0:
                page.screenshot(path=str(SHOTS / "S-S1-hover-collecting-en.png"))
        s["hovers"] = hov
        page.mouse.move(5, 5)
        shot_el(page, "#qualification-panel", "S-S1-quality-gates-en.png")
        s["config_api_scope"] = api_json(page, "/api/sources/qualification/config").get("scope")
        # expand Collection and Sources, search Advanced for any unqualified-scrape control
        for sec in ("collect", "sources"):
            d = page.locator(f"details[data-adv='{sec}']")
            if not d.evaluate("e => e.open"):
                page.click(f"details[data-adv='{sec}'] > summary")
            page.wait_for_timeout(1200)
        s["hatch_controls"] = page.evaluate("""() => {
          const out = [];
          document.querySelectorAll('#set-advanced input[type=checkbox], #set-advanced input[type=radio], #set-advanced select, #set-advanced [role=switch]').forEach(el => {
            const lab = (el.closest('label') ? el.closest('label').innerText : '') + ' ' + (el.title||'') + ' ' + (el.closest('label') ? (el.closest('label').title||'') : '') + ' ' + (el.id||'');
            if (/unqualif|unjudg|not yet judged|scrape_unq/i.test(lab)) out.push({id: el.id, label: lab.trim().slice(0, 200)});
          });
          return out;
        }""")
        s["advanced_checkbox_count"] = page.evaluate("() => document.querySelectorAll('#set-advanced input[type=checkbox]').length")
        s["advanced_text_mentions"] = page.evaluate("""() => {
          const t = document.getElementById('set-advanced').innerText;
          return (t.match(/[^\\n]*(unqualified|unjudged)[^\\n]*/gi) || []).slice(0, 20);
        }""")
        junk_scan(page, "S1 en", "#qualification-panel")
        save()

        # ------------------------------------------------------------------ S2
        s = step("S2")
        s["panel"] = panel_read(page)
        shot_el(page, "#qual-admission", "S-S2-admission-en.png")
        page.locator("#qual-overlay").scroll_into_view_if_needed()
        shot_el(page, "#qualification-panel", "S-S2-lower-panel-en.png")
        s["bulk_status_api"] = api_json(page, "/api/sources/qualify-bulk/status")
        save()

        # ------------------------------------------------------------------ S3
        s = step("S3")
        goto_tab(page, "home")
        page.wait_for_function("() => !/Loading/.test(document.getElementById('home-stats').innerText)", timeout=30000)
        page.wait_for_timeout(1500)
        s["home_innerText"] = page.evaluate("() => document.getElementById('home-stats').innerText")
        s["home_textContent_items"] = page.evaluate("() => Array.from(document.querySelectorAll('#home-stats .s')).map(e => e.textContent.replace(/\\s+/g,' ').trim())")
        shot_el(page, "#home-stats", "S-S3-home-strip-en.png")
        junk_scan(page, "S3 en home", "#home-stats")
        goto_tab(page, "library")
        page.click("#library-views button[data-tab='storage']")
        page.wait_for_selector("#db-stats .stat", timeout=30000)
        page.wait_for_timeout(4000)
        s["db_tiles"] = page.evaluate("() => Array.from(document.querySelectorAll('#db-stats .stat')).map(e => ({n: e.querySelector('.n').textContent.trim(), k: e.querySelector('.k').textContent.trim()}))")
        s["db_stats_api_counts"] = {k: v for k, v in api_json(page, "/api/database/stats").get("counts", {}).items() if "source" in k}
        shot_el(page, "#db-stats", "S-S3-library-db-en.png")
        junk_scan(page, "S3 en library", "#db-stats")
        open_settings_advanced(page)
        d = page.locator("details[data-adv='collect']")
        if not d.evaluate("e => e.open"):
            page.click("details[data-adv='collect'] > summary")
        page.wait_for_timeout(800)
        leg = page.locator("details[data-adv='collect'] details.adv-collect", has=page.locator("button[onclick='previewTargets()']"))
        s["legacy_details_present"] = leg.count()
        s["legacy_summary"] = leg.locator(":scope > summary").inner_text() if leg.count() else None
        if leg.count() and not leg.evaluate("e => e.open"):
            leg.locator(":scope > summary").click()
            page.wait_for_timeout(600)
        s["which_sources_boxes"] = page.evaluate("() => ['sch-langs','sch-types','sch-tags'].map(i => [i, document.getElementById(i).value])")
        page.locator("button[onclick='previewTargets()']").scroll_into_view_if_needed()
        page.click("button[onclick='previewTargets()']")
        page.wait_for_function("() => /targeted/.test(document.getElementById('sched-targets').innerText)", timeout=15000)
        s["preview_targets"] = page.evaluate("() => document.getElementById('sched-targets').innerText")
        s["targets_api"] = api_json(page, "/api/scheduler/targets")
        shot_el(page, "#sched-targets", "S-S3-preview-targets-en.png")
        save()

        # ------------------------------------------------------------------ S4
        s = step("S4")
        # panel is still open and loaded from S1, same page (no reload since)
        page.locator("details[data-adv='qualification'] > summary").scroll_into_view_if_needed()
        s["panel_open_before"] = page.locator("details[data-adv='qualification']").evaluate("e => e.open")
        en_panel = panel_read(page)
        s["en_before"] = en_panel
        switch_lang(page, "fr")
        lang_tag["v"] = "fr-live"
        page.wait_for_timeout(1500)
        live = panel_read(page)
        s["fr_live"] = live
        shot_el(page, "#qualification-panel", "S-S4-live-switch-fr.png")
        # which lines are byte-identical to the English render (untranslated) -- ignore pure data
        en_lines = [l.strip() for l in (en_panel["panel"] or "").split("\n") if l.strip()]
        fr_lines = [l.strip() for l in (live["panel"] or "").split("\n") if l.strip()]
        s["identical_lines_after_live_switch"] = [l for l in fr_lines if l in en_lines and re.search(r"[A-Za-z]{4,}", l)]
        page.reload(wait_until="domcontentloaded")
        unlock_if_needed(page)
        settle_chrome(page)
        open_settings_advanced(page)
        expand_quality(page)
        s["fr_after_reload_lang"] = page.evaluate("() => document.documentElement.lang")
        save()

        # ------------------------------------------------------------------ S5
        s = step("S5")
        per = {}
        for code in ("fr", "zh", "ar"):
            if code != "fr":
                switch_lang(page, code)
                page.reload(wait_until="domcontentloaded")
                unlock_if_needed(page)
                settle_chrome(page)
                open_settings_advanced(page)
                expand_quality(page)
            lang_tag["v"] = code
            pr = panel_read(page)
            lines = [l.strip() for l in (pr["panel"] or "").split("\n") if l.strip()]
            pr["identical_to_en_lines"] = [l for l in lines if l in en_lines and re.search(r"[A-Za-z]{4,}", l)]
            if code == "ar":
                pr["row_layout"] = page.evaluate("""() => Array.from(document.querySelectorAll('#qual-admission .row')).map(r => {
                  const kids = r.children; const a = kids[0].getBoundingClientRect(), b = kids[1].getBoundingClientRect();
                  const ts = r.querySelector('span[dir=ltr]');
                  return {text: r.innerText.replace(/\\s+/g,' ').slice(0,80), info_left: a.left, info_right: a.right,
                          action_left: b.left, action_right: b.right, action_text: kids[1].innerText.trim(),
                          ts: ts ? ts.textContent : null, ts_dir: ts ? getComputedStyle(ts).direction : null};
                })""")
                pr["body_direction"] = page.evaluate("() => getComputedStyle(document.body).direction")
            per[code] = pr
            page.locator("#qual-state").scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=str(SHOTS / f"S-S5-headline-{code}.png"))
            shot_el(page, "#qual-admission", f"S-S5-admission-{code}.png")
            shot_el(page, "#qual-overlay", f"S-S5-overlay-{code}.png") if code == "zh" else None
            junk_scan(page, f"S5 {code}", "#qualification-panel")
            # Home + Library quick read in this locale
            goto_tab(page, "home")
            page.wait_for_timeout(1500)
            pr["home"] = page.evaluate("() => document.getElementById('home-stats').innerText")
            goto_tab(page, "library")
            page.click("#library-views button[data-tab='storage']")
            page.wait_for_timeout(3000)
            pr["db_tiles"] = page.evaluate("() => Array.from(document.querySelectorAll('#db-stats .stat')).map(e => e.innerText.replace(/\\s+/g,' '))")
            open_settings_advanced(page)
            expand_quality(page)
            save()
        s["per_lang"] = per
        save()

        # ------------------------------------------------------------------ S6 (ar)
        s = step("S6")
        lang_tag["v"] = "ar"
        s["lang"] = page.evaluate("() => document.documentElement.lang")
        row = page.locator("#qual-admission .row", has_text="admitted-live.example")
        s["row_before"] = row.inner_text()
        btn = row.locator("button[data-undo]")
        btn.scroll_into_view_if_needed()
        t0 = now_ms(page)
        btn.click()
        page.wait_for_function("() => document.querySelectorAll('#qual-admission button[data-undo]').length === 0", timeout=15000)
        page.wait_for_timeout(1500)
        s["toasts"] = [x["text"] for x in toasts_since(page, t0)]
        s["after_no_reload"] = panel_read(page)
        page.locator("#qual-state").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "S-S6-after-undo-ar.png"))
        shot_el(page, "#qual-admission", "S-S6-admission-after-undo-ar.png")
        s["api_config_counts_now"] = api_json(page, "/api/sources/qualification/config").get("counts")
        page.reload(wait_until="domcontentloaded")
        unlock_if_needed(page)
        settle_chrome(page)
        open_settings_advanced(page)
        expand_quality(page)
        s["after_reload"] = panel_read(page)
        save()

        # ------------------------------------------------------------------ S7
        s = step("S7")
        switch_lang(page, "en")
        page.reload(wait_until="domcontentloaded")
        unlock_if_needed(page)
        settle_chrome(page)
        lang_tag["v"] = "en"
        OVERLAY.write_text(OVERLAY_TEXT)
        s["overlay_path"] = str(OVERLAY)
        s["overlay_sha256"] = sha(OVERLAY)
        page.reload(wait_until="domcontentloaded")
        unlock_if_needed(page)
        settle_chrome(page)
        open_settings_advanced(page)
        expand_quality(page)
        s["panel"] = panel_read(page)
        shot_el(page, "#qual-overlay", "S-S7-overlay-populated-en.png")
        page.locator("#qual-state").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "S-S7-headline-en.png"))
        save()

        # ------------------------------------------------------------------ S8
        s = step("S8")
        t0 = now_ms(page)
        page.locator("#qual-ov-export").scroll_into_view_if_needed()
        with page.expect_download(timeout=20000) as dl:
            page.click("#qual-ov-export")
        d = dl.value
        exp_path = DL / ("export-" + d.suggested_filename)
        d.save_as(str(exp_path))
        page.wait_for_timeout(800)
        s["export_toasts"] = [x["text"] for x in toasts_since(page, t0)]
        s["export_filename"] = d.suggested_filename
        s["export_text"] = exp_path.read_text()
        # merge with the picker empty
        t0 = now_ms(page)
        page.locator("#qual-ov-merge").scroll_into_view_if_needed()
        with page.expect_download(timeout=30000) as dl2:
            page.click("#qual-ov-merge")
        d2 = dl2.value
        m_path = DL / ("merge-" + d2.suggested_filename)
        d2.save_as(str(m_path))
        page.wait_for_function("() => !/Merging/.test(document.getElementById('qual-ov-merge-out').innerText)", timeout=20000)
        page.wait_for_timeout(500)
        s["merge_out"] = page.evaluate("() => document.getElementById('qual-ov-merge-out').innerText")
        s["merge_filename"] = d2.suggested_filename
        s["merge_text"] = m_path.read_text()
        s["overlay_sha256_after_merge"] = sha(OVERLAY)
        s["overlay_unchanged"] = s["overlay_sha256_after_merge"] == step("S7")["overlay_sha256"]
        s["collecting_after_merge"] = api_json(page, "/api/sources/qualification/config")["counts"]["collecting"]
        s["headline_after_merge"] = page.evaluate("() => document.getElementById('qual-state').innerText")
        shot_el(page, "#qual-ov-merge-out", "S-S8-merge-empty-picker-en.png")
        # PROBE: put the exported YAML into the picker and merge again
        pe_before = len(R["page_errors"])
        ce_before = len(R["console_errors"])
        page.set_input_files("#qual-ov-files", str(exp_path))
        s["picker_files"] = page.evaluate("() => Array.from(document.getElementById('qual-ov-files').files).map(f => f.name)")
        downloaded = None
        try:
            with page.expect_download(timeout=8000) as dl3:
                page.click("#qual-ov-merge")
            downloaded = dl3.value.suggested_filename
        except PWTimeout:
            downloaded = None
        page.wait_for_timeout(3000)
        s["probe_download"] = downloaded
        s["probe_merge_out"] = page.evaluate("() => document.getElementById('qual-ov-merge-out').innerText")
        s["probe_merge_btn_disabled"] = page.evaluate("() => document.getElementById('qual-ov-merge').disabled")
        s["probe_new_page_errors"] = R["page_errors"][pe_before:]
        s["probe_new_console_errors"] = R["console_errors"][ce_before:]
        # what the server actually said to that upload
        s["probe_server_reply"] = page.evaluate("""async () => {
          const fd = new FormData(); fd.append('files', new Blob([%s], {type:'text/yaml'}), 'source_qualification.yml');
          fd.append('include_this_instance', 'true');
          const r = await fetch('/api/diagnostics/source-qualification-merge', {method:'POST', body: fd});
          return {status: r.status, body: (await r.text()).slice(0, 400)};
        }""" % json.dumps(s["export_text"]))
        shot_el(page, "#qual-ov-merge-out", "S-S8-merge-probe-yaml-en.png")
        page.set_input_files("#qual-ov-files", [])
        save()

        # ------------------------------------------------------------------ S9
        s = step("S9")
        page.reload(wait_until="domcontentloaded")  # clear the stuck Merging state before adopting
        unlock_if_needed(page)
        settle_chrome(page)
        open_settings_advanced(page)
        expand_quality(page)
        s["before"] = panel_read(page)
        t0 = now_ms(page)
        page.locator("#qual-ov-adopt").scroll_into_view_if_needed()
        page.click("#qual-ov-adopt")
        page.wait_for_function("() => (window.__toasts||[]).some(x => /Adopted/.test(x.text))", timeout=20000)
        page.wait_for_timeout(2500)
        wait_panel_loaded(page)
        s["adopt_toasts"] = [x["text"] for x in toasts_since(page, t0)]
        s["after_adopt"] = panel_read(page)
        s["after_adopt_counts_api"] = api_json(page, "/api/sources/qualification/config")["counts"]
        s["candidate0"] = page.evaluate("async () => { const r = await fetch('/api/sources?limit=50'); if (!r.ok) return r.status; const d = await r.json(); const arr = Array.isArray(d) ? d : (d.sources||d.items||[]); return arr.filter(x => /candidate-0|awaiting/.test(x.domain||'')).map(x => ({domain: x.domain, enabled: x.enabled, status: x.status})); }")
        shot_el(page, "#qual-overlay", "S-S9-after-adopt-overlay-en.png")
        page.locator("#qual-state").scroll_into_view_if_needed()
        page.screenshot(path=str(SHOTS / "S-S9-after-adopt-en.png"))
        # Revert, dismissed
        DIALOG_ACTION["next"] = "dismiss"
        t0 = now_ms(page)
        nd = len(R["dialogs"])
        page.click("#qual-ov-revert")
        page.wait_for_timeout(2000)
        s["cancel_dialogs"] = R["dialogs"][nd:]
        s["cancel_toasts"] = [x["text"] for x in toasts_since(page, t0)]
        s["after_cancel"] = panel_read(page)
        # Revert, accepted
        DIALOG_ACTION["next"] = "accept"
        t0 = now_ms(page)
        nd = len(R["dialogs"])
        page.click("#qual-ov-revert")
        page.wait_for_function("() => (window.__toasts||[]).some(x => /Put back/.test(x.text))", timeout=20000)
        page.wait_for_timeout(2500)
        wait_panel_loaded(page)
        DIALOG_ACTION["next"] = "dismiss"
        s["accept_dialogs"] = R["dialogs"][nd:]
        s["revert_toasts"] = [x["text"] for x in toasts_since(page, t0)]
        s["after_revert"] = panel_read(page)
        s["after_revert_counts_api"] = api_json(page, "/api/sources/qualification/config")["counts"]
        shot_el(page, "#qual-overlay", "S-S9-after-revert-overlay-en.png")
        shot_el(page, "#qual-admission", "S-S9-after-revert-admission-en.png")
        save()

        # ------------------------------------------------------------------ 375px pass (en)
        s = step("narrow375")
        ctx2 = browser.new_context(viewport={"width": 375, "height": 800})
        ctx2.add_init_script(INIT)
        p2 = ctx2.new_page()
        lang_tag["v"] = "en-375"
        attach(p2, lang_tag)
        unlock_if_needed(p2)
        settle_chrome(p2)
        res = {}
        res["home_overflow"] = p2.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        p2.screenshot(path=str(SHOTS / "S-375-home-en.png"))
        # reach Settings via the same sidebar button
        try:
            open_settings_advanced(p2)
            expand_quality(p2)
            res["settings_reached"] = True
        except Exception as e:  # noqa: BLE001
            res["settings_reached"] = f"failed: {e}"
        res["quality_overflow"] = p2.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        res["clipped"] = p2.evaluate("""() => {
          const out = [];
          document.querySelectorAll('#qualification-panel *').forEach(e => {
            if (!e.offsetParent) return;
            const cs = getComputedStyle(e);
            if ((cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.textOverflow === 'ellipsis') && e.scrollWidth > e.clientWidth + 1)
              out.push({tag: e.tagName, id: e.id, cls: e.className, text: e.innerText.slice(0, 80)});
            const r = e.getBoundingClientRect();
            if (r.right > window.innerWidth + 1 && e.children.length === 0 && e.innerText.trim())
              out.push({offscreen: true, tag: e.tagName, id: e.id, right: r.right, text: e.innerText.slice(0, 80)});
          });
          return out.slice(0, 30);
        }""")
        p2.locator("#qual-state").scroll_into_view_if_needed()
        p2.screenshot(path=str(SHOTS / "S-375-quality-gates-en.png"))
        shot_el(p2, "#qual-admission", "S-375-admission-en.png")
        s.update(res)
        ctx2.close()
        save()
        browser.close()
    save()
    print("phase A done")


if __name__ == "__main__":
    main()
