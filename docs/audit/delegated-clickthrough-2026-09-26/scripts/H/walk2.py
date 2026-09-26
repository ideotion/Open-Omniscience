"""Row H, part 2: H3 retry (slow human-like mouse, long rest), H4 Help > Security, H5 discovery toggle, H6 refresh sizes."""
import re
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/H")
from common import (OUT, Recorder, api, close_guide, consent_snapshot, dismiss_coach, dump,  # noqa: E402
                    launch, open_consent_via_plane, pixel_diff, tip_state, unlock_and_enter)

VW, VH = 1440, 950
rep = {"notes": []}
rec = Recorder()


def groups_of(snap):
    return {g["heading"]: [l["label"] for l in g["lanes"]] for g in snap["groups"]}


with sync_playwright() as p:
    br, ctx = launch(p, VW, VH)
    pg = ctx.new_page()
    rec.attach(pg)
    unlock_and_enter(pg, rec, rep["notes"])
    close_guide(pg, rep["notes"])
    pg.wait_for_timeout(1000)
    dismiss_coach(pg, rep["notes"])

    # ---- H3 retry: slow mouse travel, 1.5 s rest, three lanes --------------------------
    open_consent_via_plane(pg)
    retry = []
    for label in ("Press collection", "Hazard feeds", "Chain of custody"):
        span = pg.locator("#net-consent-lanes div > span:not(.muted)", has_text=label).first
        box = span.bounding_box()
        pg.mouse.move(520, 160)
        pg.wait_for_timeout(500)
        off = f"{OUT}/_h3r-off.png"
        pg.screenshot(path=off)
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25)
        pg.wait_for_timeout(1500)
        ts = tip_state(pg)
        on = f"{OUT}/_h3r-on.png"
        pg.screenshot(path=on)
        retry.append({"label": label, "shown": ts["shown"], "opacity": ts["opacity"], "rect": ts["rect"],
                      "diff": pixel_diff(on, off, ts["rect"], VW, VH), "text": ts["text"][:80]})
    pg.screenshot(path=f"{OUT}/H-H3-en-custody-hover-1500ms.png")
    rep["H3_retry"] = retry
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(500)
    dismiss_coach(pg, rep["notes"])

    # ---- H4: Help > Security > the endpoint table --------------------------------------
    pg.click("button.icon-btn[onclick=\"showTab('help')\"]")
    pg.wait_for_selector("#doc-nav .doc-link", timeout=15000)
    sec_btn = pg.locator("#doc-nav .doc-link", has_text=re.compile(r"^\s*Security"))
    rep["H4_doc_links"] = pg.eval_on_selector_all("#doc-nav .doc-link", "els => els.map(e => e.childNodes[0].textContent.trim())")
    sec_btn.first.click()
    pg.wait_for_function("() => document.querySelector('#doc-prose') && document.querySelector('#doc-prose').innerText.includes('Where in the tree')", timeout=15000)
    pg.fill("#doc-find", "Where in the tree")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/H-H4-en.png")
    rep["H4"] = pg.evaluate("""() => {
      const prose = document.getElementById('doc-prose');
      const tables = [...prose.querySelectorAll('table')];
      const t = tables.find(tb => tb.innerText.includes('Where in the tree'));
      const heads = t ? [...t.querySelectorAll('th')].map(th => th.innerText.trim()) : null;
      const rows = t ? [...t.querySelectorAll('tbody tr')].map(tr => [...tr.children].map(td => td.innerText.trim())) : [];
      const marks = [...prose.querySelectorAll('mark')];
      const firstMark = marks[0] ? marks[0].getBoundingClientRect() : null;
      const leadP = [...prose.querySelectorAll('li, p')].find(e => e.innerText.includes('full set of endpoints the app can reach'));
      return {heads, rows, n_tables: tables.length, marks: marks.length,
              firstMarkInView: firstMark ? (firstMark.top >= 0 && firstMark.bottom <= window.innerHeight) : null,
              lead: leadP ? leadP.innerText : null,
              banner: prose.querySelector('.hint') ? prose.querySelector('.hint').innerText : null};
    }""")
    rep["H4_lanes_js"] = pg.evaluate("() => (window.OO_NET_LANES || []).map(l => ({label: l.label, hosts: l.hosts, hostCount: l.hostCount || null}))")
    rec.scan_junk(pg, "help-security", "#doc-prose")
    pg.fill("#doc-find", "")
    pg.wait_for_timeout(300)

    # ---- H5: Settings > Advanced > Safety > External topic discovery ------------------
    pg.click("button[onclick=\"showTab('settings')\"]")
    pg.wait_for_selector("#set-subtabs button[data-tab='advanced']", state="visible", timeout=15000)
    pg.click("#set-subtabs button[data-tab='advanced']")
    pg.wait_for_selector("#set-advanced", state="visible", timeout=10000)
    summ = pg.locator("details[data-adv='safety'] > summary")
    if not pg.evaluate("() => document.querySelector(\"details[data-adv='safety']\").open"):
        summ.click()
    pg.wait_for_selector("#discovery-external", state="visible", timeout=10000)
    pg.wait_for_timeout(800)
    cb = pg.locator("#discovery-external")
    cb.scroll_into_view_if_needed()
    h5 = {"initial_checked": cb.is_checked(),
          "initial_api": (api(pg, "/api/safety/settings") or {}).get("discovery_external_enabled"),
          "fetch_mode_select": pg.eval_on_selector("#fetch-mode", "e => e.options[e.selectedIndex].text")}
    cb.click()
    pg.wait_for_function("() => document.getElementById('discovery-external-result').textContent.trim().length > 0", timeout=8000)
    pg.wait_for_timeout(300)
    h5["on_result"] = pg.inner_text("#discovery-external-result")
    h5["on_toasts"] = pg.eval_on_selector_all("#toast .note", "els => els.map(e => e.textContent)")
    h5["on_api"] = (api(pg, "/api/safety/settings") or {}).get("discovery_external_enabled")
    h5["on_network"] = api(pg, "/api/system/network")
    pg.screenshot(path=f"{OUT}/H-H5-en-checkbox-on.png")
    open_consent_via_plane(pg)
    snap_on = consent_snapshot(pg)
    h5["popup_groups_on"] = groups_of(snap_on)
    pg.screenshot(path=f"{OUT}/H-H5-en-popup-on.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(500)
    dismiss_coach(pg, rep["notes"])
    cb.scroll_into_view_if_needed()
    cb.click()
    pg.wait_for_function("() => document.getElementById('discovery-external-result').textContent.includes('Disabled')", timeout=8000)
    h5["off_result"] = pg.inner_text("#discovery-external-result")
    h5["off_toasts"] = pg.eval_on_selector_all("#toast .note", "els => els.map(e => e.textContent)")
    h5["off_api"] = (api(pg, "/api/safety/settings") or {}).get("discovery_external_enabled")
    open_consent_via_plane(pg)
    h5["popup_groups_off"] = groups_of(consent_snapshot(pg))
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(500)
    dismiss_coach(pg, rep["notes"])
    rep["H5"] = h5

    # ---- H6: Settings > Wikipedia > Refresh exact sizes -------------------------------
    pg.click("#set-subtabs button[data-tab='wikipedia']")
    pg.wait_for_selector("#dump-lang", state="visible", timeout=10000)
    pg.wait_for_function("() => document.querySelectorAll('#dump-lang option').length > 3", timeout=15000)
    sel = pg.locator("#dump-lang")
    sel.scroll_into_view_if_needed()
    h6 = {}
    # first: nothing selected -> the honest refusal, no popup
    pg.evaluate("() => [...document.getElementById('dump-lang').options].forEach(o => o.selected = false)")
    btn = pg.locator("button[onclick='refreshDumpSizes()']")
    btn.click()
    pg.wait_for_timeout(700)
    h6["none_selected_estimate"] = pg.inner_text("#dump-estimate")
    h6["none_selected_popup_open"] = pg.evaluate("() => document.getElementById('net-consent').open")
    # click one edition with the mouse (a real option click in a listbox select)
    opts = pg.eval_on_selector_all("#dump-lang option", "els => els.slice(0,4).map(e => [e.value, e.textContent.trim()])")
    h6["first_options"] = opts
    first_opt = pg.locator("#dump-lang option").nth(1)
    first_opt.click()
    pg.wait_for_timeout(300)
    h6["selected"] = pg.eval_on_selector("#dump-lang", "e => [...e.selectedOptions].map(o => o.value)")
    btn.click()
    pg.wait_for_function(
        "() => { const d = document.getElementById('net-consent'); return d && d.open && "
        "document.querySelectorAll('#net-consent-lanes span[title], #net-consent-lanes span[data-oo-tip]').length > 3 && "
        "document.getElementById('net-consent-ifaces').textContent.trim() !== '…'; }", timeout=15000)
    pg.wait_for_timeout(500)
    snap6 = consent_snapshot(pg)
    h6["popup"] = {k: snap6[k] for k in ("title", "reason", "transport", "ifaces", "cancel", "ok")}
    h6["popup_groups"] = groups_of(snap6)
    h6["popup_caveats"] = [c["text"][:80] for c in snap6["caveats"]]
    pg.screenshot(path=f"{OUT}/H-H6-en.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(1200)
    h6["after_cancel"] = {"popup_open": pg.evaluate("() => document.getElementById('net-consent').open"),
                          "plane_fill": pg.get_attribute("#net-plane", "fill"),
                          "estimate_text": pg.inner_text("#dump-estimate"),
                          "api_network": api(pg, "/api/system/network")}
    dismiss_coach(pg, rep["notes"])
    rep["H6"] = h6
    rec.scan_junk(pg, "settings-wikipedia", "#set-wikipedia")
    ctx.close()
    br.close()

rep["page_errors"], rep["console_errors"], rep["http_errors"], rep["junk"] = (
    rec.page_errors, rec.console_errors, rec.http_errors, rec.junk)
dump(rep, "part2.json")
print("done")
