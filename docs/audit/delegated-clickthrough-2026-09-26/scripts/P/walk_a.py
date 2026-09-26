"""Row P, folder A (fresh, encrypted, OO_AUTOSEED=0) on port 8838: P1-P5 through the real UI."""
import json
import sys
import traceback

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/P")
from common import (EXE, OUT, PASS, TOAST_INIT, TOPBAR, Rec, boxes, close_guide, dismiss_coach,  # noqa: E402
                    jsnow, junk_in, plane_filled, save, settings_sub, shot, text, tip, toasts_since, wstate)

BASE = "http://127.0.0.1:8838"
STAGES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["p1", "p2", "p3", "p4", "p5"]
R = {}
OUTF = "a_" + "_".join(STAGES) + ".json"
rec = Rec("A")


def wizard_read(pg):
    return pg.evaluate("""() => {
      const d = document.getElementById('wiki-wizard');
      const boxes = [...document.querySelectorAll('#wiki-wizard-editions input[type=checkbox]')];
      return {open: !!(d && d.open),
        title: (d.querySelector('h3')||{}).innerText,
        hosts: (document.getElementById('wiki-wizard-hosts')||{}).innerText,
        blocks: [...d.querySelectorAll('.hint')].map(h => h.innerText),
        editions: boxes.map(b => b.parentElement.innerText + (b.checked ? ' [x]' : ' [ ]')),
        n_editions: boxes.length, n_checked: boxes.filter(b => b.checked).length,
        count: (document.getElementById('wiki-wizard-count')||{}).innerText,
        budget: (document.getElementById('wiki-wizard-budget')||{}).value,
        share: (document.getElementById('wiki-wizard-share')||{}).innerText,
        body: d.innerText};
    }""")


def main():
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=EXE, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking", "--disable-component-update"])
        ctx = br.new_context(viewport={"width": 1440, "height": 950})
        ctx.add_init_script(TOAST_INIT)
        pg = ctx.new_page()
        rec.attach(pg)
        try:
            state = pg.evaluate("() => 0") if False else None
            pg.goto(BASE, wait_until="domcontentloaded")
            pg.wait_for_timeout(1500)
            lock = pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json())")
            R["lock_state_at_start"] = lock
            if "p1" in STAGES:
                p1(pg, lock)
            else:
                unlock(pg)
            if "p2" in STAGES:
                p2(pg)
            if "p3" in STAGES:
                p3(pg)
            if "p4" in STAGES:
                p4(pg)
            if "p5" in STAGES:
                p5(pg)
        except Exception:
            R["harness_exception"] = traceback.format_exc()
            try:
                shot(pg, "A-exception")
            except Exception:
                pass
        finally:
            R["errors"] = rec.dump()
            save(OUTF, R)
            br.close()


def unlock(pg):
    st = pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json())")
    R.setdefault("unlocks", []).append(st)
    if not st.get("locked"):
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)
        close_guide(pg)
        dismiss_coach(pg)
        return
    pg.wait_for_selector("#pw", timeout=20000)
    pg.fill("#pw", PASS)
    pg.click("#btn-unlock")
    pg.wait_for_url("**/#home", timeout=60000)
    pg.wait_for_timeout(2500)
    close_guide(pg)
    dismiss_coach(pg)


