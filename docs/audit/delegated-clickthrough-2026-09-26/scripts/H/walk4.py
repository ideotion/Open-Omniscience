"""Row H, part 4: the hover's transport sentence in PROTECTED mode, set through the real Settings UI, then reverted."""
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/H")
from common import (OUT, Recorder, api, close_guide, consent_snapshot, dismiss_coach, dump,  # noqa: E402
                    launch, open_consent_via_plane, unlock_and_enter)

rep = {"notes": []}
rec = Recorder()


def open_safety(pg):
    pg.click("button[onclick=\"showTab('settings')\"]")
    pg.wait_for_selector("#set-subtabs button[data-tab='advanced']", state="visible", timeout=15000)
    pg.click("#set-subtabs button[data-tab='advanced']")
    pg.wait_for_selector("#set-advanced", state="visible", timeout=10000)
    if not pg.evaluate("() => document.querySelector(\"details[data-adv='safety']\").open"):
        pg.click("details[data-adv='safety'] > summary")
    pg.wait_for_selector("#fetch-mode", state="visible", timeout=10000)
    pg.wait_for_timeout(600)


with sync_playwright() as p:
    br, ctx = launch(p, 1440, 950)
    pg = ctx.new_page()
    rec.attach(pg)
    unlock_and_enter(pg, rec, rep["notes"])
    close_guide(pg, rep["notes"])
    pg.wait_for_timeout(800)
    dismiss_coach(pg, rep["notes"])
    open_safety(pg)
    rep["before"] = api(pg, "/api/safety/settings")
    pg.locator("#fetch-mode").scroll_into_view_if_needed()
    pg.select_option("#fetch-mode", "protected")
    pg.fill("#http-proxy", "http://127.0.0.1:9")
    pg.click("button[onclick='saveFetchMode()']")
    pg.wait_for_timeout(1200)
    rep["toasts_save"] = pg.eval_on_selector_all("#toast .note", "els => els.map(e => e.textContent)")
    st = api(pg, "/api/safety/settings")
    rep["protected_settings"] = {"fetch_mode": st.get("fetch_mode"), "transport": st.get("transport")}
    open_consent_via_plane(pg)
    snap = consent_snapshot(pg)
    rep["protected_transport_line"] = snap["transport"]
    rep["protected_hovers"] = {l["label"]: l["hover"] for g in snap["groups"] for l in g["lanes"]}
    pg.screenshot(path=f"{OUT}/H-H3-en-protected-popup.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(500)
    dismiss_coach(pg, rep["notes"])
    # revert through the same UI
    open_safety(pg)
    pg.select_option("#fetch-mode", "transparent")
    pg.fill("#http-proxy", "")
    pg.click("button[onclick='saveFetchMode()']")
    pg.wait_for_timeout(1200)
    st = api(pg, "/api/safety/settings")
    rep["reverted"] = {"fetch_mode": st.get("fetch_mode"), "transport": st.get("transport"), "http_proxy": st.get("http_proxy")}
    rep["network_end"] = api(pg, "/api/system/network")
    ctx.close()
    br.close()

rep["page_errors"], rep["console_errors"], rep["http_errors"], rep["junk"] = (
    rec.page_errors, rec.console_errors, rec.http_errors, rec.junk)
dump(rep, "part4.json")
print("done")
