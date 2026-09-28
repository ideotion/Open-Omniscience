"""Row O walk, instance A: O9 locale re-check (fr, ar full; zh spot check) through the real
top-bar switcher. Usage: walk_loc.py fr ar zh"""
import sys

from playwright.sync_api import sync_playwright

from lib import (OUT, Rec, close_guide, consent_lanes, junk, living_open, living_sub, open_consent,
                 save, settings_sub, shot, storage_ready, switch_lang, tip_of, txt, unhover)

BASE = "http://127.0.0.1:8834"
langs = sys.argv[1:]
rec = Rec()
R = {}

ORDER_JS = """([sel, sub, a, b]) => {
  // visual order of two characters of the first text node under `sel` holding `sub`:
  // returns true when char #a is drawn LEFT of char #b (i.e. read in LTR order).
  const root = document.querySelector(sel); if (!root) return 'no-root';
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode())) {
    const i = n.data.indexOf(sub); if (i < 0) continue;
    const r1 = document.createRange(); r1.setStart(n, i + a); r1.setEnd(n, i + a + 1);
    const r2 = document.createRange(); r2.setStart(n, i + b); r2.setEnd(n, i + b + 1);
    const x1 = r1.getBoundingClientRect(), x2 = r2.getBoundingClientRect();
    if (!x1.width && !x2.width) return 'not-rendered';
    return {a_left: Math.round(x1.left), b_left: Math.round(x2.left), ltr_order: x1.left < x2.left};
  }
  return 'not-found';
}"""