def p1(pg, lock):
    r = R["P1"] = {}
    r["lock_state"] = lock.get("state")
    # language step
    pg.wait_for_selector("#view-language:not(.hidden) .lang-btn", timeout=20000)
    r["lang_buttons"] = pg.evaluate("() => [...document.querySelectorAll('#lang-list .lang-btn')].map(b => b.innerText)")
    shot(pg, "P1-firstlaunch-language-en")
    pg.click("#lang-list .lang-btn[lang='en']")
    pg.wait_for_selector("#view-legal:not(.hidden)", timeout=20000)
    pg.wait_for_timeout(1500)
    r["legal_heading"] = text(pg, "#lg-heading")
    r["accept_label"] = text(pg, "#lg-accept-label")
    r["accept_btn"] = text(pg, "#lg-accept")
    pg.check("#lg-check")
    pg.wait_for_timeout(300)
    pg.click("#lg-accept")
    # datadir step is skipped when OO_DATA_DIR is set; handle it if shown
    pg.wait_for_timeout(1500)
    if pg.is_visible("#view-datadir"):
        r["datadir_shown"] = True
        pg.click("#dl-continue")
    pg.wait_for_selector("#view-create:not(.hidden)", timeout=20000)
    r["create_heading"] = text(pg, "#view-create h1")
    pg.fill("#pw1", PASS)
    pg.fill("#pw2", PASS)
    pg.click("#btn-create")
    # preparing -> /?wikiwizard=1
    pg.wait_for_url("**/?wikiwizard=1*", timeout=120000)
    r["landed_url"] = pg.url
    pg.wait_for_timeout(3500)
    r["dialogs_open_on_arrival"] = pg.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)")
    r["coach_visible_on_arrival"] = pg.is_visible("#net-coach")
    r["plane_filled_on_arrival"] = plane_filled(pg)
    shot(pg, "P1-arrival-en")
    # The welcome guide may sit over / under the wiki wizard. Close only the guide.
    guide_open = pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }")
    r["guide_opened"] = guide_open
    if guide_open:
        r["guide_title"] = text(pg, "#gw-title")
        close_guide(pg)
    r["coach_dismissed"] = dismiss_coach(pg)
    pg.wait_for_timeout(500)
    r["dialogs_open_after_guide_close"] = pg.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)")
    wz = wizard_read(pg)
    r["wizard"] = wz
    r["plane_filled_with_wizard"] = plane_filled(pg)
    r["w_state_under_wizard"] = wstate(pg)
    # Screenshot the wizard, scrolled top then bottom of its body
    shot(pg, "P1-wizard-top-en")
    pg.evaluate("() => { const b = document.getElementById('wiki-wizard-body'); if (b) b.scrollTop = b.scrollHeight; }")
    pg.wait_for_timeout(300)
    shot(pg, "P1-wizard-bottom-en")
    pg.evaluate("() => { const b = document.getElementById('wiki-wizard-body'); if (b) b.scrollTop = 0; }")
    r["junk"] = junk_in(wz.get("body"))
    # Not now
    pg.click("#wiki-wizard-cancel")
    pg.wait_for_timeout(500)
    r["wizard_open_after_not_now"] = pg.evaluate("() => !!document.getElementById('wiki-wizard').open")
    r["plane_filled_after"] = plane_filled(pg)
    r["cfg_after_not_now"] = pg.evaluate("() => fetch('/api/scheduler/config').then(r => r.json()).then(c => ({state: c.wiki_lane_state, editions: c.wiki_lane_editions, budget: c.wiki_lane_budget_gb, wizard_done: c.wiki_lane_wizard_done}))")
    r["network"] = pg.evaluate("() => fetch('/api/system/network').then(r => r.json())")
    r["at_rest"] = pg.evaluate("() => fetch('/api/system/lock-state').then(r => r.json())")
    R["P1"] = r
    save(OUTF, R)


