"""Row H, part 1: unlock (encrypted, started LOCKED), H1 plane state, H2 popup read, H3 per-lane hover."""
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/H")
from common import (OUT, Recorder, api, close_guide, consent_snapshot, dismiss_coach, dump,  # noqa: E402
                    launch, open_consent_via_plane, pixel_diff, tip_state, unlock_and_enter)

VW, VH = 1440, 950
rep = {"notes": []}
rec = Recorder()
with sync_playwright() as p:
    br, ctx = launch(p, VW, VH)
    pg = ctx.new_page()
    rec.attach(pg)
    rep["lock_state_before"] = None
    unlock_and_enter(pg, rec, rep["notes"])
    rep["url_after_unlock"] = pg.url
    rep["lock_state_after"] = api(pg, "/api/system/lock-state")
    close_guide(pg, rep["notes"])
    pg.wait_for_timeout(1200)
    dismiss_coach(pg, rep["notes"])

    # ---- H1: the plane is filled, its hover says offline -------------------------------
    rep["H1"] = {
        "api_network": api(pg, "/api/system/network"),
        "plane_fill": pg.get_attribute("#net-plane", "fill"),
        "btn_off_class": pg.evaluate("() => document.getElementById('net-toggle').classList.contains('off')"),
        "btn_title": pg.evaluate("() => { const b = document.getElementById('net-toggle'); return b.getAttribute('title') || b.dataset.ooTip; }"),
    }
    # CONTROL for the hover measurement: the same #oo-tip over the normal page (no dialog).
    pg.mouse.move(2, 400)
    pg.wait_for_timeout(400)
    pg.screenshot(path=f"{OUT}/_ctl-off.png")
    pg.hover("#net-toggle")
    pg.wait_for_timeout(700)
    ts = tip_state(pg)
    pg.screenshot(path=f"{OUT}/H-H1-en.png")
    rep["H1"]["tip_on_plane"] = ts
    rep["H1"]["tip_on_plane_pixel_diff"] = pixel_diff(f"{OUT}/H-H1-en.png", f"{OUT}/_ctl-off.png", ts["rect"], VW, VH)
    pg.mouse.move(2, 400)
    pg.wait_for_timeout(400)
    dismiss_coach(pg, rep["notes"])

    # ---- H2: open the popup with a real click and read it -----------------------------
    rep["H2_config_reads"] = {
        "scheduler": {k: v for k, v in (api(pg, "/api/scheduler/config") or {}).items()
                      if k in ("world_discovery_per_pass", "wiki_lane_state", "country_data_per_pass",
                               "auto_refresh_stat_subscriptions", "auto_track_signals", "discovery_external_enabled")},
        "safety_transport": (api(pg, "/api/safety/settings") or {}).get("transport"),
        "safety_fetch_mode": (api(pg, "/api/safety/settings") or {}).get("fetch_mode"),
        "custody_mode": (api(pg, "/api/custody/settings") or {}).get("anchoring_mode"),
        "interfaces": api(pg, "/api/system/interfaces"),
    }
    open_consent_via_plane(pg)
    snap = consent_snapshot(pg)
    rep["H2"] = snap
    pg.screenshot(path=f"{OUT}/H-H2-en.png")
    # the caveats inside the scrolling body: are they on screen after scrolling it to its end?
    body_info = pg.evaluate("""() => { const b = document.getElementById('net-consent-body');
        return {scrollHeight: b.scrollHeight, clientHeight: b.clientHeight}; }""")
    rep["H2_body"] = body_info
    pg.evaluate("() => { const b = document.getElementById('net-consent-body'); b.scrollTop = b.scrollHeight; }")
    pg.wait_for_timeout(300)
    rep["H2_caveats_after_scroll"] = pg.evaluate("""() => {
        const vh = window.innerHeight; const body = document.getElementById('net-consent-body').getBoundingClientRect();
        return [...document.querySelectorAll('#net-consent-body > .hint')].map(h => { const r = h.getBoundingClientRect();
          return {text: h.textContent.replace(/\\s+/g,' ').trim().slice(0,90), top: r.top, bottom: r.bottom,
                  inBody: r.top >= body.top - 1 && r.bottom <= body.bottom + 1, inViewport: r.top >= 0 && r.bottom <= vh}; }); }""")
    pg.screenshot(path=f"{OUT}/H-H2-en-scrolled.png")
    rec.scan_junk(pg, "consent-en", "#net-consent")
    pg.evaluate("() => { const b = document.getElementById('net-consent-body'); b.scrollTop = 0; }")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(600)
    rep["H2_after_esc"] = {
        "dialog_open": pg.evaluate("() => document.getElementById('net-consent').open"),
        "plane_fill": pg.get_attribute("#net-plane", "fill"),
        "api_network": api(pg, "/api/system/network"),
        "coach_visible": pg.locator("#net-coach").is_visible(),
    }
    dismiss_coach(pg, rep["notes"])

    # ---- H3: rest the mouse on each lane name, measure whether the bubble is SEEN -----
    open_consent_via_plane(pg)
    order = ["Press collection", "Law", "Calendars", "Hazard feeds", "Wikipedia / Wikimedia",
             "Maps / OpenStreetMap", "Source discovery", "Local AI install & weights",
             "Newsletter mailbox", "Chain of custody", "Official statistics", "Markets & commodities",
             "Keyword translations", "Weather", "Discover by topic"]
    lanes_out = []
    dlg_rect = pg.evaluate("() => { const r = document.getElementById('net-consent').getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; }")
    for i, label in enumerate(order):
        span = pg.locator("#net-consent-lanes div > span:not(.muted)", has_text=label).first
        if not span.count():
            lanes_out.append({"label": label, "found": False})
            continue
        span.scroll_into_view_if_needed()
        # OFF frame: mouse on the dialog title (no hover target), bubble hidden.
        pg.mouse.move(dlg_rect["x"] + 30, dlg_rect["y"] + 25)
        pg.wait_for_timeout(350)
        off = f"{OUT}/_h3-off-{i}.png"
        pg.screenshot(path=off)
        span.hover()
        pg.wait_for_timeout(700)
        ts = tip_state(pg)
        on = f"{OUT}/_h3-on-{i}.png"
        pg.screenshot(path=on)
        r = ts["rect"]
        # split the bubble's box into its part inside the dialog and the part outside
        ix0, iy0 = max(r["x"], dlg_rect["x"]), max(r["y"], dlg_rect["y"])
        ix1 = min(r["x"] + r["w"], dlg_rect["x"] + dlg_rect["w"])
        iy1 = min(r["y"] + r["h"], dlg_rect["y"] + dlg_rect["h"])
        inside = {"x": ix0, "y": iy0, "w": max(0, ix1 - ix0), "h": max(0, iy1 - iy0)}
        right = {"x": dlg_rect["x"] + dlg_rect["w"], "y": r["y"], "w": max(0, r["x"] + r["w"] - (dlg_rect["x"] + dlg_rect["w"])), "h": r["h"]}
        lanes_out.append({
            "label": label, "found": True,
            "hover_text_dom": ts["text"], "tip_class_show": ts["shown"], "tip_opacity": ts["opacity"],
            "tip_parent": ts["parent"], "tip_in_dialog": ts["inDialog"], "tip_rect": r,
            "diff_whole_tip": pixel_diff(on, off, r, VW, VH),
            "diff_tip_inside_dialog": pixel_diff(on, off, inside, VW, VH) if inside["w"] and inside["h"] else None,
            "diff_tip_right_of_dialog": pixel_diff(on, off, right, VW, VH) if right["w"] > 2 else None,
        })
        if label == "Press collection":
            pg.screenshot(path=f"{OUT}/H-H3-en-press-hover.png")
        if label == "Law":
            pg.screenshot(path=f"{OUT}/H-H3-en-law-hover.png")
    rep["H3_dialog_rect"] = dlg_rect
    rep["H3"] = lanes_out
    # keyboard: can a lane name take focus at all (invariant #17 promises keyboard focus)?
    rep["H3_lane_focusable"] = pg.evaluate("""() => [...document.querySelectorAll('#net-consent-lanes div > span:not(.muted)')]
        .map(s => ({label: s.textContent.trim(), tabIndex: s.tabIndex}))""")
    # tab through the dialog and record which elements receive focus
    focus_seq = []
    for _ in range(6):
        pg.keyboard.press("Tab")
        pg.wait_for_timeout(120)
        focus_seq.append(pg.evaluate("() => { const a = document.activeElement; return a ? (a.id || a.tagName) + ':' + (a.textContent||'').trim().slice(0,30) : null; }"))
    rep["H3_tab_sequence"] = focus_seq
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(500)
    rep["H3_after_cancel"] = {"plane_fill": pg.get_attribute("#net-plane", "fill"),
                              "api_network": api(pg, "/api/system/network")}
    dismiss_coach(pg, rep["notes"])
    ctx.close()
    br.close()

rep["page_errors"], rep["console_errors"], rep["http_errors"], rep["junk"] = (
    rec.page_errors, rec.console_errors, rec.http_errors, rec.junk)
dump(rep, "part1.json")
print("done")