def order(pg, sel, sub, a=0, b=1):
    return pg.evaluate(ORDER_JS, [sel, sub, a, b])


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking",
                                 "--disable-component-update", "--no-proxy-server"])
    ctx = br.new_context(viewport={"width": 1440, "height": 950})
    pg = ctx.new_page()
    rec.watch(pg, "A-loc")
    pg.goto(BASE + "/", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    close_guide(pg)
    import traceback
    try:
        for loc in langs:
            o = R[loc] = {}
            o["switched"] = switch_lang(pg, loc, rec)
            o["html_lang"] = pg.evaluate("() => document.documentElement.lang")
            o["html_dir"] = pg.evaluate("() => document.documentElement.dir || getComputedStyle(document.documentElement).direction")
            o["sidebar_living"] = pg.evaluate("() => document.querySelector(\".nav-item[data-tab='living'] span\").innerText")
            full = loc in ("fr", "ar")
            # ---- Storage (O1) ----
            if full:
                settings_sub(pg, "data")
                storage_ready(pg)
                o["subtabs"] = pg.evaluate("() => [...document.querySelectorAll('#set-subtabs button')].map(b => b.innerText.trim())")
                o["storage"] = txt(pg, "#storage-panel")
                o["storage_junk"] = junk(pg, "#storage-panel")
                o["storage_order_plus6"] = order(pg, "#storage-lanes", "+6.0", 0, 1)
                o["storage_order_rate"] = order(pg, "#storage-lanes", "+9.5", 0, 1)
                tips = o["storage_tips"] = {}
                tips["reading"] = tip_of(pg, pg.locator("#storage-reading > div").first)
                tips["wiki_lane_name"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(2) td:first-child"))
                tips["corpus_growth"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(1) td:nth-child(4) span").first)
                tips["wiki_not_measured"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(2) td:nth-child(4) span").first)
                tips["no_published_budget"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(1) td:nth-child(3) span").first)
                tips["not_built_yet"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(3) td:nth-child(2) span").first)
                tips["caveat"] = tip_of(pg, pg.locator("#storage-panel > p.card-caveat"))
                unhover(pg)
                shot(pg, f"O-O9-storage-{loc}.png")
            # ---- Living sources (O3-O5) ----
            living_open(pg)
            o["living_heading"] = txt(pg, "#tab-living h2")
            o["living_subtabs"] = pg.evaluate("() => [...document.querySelectorAll('#living-subtabs button')].map(b => b.innerText.trim())")
            o["living_status"] = txt(pg, "#living-status")
            o["living_caveat"] = txt(pg, "#living-caveat")
            o["wiki_facts"] = txt(pg, "#living-wiki-facts")
            o["stream_cap"] = txt(pg, "#living-stream-cap")
            o["stream"] = txt(pg, "#living-stream")
            o["pages"] = txt(pg, "#living-pages")
            o["tc_before"] = txt(pg, "#wiki-tc-body")
            o["living_junk_wiki"] = junk(pg, "#living-wiki")
            o["order_delta_plus38"] = order(pg, "#living-stream", "+38", 0, 1)
            o["order_delta_minus120"] = order(pg, "#living-stream", "-120", 0, 1)
            o["order_date_year_first"] = order(pg, "#living-stream", "2026-09", 0, 5)
            ftips = o["wiki_fact_tips"] = []
            facts = pg.locator("#living-wiki-facts .living-fact[title], #living-wiki-facts .living-fact.oo-tip-target")
            for i in range(min(facts.count(), 3 if not full else 9)):
                ftips.append(tip_of(pg, facts.nth(i), wait=600))
            unhover(pg)
            shot(pg, f"O-O9-living-wiki-{loc}.png", full=True)
            if full:
                row = pg.locator("#living-stream .living-row").filter(has_text="Walk Rome").filter(has_text="+38")
                row.locator("button").first.click()
                pg.wait_for_selector("#living-stream .living-diff", timeout=8000)
                pg.wait_for_timeout(700)
                o["diff"] = txt(pg, "#living-stream .living-diff")
                o["diff_note"] = pg.evaluate("() => document.querySelector('#living-stream .living-diff').parentElement.innerText")
                o["diff_button_after"] = row.locator("button").first.inner_text()
                o["diff_line_bidi"] = pg.evaluate("() => [...document.querySelectorAll('#living-stream .living-diff-l')].map(e => getComputedStyle(e).unicodeBidi + '/' + getComputedStyle(e).direction)")
                o["order_diff_plus_rome"] = order(pg, "#living-stream .living-diff", "+Rome is the capital", 0, 1)
                o["order_diff_plus_rome_end"] = order(pg, "#living-stream .living-diff", "+Rome is the capital city of Italy.", 0, 34)
                o["order_diff_minus"] = order(pg, "#living-stream .living-diff", "-Rome is a city.", 0, 1)
                row.scroll_into_view_if_needed()
                shot(pg, f"O-O9-wiki-diff-{loc}.png")
                row.locator("button").first.click()
                pg.wait_for_timeout(500)
                pg.locator("#living-pages button.living-page", has_text="Walk Tracked Page").click()
                pg.wait_for_function("() => document.querySelectorAll('#wiki-tc-body .living-diff-l, #wiki-tc-body div').length > 2", timeout=10000)
                pg.wait_for_timeout(900)
                o["tc_title"] = txt(pg, "#wiki-tc-title")
                o["tc_body"] = txt(pg, "#wiki-tc-body")
                o["tc_method"] = txt(pg, "#wiki-tc-method")
                o["order_tc_minus3000"] = order(pg, "#wiki-tc-body", "-3000", 0, 1)
                o["order_tc_plus_line"] = order(pg, "#wiki-tc-body", "+A new paragraph", 0, 1)
                o["order_tc_plus812"] = order(pg, "#wiki-tc-body", "+812", 0, 1)
                pg.locator("#wiki-tc").scroll_into_view_if_needed()
                shot(pg, f"O-O9-tracked-{loc}.png")
                living_sub(pg, "law")
                o["law_facts"] = txt(pg, "#living-law-facts")
                o["law_changes"] = txt(pg, "#living-law-changes")
                pg.locator("#living-law-changes details summary").first.click()
                pg.wait_for_timeout(600)
                o["law_diff"] = txt(pg, "#living-law-changes details .living-diff")
                o["order_law_minus640"] = order(pg, "#living-law-changes", "-640", 0, 1)
                o["order_law_plus_line"] = order(pg, "#living-law-changes .living-diff", "+Article 12", 0, 1)
                o["living_junk_law"] = junk(pg, "#living-law")
                shot(pg, f"O-O9-law-{loc}.png", full=True)
                living_sub(pg, "osm")
                o["maps_facts"] = txt(pg, "#living-osm-facts")
                o["maps_regions"] = txt(pg, "#living-osm-regions")
                f = pg.locator("#living-osm-facts .living-fact[title], #living-osm-facts .living-fact.oo-tip-target")
                o["maps_tips"] = [tip_of(pg, f.nth(i), wait=500) for i in range(f.count())]
                unhover(pg)
                o["living_junk_maps"] = junk(pg, "#living-osm")
                shot(pg, f"O-O9-maps-{loc}.png", full=True)
                living_sub(pg, "wiki")
                # ---- Task manager (O6) ----
                close_guide(pg)
                from lib import clear_coach_if_blocking
                clear_coach_if_blocking(pg, "#tm-open", "task manager icon")
                with ctx.expect_page(timeout=15000) as newp:
                    pg.click("#tm-open")
                tm = newp.value
                rec.watch(tm, f"A-tasks-{loc}")
                tm.wait_for_load_state("networkidle", timeout=30000)
                tm.wait_for_timeout(2500)
                o["tm_lang"] = tm.evaluate("() => document.documentElement.lang")
                o["tm_dir"] = tm.evaluate("() => document.documentElement.dir")
                o["tm_title"] = tm.title()
                o["tm_jobs"] = tm.evaluate("() => document.getElementById('jobs-body').innerText")
                o["tm_junk"] = junk(tm, "#jobs-body")
                tm.screenshot(path=f"{OUT}/O-O9-taskmanager-{loc}.png", full_page=True)
                tm.close()
                # ---- Export row (O7) ----
                settings_sub(pg, "data")
                pg.locator("#set-data button[onclick='openUnifiedExport()']").click()
                pg.wait_for_function("() => document.getElementById('ux-export').open && document.querySelectorAll('#ux-checklist label').length > 2", timeout=15000)
                pg.wait_for_timeout(800)
                o["export_rows"] = pg.evaluate("() => [...document.querySelectorAll('#ux-checklist label')].map(l => l.innerText.trim())")
                lab = pg.locator("#ux-checklist label:has(#ux-c-lanes)")
                o["export_living_tip"] = tip_of(pg, lab) if lab.count() else "row not found"
                o["export_living_state"] = pg.evaluate("() => { const i = document.getElementById('ux-c-lanes'); return i ? {checked: i.checked, disabled: i.disabled} : null; }")
                shot(pg, f"O-O9-export-{loc}.png")
                unhover(pg)
                pg.locator("#ux-export button[onclick*='close()']").first.click()
                pg.wait_for_timeout(400)
            # ---- Consent popup, protected mode (O8) ----
            open_consent(pg)
            o["consent_body"] = txt(pg, "#net-consent-body")
            o["consent_buttons"] = pg.evaluate("() => [...document.querySelectorAll('#net-consent button')].map(b => b.innerText)")
            o["consent_lanes"] = consent_lanes(pg, hover=True, limit=None if full else 3)
            o["consent_junk"] = junk(pg, "#net-consent")
            # one hover drawn into the screenshot
            tip_of(pg, pg.locator("#net-consent-lanes div > span:first-child").nth(2))
            shot(pg, f"O-O9-consent-{loc}.png")
            unhover(pg)
            pg.click("#net-consent-cancel")
            pg.wait_for_timeout(1200)
            o["after_cancel"] = {"closed": not pg.evaluate("() => document.getElementById('net-consent').open"),
                                 "plane_fill": pg.evaluate("() => document.getElementById('net-plane').getAttribute('fill')"),
                                 "coach_visible": pg.is_visible("#net-coach"),
                                 "coach_text": txt(pg, "#net-coach .coach-body")}
            if loc == "fr":
                # right after Stay offline: open the language menu; it must sit above the coach
                pg.click("#lang-switch")
                pg.wait_for_selector("#lang-menu", state="visible", timeout=5000)
                pg.wait_for_timeout(500)
                o["menu_over_coach"] = pg.evaluate("""() => {
                  const menu = document.getElementById('lang-menu'); const coach = document.getElementById('net-coach');
                  const items = [...menu.querySelectorAll('[data-lang]')];
                  const cr = coach.getBoundingClientRect(); const mr = menu.getBoundingClientRect();
                  const res = items.map(it => { const r = it.getBoundingClientRect();
                    const x = r.left + r.width / 2, y = r.top + r.height / 2; const hit = document.elementFromPoint(x, y);
                    return {lang: it.dataset.lang, clickable: !!hit && (hit === it || it.contains(hit))}; });
                  const overlap = !(mr.right < cr.left || mr.left > cr.right || mr.bottom < cr.top || mr.top > cr.bottom);
                  return {coach_visible: getComputedStyle(coach).display !== 'none' && cr.width > 0, overlap,
                          menu_z: getComputedStyle(menu).zIndex, coach_z: getComputedStyle(coach).zIndex,
                          items: res, all_clickable: res.every(r => r.clickable)}; }""")
                shot(pg, "O-O9-langmenu-over-coach-fr.png")
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(400)
                if pg.is_visible("#lang-menu"):
                    pg.click("#lang-switch")
                    pg.wait_for_timeout(300)
        switch_lang(pg, "en", rec)
        R["back_to_en"] = pg.evaluate("() => document.documentElement.lang")
    except Exception:
        R["_exception"] = traceback.format_exc()[-3000:]
        print(R["_exception"])
        try:
            shot(pg, "_fail-loc.png")
        except Exception:
            pass
    from lib import COACH_BLOCKS
    save(f"raw-loc-{'-'.join(langs)}.json", {"R": R, "coach_blocks": COACH_BLOCKS, "page_errors": rec.page_errors,
                                              "console_errors": rec.console_errors, "http": rec.http})
    br.close()
print("done", langs)