def p2(pg):
    r = R["P2"] = {}
    settings_sub(pg, "wikipedia")
    pg.wait_for_function("() => !/Loading/.test(document.getElementById('wiki-lane-summary').innerText)", timeout=15000)
    r["summary_before"] = text(pg, "#wiki-lane-summary")
    r["panel_text"] = pg.evaluate("() => document.getElementById('wiki-lane-summary').closest('section').innerText")
    r["robots_visible"] = pg.evaluate("() => { const s = document.getElementById('wiki-lane-summary').closest('section'); const b = [...s.querySelectorAll('.hint b')].map(x => x.innerText); return b; }")
    r["ores_checked"] = pg.evaluate("() => document.getElementById('wiki-ores').checked")
    r["first_panel"] = pg.evaluate("() => document.querySelector('#set-wikipedia section.panel').innerText")
    pg.locator("#wiki-lane-summary").scroll_into_view_if_needed()
    shot(pg, "P2-settings-wikipedia-en")
    # Open the wizard through its button
    pg.click("#wiki-wizard-open")
    pg.wait_for_function("() => document.getElementById('wiki-wizard').open && document.querySelectorAll('#wiki-wizard-editions input').length", timeout=15000)
    pg.wait_for_timeout(500)
    boxes_ = pg.locator("#wiki-wizard-editions input[type=checkbox]")
    boxes_.nth(1).uncheck()
    boxes_.nth(3).uncheck()
    pg.wait_for_timeout(200)
    r["two_unticked"] = {"count": text(pg, "#wiki-wizard-count"), "share": text(pg, "#wiki-wizard-share"),
                         "unticked": pg.evaluate("() => [...document.querySelectorAll('#wiki-wizard-editions input')].filter(b => !b.checked).map(b => b.value)")}
    pg.click("#wiki-wizard-none")
    pg.wait_for_timeout(200)
    r["cleared"] = {"count": text(pg, "#wiki-wizard-count"), "share": text(pg, "#wiki-wizard-share")}
    t0 = jsnow(pg)
    pg.click("#wiki-wizard-save")
    pg.wait_for_timeout(900)
    r["save_empty"] = {"toasts": toasts_since(pg, t0), "still_open": pg.evaluate("() => document.getElementById('wiki-wizard').open")}
    shot(pg, "P2-wizard-save-empty-en")
    pg.click("#wiki-wizard-all")
    pg.wait_for_timeout(200)
    r["select_all"] = {"count": text(pg, "#wiki-wizard-count"), "share": text(pg, "#wiki-wizard-share")}
    pg.fill("#wiki-wizard-budget", "0")
    pg.wait_for_timeout(200)
    r["budget0"] = {"count": text(pg, "#wiki-wizard-count"), "share": text(pg, "#wiki-wizard-share")}
    pg.fill("#wiki-wizard-budget", "24")
    pg.wait_for_timeout(200)
    r["budget24"] = {"count": text(pg, "#wiki-wizard-count"), "share": text(pg, "#wiki-wizard-share")}
    t0 = jsnow(pg)
    pg.click("#wiki-wizard-save")
    pg.wait_for_timeout(1500)
    r["save_ok"] = {"toasts": toasts_since(pg, t0), "still_open": pg.evaluate("() => document.getElementById('wiki-wizard').open"),
                    "plane_filled": plane_filled(pg)}
    r["summary_after"] = text(pg, "#wiki-lane-summary")
    shot(pg, "P2-after-save-en")
    # Reopen to verify it kept the values
    pg.click("#wiki-wizard-open")
    pg.wait_for_function("() => document.getElementById('wiki-wizard').open && document.querySelectorAll('#wiki-wizard-editions input').length", timeout=15000)
    pg.wait_for_timeout(500)
    r["reopened"] = {"budget": pg.evaluate("() => document.getElementById('wiki-wizard-budget').value"),
                     "checked": pg.evaluate("() => [...document.querySelectorAll('#wiki-wizard-editions input')].filter(b => b.checked).length"),
                     "count": text(pg, "#wiki-wizard-count"), "share": text(pg, "#wiki-wizard-share")}
    pg.click("#wiki-wizard-cancel")
    pg.wait_for_timeout(400)
    r["cfg_after"] = pg.evaluate("() => fetch('/api/scheduler/config').then(r => r.json()).then(c => ({state: c.wiki_lane_state, editions: c.wiki_lane_editions, budget: c.wiki_lane_budget_gb, wizard_done: c.wiki_lane_wizard_done}))")
    # Storage row
    pg.click("#set-subtabs button[data-tab='data']")
    pg.wait_for_timeout(1500)
    pg.wait_for_function("() => /\\S/.test((document.getElementById('storage-lanes')||{}).innerText || '')", timeout=15000)
    r["storage_rows"] = pg.evaluate("() => [...document.querySelectorAll('#storage-lanes tr')].map(tr => tr.innerText.replace(/\\s+/g,' ').trim())")
    r["storage_wiki_row"] = [x for x in r["storage_rows"] if "Wikipedia" in x]
    r["storage_text"] = text(pg, "#storage-panel")
    pg.locator("#storage-panel").scroll_into_view_if_needed()
    shot(pg, "P2-storage-en", clip_sel="#storage-panel")
    # Back to Wikipedia: first panel + offline baselines
    pg.click("#set-subtabs button[data-tab='wikipedia']")
    pg.wait_for_timeout(900)
    r["baselines"] = pg.evaluate("""() => { const s = [...document.querySelectorAll('#set-wikipedia section.panel')].find(x => /offline baselines/.test(x.innerText));
       if (!s) return null;
       return {h3: [...s.querySelectorAll('h3')].map(h => h.innerText),
               buttons: [...s.querySelectorAll('button')].map(b => b.innerText.trim())}; }""")
    R["P2"] = r
    save(OUTF, R)


