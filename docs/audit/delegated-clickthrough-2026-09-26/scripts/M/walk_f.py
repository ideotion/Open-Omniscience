"""Phase F: M9 consent lanes timing retry (en)."""
import json
import sys
import time

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa

BASE = "http://127.0.0.1:8826"
R = {}


def tip_text(page):
    return page.evaluate("() => { const t=document.getElementById('oo-tip'); return t && t.classList.contains('show') ? t.textContent : null; }")


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", lambda d: d.dismiss())
    unlock_if_needed(page, BASE)
    close_guide(page)
    R["lang"] = page.evaluate("document.documentElement.lang")
    R["OO_NET_LANES_len"] = page.evaluate("() => (window.OO_NET_LANES||[]).length")
    R["ring_lane"] = page.evaluate("() => JSON.stringify((window.OO_NET_LANES||[]).filter(l => /Keyword|wikidata/i.test(JSON.stringify(l))))")
    open_settings_advanced(page)
    open_adv(page, "keywords")
    page.locator("#ring-limit").scroll_into_view_if_needed()
    page.fill("#ring-limit", "5")
    page.click("section.panel:has(#ring-gaps) button:has-text('Load from Wikidata')")
    page.wait_for_selector("#net-consent[open]", timeout=10000)
    t0 = time.time()
    seq = []
    last = None
    while time.time() - t0 < 20:
        s = page.inner_text("#net-consent-lanes")
        if s != last:
            seq.append([round(time.time() - t0, 2), s[:200]])
            last = s
        page.wait_for_timeout(250)
    R["lanes_sequence"] = seq
    R["lanes_final"] = page.inner_text("#net-consent-lanes")
    kt = page.locator("#net-consent-lanes span:has-text('Keyword translations')").first
    if kt.count():
        kt.hover(); page.wait_for_timeout(700)
        R["kt_hover"] = tip_text(page)
        R["kt_line"] = kt.evaluate("e => e.parentElement.innerText")
    shot(page, "M-M9-consent-en.png", selector="#net-consent")
    page.click("#net-consent-cancel")
    page.wait_for_timeout(800)
    R["online_after"] = page.evaluate("async () => (await fetch('/api/system/network')).json()")
    # compare: the top-bar plane
    page.click("#net-toggle")
    page.wait_for_selector("#net-consent[open]", timeout=10000)
    page.wait_for_timeout(3000)
    R["plane_consent_lanes"] = page.inner_text("#net-consent-lanes")[:1500]
    page.click("#net-consent-cancel")
    page.wait_for_timeout(800)
    R["online_after2"] = page.evaluate("async () => (await fetch('/api/system/network')).json()")
    b.close()

with open(log_path("walk_f.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_f_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:6000])
print(json.dumps(LOG, indent=1)[:2000])
