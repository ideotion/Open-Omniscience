"""Row O walk, instance A (encrypted, seeded), en pass at 1440x950: O1-O8, O11 (offline part),
O13a (doctor on the encrypted throwaway), O14a (legacy panel on a non-migrated install).
Usage: walk_a.py <phase> [...]   phases: unlock o1 o2 o3o4 o5 o6 o7 o8 o11 doctor o14a
"""
import sys

from playwright.sync_api import sync_playwright

from lib import (OUT, Rec, api, close_guide, consent_lanes, junk, living_open, living_sub, nav,
                 open_consent, save, settings_sub, shot, storage_ready, tip_of, txt, unhover, unlock)

BASE = "http://127.0.0.1:8834"
PASS = "walk-pass-2026"
phases = sys.argv[1:]
rec = Rec()
R = {}


def page_new(br, w=1440, h=950):
    ctx = br.new_context(viewport={"width": w, "height": h})
    pg = ctx.new_page()
    rec.watch(pg, "A")
    return ctx, pg


def goto_app(pg):
    pg.goto(BASE + "/", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    close_guide(pg)


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking",
                                 "--disable-component-update", "--no-proxy-server"])
    ctx, pg = page_new(br)

    import traceback
    try:
        if "unlock" in phases:
            R["unlock"] = unlock(pg, BASE, PASS)
            R["unlock"]["guide_open_after_unlock"] = pg.evaluate(
                "() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }")
            shot(pg, "O-unlock-home-en.png")
            close_guide(pg)
            R["unlock"]["lock_state"] = api(pg, "/api/system/lock-state")
            R["unlock"]["network"] = api(pg, "/api/system/network")
        else:
            goto_app(pg)

        if "o1" in phases:
            o = R["O1"] = {}
            settings_sub(pg, "data")
            storage_ready(pg)
            o["subtabs"] = pg.evaluate("() => [...document.querySelectorAll('#set-subtabs button')].map(b => b.innerText.trim())")
            o["storage_first_panel_in_data"] = pg.evaluate(
                "() => { const v = document.getElementById('set-data'); const p = v.querySelector('section.panel'); return p && p.id; }")
            o["reading"] = txt(pg, "#storage-reading")
            o["table"] = pg.evaluate("""() => { const t = document.querySelector('#storage-lanes table');
                return {head: [...t.querySelectorAll('thead th')].map(e => e.innerText.trim()),
                        rows: [...t.querySelectorAll('tbody tr')].map(r => [...r.children].map(c => c.innerText.trim()))}; }""")
            o["disk"] = txt(pg, "#storage-disk")
            o["disk_caveat_class"] = pg.evaluate("() => !!document.querySelector('#storage-disk .card-caveat')")
            o["caveat"] = txt(pg, "#storage-panel > p.card-caveat")
            o["colors_red_green"] = pg.evaluate("""() => [...document.querySelectorAll('#storage-panel *')].map(e => getComputedStyle(e).color)
                .filter((c, i, a) => a.indexOf(c) === i)""")
            o["verdict_words"] = [w for w in ("too small", "enough", "insufficient", "will be full", "full in", "days left")
                                  if w in (txt(pg, "#storage-panel") or "").lower()]
            shot(pg, "O-O1-storage-en.png")
            tips = o["tips"] = {}
            tips["reading"] = tip_of(pg, pg.locator("#storage-reading > div[title], #storage-reading > div.oo-tip-target").first)
            tips["wiki_lane_name"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(2) td:first-child"))
            tips["corpus_growth"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(1) td:nth-child(4) span").first)
            tips["wiki_not_measured"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(2) td:nth-child(4) span").first)
            tips["no_published_budget"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(1) td:nth-child(3) span").first)
            tips["not_built_yet"] = tip_of(pg, pg.locator("#storage-lanes tbody tr:nth-child(3) td:nth-child(2) span").first)
            tips["caveat"] = tip_of(pg, pg.locator("#storage-panel > p.card-caveat"))
            unhover(pg)
            o["junk"] = junk(pg, "#storage-panel")
            o["api"] = api(pg, "/api/storage/lanes")

        if "o2" in phases:
            o = R["O2"] = {}
            settings_sub(pg, "data")
            storage_ready(pg)

            def wiki_row():
                return pg.evaluate("() => [...document.querySelectorAll('#storage-lanes tbody tr')][1].innerText")

            def try_budget(val, label):
                pg.fill("#storage-budget-wiki", str(val))
                pg.click("#storage-lanes tbody tr:nth-child(2) button")
                pg.wait_for_timeout(1500)
                return {"typed": val, "msg": txt(pg, "#storage-budget-msg-wiki"),
                        "input_value": pg.input_value("#storage-budget-wiki"),
                        "bold": pg.evaluate("() => (document.querySelector('#storage-lanes tbody tr:nth-child(2) td:nth-child(3) b') || {}).innerText"),
                        "row": wiki_row(), "disk": txt(pg, "#storage-disk"),
                        "disk_caveat": pg.evaluate("() => !!document.querySelector('#storage-disk .card-caveat')"),
                        "config": api(pg, "/api/scheduler/config")["body"][:4000]}
            o["35"] = try_budget(35, "35")
            o["1.5"] = try_budget(1.5, "1.5")
            o["5000"] = try_budget(5000, "5000")
            shot(pg, "O-O2-refused-5000-en.png")
            o["2000"] = try_budget(2000, "2000")
            shot(pg, "O-O2-budget-2000-en.png")
            # the wizard: one setting, two doors
            settings_sub(pg, "wikipedia")
            pg.click("#wiki-wizard-open")
            pg.wait_for_timeout(1500)
            o["consent_opened_by_wizard"] = pg.evaluate("() => document.getElementById('net-consent').open")
            o["wizard_open"] = pg.evaluate("() => document.getElementById('wiki-wizard').open")
            o["wizard_budget_value"] = pg.input_value("#wiki-wizard-budget") if o["wizard_open"] else None
            o["wizard_budget_box"] = pg.evaluate("""() => { const i = document.getElementById('wiki-wizard-budget');
                return i ? i.closest('div').parentElement.innerText : null; }""")
            o["wizard_share"] = txt(pg, "#wiki-wizard-share")
            shot(pg, "O-O2-wizard-en.png")
            pg.click("#wiki-wizard-cancel")
            pg.wait_for_timeout(600)
            o["wizard_closed"] = not pg.evaluate("() => document.getElementById('wiki-wizard').open")
            settings_sub(pg, "data")
            storage_ready(pg)
            o["20"] = try_budget(20, "20")

        if "o3o4" in phases:
            o = R["O3"] = {}
            o["sidebar_order"] = pg.evaluate("() => [...document.querySelectorAll('.nav-item')].map(b => b.dataset.tab)")
            living_open(pg)
            o["active_nav"] = pg.evaluate("() => (document.querySelector('.nav-item.active') || {}).dataset?.tab")
            o["is_dialog"] = pg.evaluate("() => !!document.querySelector('dialog[open]')")
            o["heading"] = txt(pg, "#tab-living h2")
            o["subtabs"] = pg.evaluate("() => [...document.querySelectorAll('#living-subtabs button')].map(b => [b.innerText.trim(), b.getAttribute('aria-selected')])")
            o["status"] = txt(pg, "#living-status")
            o["caveat"] = txt(pg, "#living-caveat")
            o["facts"] = pg.evaluate("""() => { const box = document.getElementById('living-wiki-facts'); const out = []; let g = null;
                for (const el of box.children) { if (el.tagName === 'H3') { g = {title: el.innerText, facts: []}; out.push(g); }
                  else if (g) { for (const f of el.querySelectorAll('.living-fact')) g.facts.push([f.children[0].innerText, f.children[1].innerText]); } }
                return out; }""")
            o["stream_cap"] = txt(pg, "#living-stream-cap")
            o["stream_rows"] = pg.evaluate("() => [...document.querySelectorAll('#living-stream .living-row')].map(r => r.innerText)")
            o["stream_buttons"] = pg.evaluate("() => [...document.querySelectorAll('#living-stream .living-row')].map(r => [...r.querySelectorAll('button')].map(b => b.innerText))")
            o["junk"] = junk(pg, "#tab-living")
            shot(pg, "O-O3-living-wiki-en.png", full=True)
            tips = o["tips"] = {}
            facts = pg.locator("#living-wiki-facts .living-fact")
            for i in range(facts.count()):
                lab = facts.nth(i).locator("div").first.inner_text()
                if lab in ("Last change recorded", "Complete through"):
                    tips[lab] = tip_of(pg, facts.nth(i))
            tips["+38"] = tip_of(pg, pg.locator("#living-stream .living-delta").first)
            tips["log"] = tip_of(pg, pg.locator("#living-stream .pill[title], #living-stream .pill[data-oo-tip]").first)
            unhover(pg)
            # O4
            o = R["O4"] = {}
            o["tc_before"] = txt(pg, "#wiki-tc-body")
            rome_edit = pg.locator("#living-stream .living-row").filter(has_text="Walk Rome").filter(has_text="+38")
            rome_edit.locator("button", has_text="Show diff").click()
            pg.wait_for_selector("#living-stream .living-diff", timeout=8000)
            pg.wait_for_timeout(600)
            o["diff"] = txt(pg, "#living-stream .living-diff")
            o["diff_has_b_element"] = pg.evaluate("() => !!document.querySelector('#living-stream .living-diff b')")
            o["diff_note"] = pg.evaluate("() => { const d = document.querySelector('#living-stream .living-diff'); return d.parentElement.innerText; }")
            o["diff_button_label"] = rome_edit.locator("button").first.inner_text()
            o["diff_in_place_under_row"] = pg.evaluate("() => !!document.querySelector('#living-stream .living-row .living-diff')")
            rome_edit.scroll_into_view_if_needed()
            shot(pg, "O-O4-diff-en.png")
            rome_edit.locator("button", has_text="Hide diff").click()
            pg.wait_for_timeout(600)
            o["diff_after_hide"] = pg.evaluate("() => !!document.querySelector('#living-stream .living-diff') && document.querySelector('#living-stream .living-diff').offsetParent !== null")
            o["page_buttons"] = pg.evaluate("() => [...document.querySelectorAll('#living-pages button.living-page')].map(b => b.innerText)")
            pg.locator("#living-pages button.living-page", has_text="Walk Tracked Page").click()
            pg.wait_for_function("() => /\\S/.test(document.getElementById('wiki-tc-body').innerText) && !/Pick a page|Loading/.test(document.getElementById('wiki-tc-body').innerText)", timeout=10000)
            pg.wait_for_timeout(700)
            o["tc_title"] = txt(pg, "#wiki-tc-title")
            o["tc_body"] = txt(pg, "#wiki-tc-body")
            o["tc_method"] = txt(pg, "#wiki-tc-method")
            o["tc_in_tab"] = pg.evaluate("() => !!document.querySelector('#tab-living #wiki-tc')")
            o["dialog_open"] = pg.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)")
            pg.locator("#wiki-tc").scroll_into_view_if_needed()
            shot(pg, "O-O4-tracked-en.png")
            pg.check("#wiki-tc-flagged")
            pg.wait_for_timeout(1500)
            o["tc_flagged_only"] = txt(pg, "#wiki-tc-body")
            pg.uncheck("#wiki-tc-flagged")
            pg.wait_for_timeout(1500)
            o["tc_unflagged"] = txt(pg, "#wiki-tc-body")
            # Settings -> Wikipedia -> Watch a page -> Tracked changes
            settings_sub(pg, "wikipedia")
            pg.wait_for_function("() => /Walk Tracked Page/.test((document.getElementById('wiki-pages') || {}).innerText || '')", timeout=15000)
            o["wiki_pages_table"] = txt(pg, "#wiki-pages")
            pg.locator("#wiki-pages tr", has_text="Walk Tracked Page").locator("button", has_text="Tracked changes").click()
            pg.wait_for_timeout(2500)
            o["from_settings"] = {
                "active_nav": pg.evaluate("() => (document.querySelector('.nav-item.active') || {}).dataset?.tab"),
                "living_visible": pg.is_visible("#tab-living"),
                "tc_title": txt(pg, "#wiki-tc-title"), "tc_body_head": (txt(pg, "#wiki-tc-body") or "")[:200],
                "dialog_open": pg.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)"),
                "url": pg.url}
            shot(pg, "O-O4-from-settings-en.png")
            pg.goto(BASE + "/?wikitc=1", wait_until="networkidle", timeout=60000)
            pg.wait_for_timeout(1500)
            close_guide(pg)
            try:
                pg.wait_for_function("() => !/Pick a page|Loading/.test((document.getElementById('wiki-tc-body') || {}).innerText || 'Pick a page')", timeout=15000)
            except Exception as exc:
                o["deeplink_wait_error"] = str(exc)[:200]
            pg.wait_for_timeout(800)
            o["deep_link"] = {
                "active_nav": pg.evaluate("() => (document.querySelector('.nav-item.active') || {}).dataset?.tab"),
                "living_visible": pg.is_visible("#tab-living"),
                "tc_title": txt(pg, "#wiki-tc-title"), "tc_body_head": (txt(pg, "#wiki-tc-body") or "")[:200],
                "dialog_open": pg.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)"),
                "dialog_wiki_tc_exists": pg.evaluate("() => !!document.querySelector('dialog#wiki-tc')"),
                "url": pg.url}
            shot(pg, "O-O4-deeplink-en.png")

        if "o5" in phases:
            o = R["O5"] = {}
            living_open(pg)
            living_sub(pg, "law")
            o["law_facts"] = txt(pg, "#living-law-facts")
            o["law_changes"] = txt(pg, "#living-law-changes")
            pg.locator("#living-law-changes details summary").first.click()
            pg.wait_for_timeout(600)
            o["law_diff"] = txt(pg, "#living-law-changes details .living-diff")
            o["law_links"] = pg.evaluate("() => [...document.querySelectorAll('#living-law-changes a')].map(a => [a.innerText, a.href])")
            link = pg.locator("#living-law-changes a", has_text="Read locally").first
            o["read_locally_tip"] = tip_of(pg, link)
            o["read_locally_href"] = link.evaluate("a => a.href")
            unhover(pg)
            shot(pg, "O-O5-law-en.png", full=True)
            o["junk_law"] = junk(pg, "#living-law")
            living_sub(pg, "osm")
            o["maps_facts"] = txt(pg, "#living-osm-facts")
            o["maps_regions"] = txt(pg, "#living-osm-regions")
            f = pg.locator("#living-osm-facts .living-fact", has_text="Date of the map data")
            o["maps_date_tip"] = tip_of(pg, f.first) if f.count() else None
            unhover(pg)
            shot(pg, "O-O5-maps-en.png", full=True)
            o["junk_maps"] = junk(pg, "#living-osm")

        if "o6" in phases:
            o = R["O6"] = {}
            close_guide(pg)
            o["tm_open_title"] = pg.get_attribute("#tm-open", "title")
            with ctx.expect_page(timeout=15000) as newp:
                pg.click("#tm-open")
            tm = newp.value
            rec.watch(tm, "A-tasks")
            tm.wait_for_load_state("networkidle", timeout=30000)
            try:
                tm.wait_for_function("() => /Downloads/i.test(document.getElementById('jobs-body').innerText)", timeout=20000)
            except Exception as exc:
                o["wait_error"] = str(exc)[:200]
            tm.wait_for_timeout(1500)
            o["url"], o["title"] = tm.url, tm.title()
            o["active_tab"] = tm.evaluate("() => (document.querySelector('#tm-tabs button.active') || {}).innerText")
            o["jobs_body"] = tm.evaluate("() => document.getElementById('jobs-body').innerText")
            o["junk"] = junk(tm, "#jobs-body")
            tm.screenshot(path=f"{OUT}/O-O6-taskmanager-en.png", full_page=True)
            tm.close()

        if "o7" in phases:
            o = R["O7"] = {}
            settings_sub(pg, "data")
            pg.click("button:has-text('Export / Back up…')")
            pg.wait_for_function("() => document.getElementById('ux-export').open && document.querySelectorAll('#ux-checklist label').length > 2", timeout=15000)
            pg.wait_for_timeout(800)
            o["rows"] = pg.evaluate("""() => [...document.querySelectorAll('#ux-checklist label')].map(l => {
                const i = l.querySelector('input'); return {text: l.innerText.trim(), checked: i.checked, disabled: i.disabled,
                title: l.getAttribute('title') || l.dataset.ooTip || null}; })""")
            row = pg.locator("#ux-checklist label", has_text="Living sources")
            o["living_row_count"] = row.count()
            if row.count():
                o["living_tip"] = tip_of(pg, row.first)
                # try to tick it through a real click: it must stay unticked
                try:
                    row.first.locator("input").click(timeout=2000, force=True)
                except Exception as exc:
                    o["tick_click_error"] = str(exc)[:120]
                pg.wait_for_timeout(300)
                o["living_checked_after_click"] = row.first.locator("input").is_checked()
            shot(pg, "O-O7-export-en.png")
            unhover(pg)
            o["inventory"] = api(pg, "/api/backup/inventory")["body"][:3000]
            o["storage_wiki"] = api(pg, "/api/storage/lanes")["body"][:1500]
            pg.click("#ux-export button:has-text('Close')")
            pg.wait_for_timeout(400)
            o["closed"] = not pg.evaluate("() => document.getElementById('ux-export').open")

        if "o8" in phases:
            o = R["O8"] = {}
            for mode, label in (("transparent", "a"), ("protected", "b")):
                settings_sub(pg, "advanced")
                det = pg.locator("details[data-adv='safety']")
                if not det.evaluate("d => d.open"):
                    det.locator("summary").first.click()
                    pg.wait_for_timeout(600)
                pg.select_option("#fetch-mode", mode)
                pg.fill("#http-proxy", "socks5h://127.0.0.1:9")
                pg.click("button:has-text('Save fetch mode')")
                pg.wait_for_timeout(1200)
                r = o[label] = {"toast": txt(pg, "#toast"), "safety": api(pg, "/api/safety/settings")["body"][:1500]}
                open_consent(pg)
                r["title"] = txt(pg, "#net-consent h3, #net-consent header")
                r["reason"] = txt(pg, "#net-consent-reason")
                r["lanes"] = consent_lanes(pg, hover=True)
                r["ifaces"] = txt(pg, "#net-consent-ifaces")
                r["body"] = txt(pg, "#net-consent-body")
                r["junk"] = junk(pg, "#net-consent")
                shot(pg, f"O-O8{label}-consent-{mode}-en.png")
                pg.click("#net-consent-cancel")
                pg.wait_for_timeout(1500)
                r["consent_closed"] = not pg.evaluate("() => document.getElementById('net-consent').open")
                r["plane_fill"] = pg.evaluate("() => { const p = document.getElementById('net-plane'); return p ? p.getAttribute('fill') : null; }")
                r["coach_visible"] = pg.is_visible("#net-coach")
                r["coach_text"] = txt(pg, "#net-coach .coach-body")
                r["network"] = api(pg, "/api/system/network")["body"][:600]
                if label == "b":
                    shot(pg, "O-O8b-after-stay-offline-en.png")

        if "o11" in phases:
            o = R["O11"] = {}
            close_guide(pg)
            o["wiki_toggle_tip_offline"] = tip_of(pg, pg.locator("#wiki-toggle"))
            unhover(pg)
            open_consent(pg)
            o["consent_body"] = txt(pg, "#net-consent-body")
            o["buttons"] = pg.evaluate("() => [...document.querySelectorAll('#net-consent button')].map(b => b.innerText)")
            shot(pg, "O-O11-consent-before-cancel-en.png")
            pg.click("#net-consent-cancel")
            pg.wait_for_timeout(800)
            o["network_after"] = api(pg, "/api/system/network")["body"][:600]
            o["scheduler_wiki_lane"] = api(pg, "/api/scheduler/status")["body"][:2500]

        if "doctor" in phases:
            o = R["O13a"] = {}
            pg.goto(BASE + "/api/system/doctor", wait_until="load", timeout=30000)
            o["doctor_text"] = pg.evaluate("() => document.body.innerText")[:6000]
            shot(pg, "O-O13a-doctor-en.png", full=True)
            goto_app(pg)
            settings_sub(pg, "advanced")
            det = pg.locator("details[data-adv='safety']")
            if not det.evaluate("d => d.open"):
                det.locator("summary").first.click()
                pg.wait_for_timeout(1500)
            o["atrest_box"] = pg.evaluate("""() => { const m = document.getElementById('atrest-msg'); const d = m && m.closest('details');
                return d ? d.innerText.slice(0, 1500) : null; }""")

        if "o14a" in phases:
            o = R["O14a"] = {}
            settings_sub(pg, "advanced")
            det = pg.locator("details[data-adv='collect']")
            if not det.evaluate("d => d.open"):
                det.locator("summary").first.click()
                pg.wait_for_timeout(600)
            pg.locator("details.adv-collect summary", has_text="Advanced (legacy)").click()
            pg.wait_for_timeout(1500)
            o["mode_select_present"] = pg.evaluate("() => !!document.getElementById('sch-mode') || [...document.querySelectorAll('#tab-settings label')].some(l => /^\\s*Mode\\s*$/.test(l.innerText) && l.htmlFor !== 'fetch-mode')")
            o["retired_notice_visible"] = pg.is_visible("#sch-retired")
            o["depth_visible"] = pg.is_visible("#sch-depth")
            o["pages_visible"] = pg.is_visible("#sch-pages")
            o["market_rules_checked"] = pg.is_checked("#sch-market-rules")
            o["stat_refresh_checked"] = pg.is_checked("#sch-stat-refresh")
            o["panel_text"] = pg.evaluate("() => document.querySelector(\"details[data-adv='collect']\").innerText.slice(0, 3000)")
            pg.locator("#sch-depth").scroll_into_view_if_needed()
            shot(pg, "O-O14a-scheduler-en.png")

        if "fixups" in phases:
            o = R["fixups"] = {}
            o["plane_fill_idle"] = pg.evaluate("() => document.getElementById('net-plane').getAttribute('fill')")
            living_open(pg)
            logpill = pg.locator("#living-stream .pill", has_text="log")
            o["log_pill_count"] = logpill.count()
            o["log_pill_text"] = logpill.first.inner_text() if logpill.count() else None
            o["log_tip"] = tip_of(pg, logpill.first) if logpill.count() else None
            unhover(pg)
            shot(pg, "O-O3-log-hover-en.png")
    except Exception:
        R["_exception"] = traceback.format_exc()[-3000:]
        print(R["_exception"])
        try:
            shot(pg, "_fail-a.png")
        except Exception:
            pass
    save(f"raw-a-{'-'.join(phases)}.json", {"R": R, "page_errors": rec.page_errors,
                                             "console_errors": rec.console_errors, "http": rec.http})
    br.close()
print("done", phases)