def p3(pg):
    r = R["P3"] = {}
    pg.click(".nav-item[data-tab='home']")
    pg.wait_for_timeout(1200)
    pg.mouse.move(2, 400)
    r["boxes_before"] = boxes(pg, TOPBAR)
    r["w_before"] = wstate(pg)
    r["tip_W_1"] = tip(pg, "#wiki-toggle")
    shot(pg, "P3-W-hover-running-en")
    # (2) airplane -> Go online? -> hover Wikipedia line -> Stay offline
    pg.mouse.move(2, 400)
    pg.click("#net-toggle")
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=10000)
    pg.wait_for_function("() => !/^…$/.test(document.getElementById('net-consent-lanes').innerText)", timeout=10000)
    pg.wait_for_timeout(800)
    r["popup_airplane"] = consent_read(pg)
    wl = pg.locator("#net-consent-lanes span[title]", has_text="Wikipedia / Wikimedia")
    r["popup_airplane"]["wiki_line_title"] = wl.first.get_attribute("title") if wl.count() else None
    if wl.count():
        r["popup_airplane"]["wiki_line_tip"] = tip(pg, None, locator=wl.first)
    shot(pg, "P3-consent-airplane-en")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(600)
    r["after_stay_offline"] = {"popup_open": pg.evaluate("() => document.getElementById('net-consent').open"),
                               "plane_filled": plane_filled(pg)}
    # (3) click W once -> paused, then hover (real mouse: hover, click, keep pointer, then re-hover)
    r["boxes_pre_click"] = boxes(pg, TOPBAR)
    t0 = jsnow(pg)
    pg.hover("#wiki-toggle")
    pg.wait_for_timeout(400)
    pg.click("#wiki-toggle")
    pg.wait_for_timeout(1500)
    r["paused"] = {"popup_open": pg.evaluate("() => document.getElementById('net-consent').open"),
                   "toasts": toasts_since(pg, t0), "w": wstate(pg),
                   "tip_visible_right_after_click": pg.evaluate("() => document.getElementById('oo-tip').textContent")}
    r["paused"]["boxes"] = boxes(pg, TOPBAR)
    # move off, then re-hover (as a person would to read the new bubble)
    r["paused"]["tip_rehover"] = tip(pg, "#wiki-toggle")
    r["paused"]["w_after_rehover"] = wstate(pg)
    shot(pg, "P3-W-paused-en", clip_sel="header")
    # (4) Shift+click -> stopped
    t0 = jsnow(pg)
    pg.click("#wiki-toggle", modifiers=["Shift"])
    pg.wait_for_timeout(1500)
    r["stopped"] = {"popup_open": pg.evaluate("() => document.getElementById('net-consent').open"),
                    "toasts": toasts_since(pg, t0), "w": wstate(pg), "boxes": boxes(pg, TOPBAR)}
    r["stopped"]["tip_rehover"] = tip(pg, "#wiki-toggle")
    shot(pg, "P3-W-stopped-en", clip_sel="header")
    r["cfg_state"] = pg.evaluate("() => fetch('/api/scheduler/config').then(r => r.json()).then(c => c.wiki_lane_state)")
    r["plane_filled_end"] = plane_filled(pg)
    # Is there any on-screen hint that Shift+click stops?
    r["shift_hint_anywhere"] = pg.evaluate("() => /shift/i.test(document.body.innerText + ' ' + [...document.querySelectorAll('[title],[data-oo-tip]')].map(e => (e.getAttribute('title')||'') + (e.dataset.ooTip||'')).join(' '))")
    R["P3"] = r
    save(OUTF, R)


def consent_read(pg):
    return pg.evaluate("""() => { const d = document.getElementById('net-consent');
      const lanes = document.getElementById('net-consent-lanes');
      const groups = {}; let cur = null;
      [...lanes.children].forEach(ch => {
        if (ch.classList.contains('muted')) { cur = ch.innerText; groups[cur] = []; }
        else if (ch.classList.contains('hint')) { groups['_hint'] = ch.innerText; }
        else if (cur) { groups[cur].push(ch.innerText); }
      });
      return {open: d.open, title: d.querySelector('h3').innerText,
              reason: document.getElementById('net-consent-reason').innerText,
              groups, ifaces: document.getElementById('net-consent-ifaces').innerText,
              caveats: [...d.querySelectorAll('#net-consent-body > .hint')].map(h => h.innerText),
              buttons: [...d.querySelectorAll('button')].map(b => b.innerText), body: d.innerText}; }""")


def p4(pg):
    r = R["P4"] = {}
    r["w_before"] = wstate(pg)
    t0 = jsnow(pg)
    pg.click("#wiki-toggle")
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=10000)
    pg.wait_for_function("() => !/^…$/.test(document.getElementById('net-consent-lanes').innerText)", timeout=10000)
    pg.wait_for_timeout(1000)
    r["popup"] = consent_read(pg)
    wl = pg.locator("#net-consent-lanes span[title]", has_text="Wikipedia / Wikimedia")
    if wl.count():
        r["popup"]["wiki_line_tip"] = tip(pg, None, locator=wl.first)
    shot(pg, "P4-consent-start-W-en")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(1200)
    r["after"] = {"popup_open": pg.evaluate("() => document.getElementById('net-consent').open"),
                  "plane_filled": plane_filled(pg), "w": wstate(pg), "toasts": toasts_since(pg, t0),
                  "cfg_state": pg.evaluate("() => fetch('/api/scheduler/config').then(r => r.json()).then(c => c.wiki_lane_state)")}
    r["after"]["tip_rehover"] = tip(pg, "#wiki-toggle")
    R["P4"] = r
    save(OUTF, R)


def p5(pg):
    r = R["P5"] = {}
    # Click W from stopped: the popup opens; read it; Stay offline (never Go online in this sandbox)
    t0 = jsnow(pg)
    pg.mouse.move(2, 400)
    pg.click("#wiki-toggle")
    pg.wait_for_function("() => document.getElementById('net-consent').open", timeout=10000)
    pg.wait_for_function("() => !/^…$/.test(document.getElementById('net-consent-lanes').innerText)", timeout=10000)
    pg.wait_for_timeout(800)
    r["popup"] = consent_read(pg)
    shot(pg, "P5-consent-en")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(800)
    r["after_cancel"] = {"plane_filled": plane_filled(pg), "w": wstate(pg), "toasts": toasts_since(pg, t0)}
    # Offline observations in folder A: Home strip, Living sources -> Wikipedia, World map (note 13)
    pg.click(".nav-item[data-tab='home']")
    pg.wait_for_timeout(2500)
    r["home_stats"] = text(pg, "#home-stats")
    r["home_wiki_figure"] = text(pg, "#home-wiki-figure")
    r["lane_status_api"] = pg.evaluate("() => fetch('/api/wiki/lane/status').then(r => r.json())")
    shot(pg, "P5-home-folderA-en", clip_sel="#home-stats")
    pg.click(".nav-item[data-tab='living']")
    pg.wait_for_timeout(2500)
    r["living_facts"] = text(pg, "#living-wiki-facts")
    r["living_stream"] = text(pg, "#living-stream")
    r["living_junk"] = junk_in(text(pg, "#tab-living"))
    shot(pg, "P5-living-folderA-en")
    pg.click(".nav-item[data-tab='timemap']")
    pg.wait_for_timeout(4000)
    r["map_wiki_button_present"] = pg.query_selector("[data-oomap-wiki]") is not None
    r["map_text"] = (text(pg, "#tab-timemap") or "")[:1500]
    shot(pg, "P5-worldmap-folderA-en")
    R["P5"] = r
    save(OUTF, R)


if __name__ == "__main__":
    main()
