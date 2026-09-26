"""Row H, part 3: H7 fr / ar / zh through the real language switcher; H4 doc language in fr; H8 at 375x667."""
import json
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, "/tmp/claude-0/walk/H")
from common import (OUT, Recorder, api, close_guide, consent_snapshot, dismiss_coach, dump,  # noqa: E402
                    launch, open_consent_via_plane, pixel_diff, switch_lang, tip_state, unlock_and_enter)

VW, VH = 1440, 950
rep = {"notes": []}
rec = Recorder()
p1 = json.load(open(f"{OUT}/part1.json"))
EN = p1["H2"]
# English sentences that must NOT survive on a translated popup (host names excluded)
en_strings = [EN["title"], EN["needs"], EN["reason"], EN["transport"], EN["cancel"], EN["ok"],
              "Where this will let the app connect:", "Your machine presents these local network addresses:",
              "Runs on every collection pass:", "Only when you ask for it:", "Switched off right now:"]
en_strings += [c["text"] for c in EN["caveats"]]
en_labels = [l["label"] for g in EN["groups"] for l in g["lanes"]]
en_hover_phrases = ["the full list is in the security notes", "Transport: direct", "Always on:",
                    "Its off-switch exists", "Not through this app's fetcher", "a host you name yourself", " hosts "]
LEAVE = {"fr": "Rester hors ligne", "ar": "البقاء دون اتصال", "zh": "保持离线"}

with sync_playwright() as p:
    br, ctx = launch(p, VW, VH)
    pg = ctx.new_page()
    rec.attach(pg)
    unlock_and_enter(pg, rec, rep["notes"])
    close_guide(pg, rep["notes"])
    pg.wait_for_timeout(800)
    dismiss_coach(pg, rep["notes"])

    for loc in ("fr", "ar", "zh"):
        ok = switch_lang(pg, loc, rep["notes"])
        dismiss_coach(pg, rep["notes"])
        r = {"switched": ok, "html_lang": pg.evaluate("() => document.documentElement.lang"),
             "html_dir": pg.evaluate("() => document.documentElement.dir")}
        open_consent_via_plane(pg)
        snap = consent_snapshot(pg)
        r["snap"] = {k: snap[k] for k in ("title", "needs", "reason", "transport", "ifaces", "cancel", "ok", "dir", "rect")}
        r["groups"] = [{"heading": g["heading"], "lanes": [(l["label"], l["n"]) for l in g["lanes"]]} for g in snap["groups"]]
        r["hovers"] = {l["label"]: l["hover"] for g in snap["groups"] for l in g["lanes"]}
        r["caveats"] = [c["text"] for c in snap["caveats"]]
        text_all = snap["innerText"] + "\n" + "\n".join(r["hovers"].values())
        r["english_left"] = [s for s in en_strings if s and s in snap["innerText"]]
        r["english_labels_left"] = [s for s in en_labels if s in [l[0] for g in r["groups"] for l in g["lanes"]]]
        r["english_hover_phrases_left"] = [s for s in en_hover_phrases if s in "\n".join(r["hovers"].values())]
        # alignment of a lane line and the title in the dialog (RTL mirroring)
        r["align"] = pg.evaluate("""() => { const d = document.getElementById('net-consent').getBoundingClientRect();
            const h = document.querySelector('#net-consent h3').getBoundingClientRect();
            const s = document.querySelector('#net-consent-lanes div > span').getBoundingClientRect();
            const ok = document.getElementById('net-consent-ok').getBoundingClientRect();
            const ca = document.getElementById('net-consent-cancel').getBoundingClientRect();
            return {dlg_left: d.left, dlg_right: d.right, title_left: h.left, title_right: h.right,
                    lane_left: s.left, lane_right: s.right, ok_left: ok.left, cancel_left: ca.left}; }""")
        pg.screenshot(path=f"{OUT}/H-H7-{loc}.png")
        # hover Law, Hazard feeds, Wikipedia: is a bubble SEEN (pixels), and where does it sit?
        dlg = snap["rect"]
        hv = []
        for idx_label in ("Law", "Hazard feeds", "Wikipedia / Wikimedia"):
            # find the translated label via the English order: same index in the flattened list
            i = en_labels.index(idx_label)
            flat = [l[0] for g in r["groups"] for l in g["lanes"]]
            tr = flat[i] if i < len(flat) else None
            span = pg.locator("#net-consent-lanes div > span:not(.muted)").nth(i)
            span.scroll_into_view_if_needed()
            pg.mouse.move(dlg["x"] + dlg["w"] / 2, dlg["y"] + 20)
            pg.wait_for_timeout(350)
            off = f"{OUT}/_h7-off.png"
            pg.screenshot(path=off)
            span.hover()
            pg.wait_for_timeout(800)
            ts = tip_state(pg)
            on = f"{OUT}/_h7-on-{loc}-{i}.png"
            pg.screenshot(path=on)
            t = ts["rect"]
            right_part = {"x": dlg["x"] + dlg["w"], "y": t["y"], "w": max(0, t["x"] + t["w"] - (dlg["x"] + dlg["w"])), "h": t["h"]}
            inside = {"x": max(t["x"], dlg["x"]), "y": t["y"], "w": max(0, min(t["x"] + t["w"], dlg["x"] + dlg["w"]) - max(t["x"], dlg["x"])), "h": t["h"]}
            hv.append({"en": idx_label, "label": tr, "span_text": span.inner_text(), "tip_text": ts["text"],
                       "shown": ts["shown"], "rect": t,
                       "diff_inside_dialog": pixel_diff(on, off, inside, VW, VH) if inside["w"] > 2 else None,
                       "diff_outside_right": pixel_diff(on, off, right_part, VW, VH) if right_part["w"] > 2 else None})
            if idx_label == "Wikipedia / Wikimedia":
                pg.screenshot(path=f"{OUT}/H-H7-{loc}-wiki-hover.png")
        r["hover_checks"] = hv
        rec.scan_junk(pg, f"consent-{loc}", "#net-consent")
        pg.mouse.move(dlg["x"] + dlg["w"] / 2, dlg["y"] + 20)
        pg.get_by_role("button", name=LEAVE[loc], exact=True).click()
        pg.wait_for_timeout(500)
        r["after_leave"] = {"open": pg.evaluate("() => document.getElementById('net-consent').open"),
                            "plane_fill": pg.get_attribute("#net-plane", "fill"),
                            "online": api(pg, "/api/system/network")}
        dismiss_coach(pg, rep["notes"])
        rep[f"H7_{loc}"] = r

    # H4 in French: the Security notes stay English
    pg.click("button.icon-btn[onclick=\"showTab('help')\"]")
    pg.wait_for_selector("#doc-nav .doc-link", timeout=15000)
    pg.locator("#doc-nav .doc-link").nth(4).click()
    pg.wait_for_function("() => document.querySelector('#doc-prose').innerText.includes('Where in the tree')", timeout=15000)
    rep["H4_zh_doc"] = {"lang": pg.evaluate("() => document.documentElement.lang"),
                        "nav_labels": pg.eval_on_selector_all("#doc-nav .doc-link", "els => els.map(e => e.childNodes[0].textContent.trim())"),
                        "banner": pg.evaluate("() => { const h = document.querySelector('#doc-prose > .hint'); return h ? h.innerText : null; }"),
                        "has_table_heading_en": pg.evaluate("() => document.querySelector('#doc-prose').innerText.includes('Hosts it can reach')")}
    switch_lang(pg, "en", rep["notes"])
    rep["back_to_en"] = pg.evaluate("() => document.documentElement.lang")
    ctx.close()

    # ---- H8: 375 x 667 -------------------------------------------------------------------
    ctx = br.new_context(viewport={"width": 375, "height": 667})
    pg = ctx.new_page()
    rec.attach(pg)
    unlock_and_enter(pg, rec, rep["notes"])
    close_guide(pg, rep["notes"])
    pg.wait_for_timeout(800)
    dismiss_coach(pg, rep["notes"])
    h8 = {"lang": pg.evaluate("() => document.documentElement.lang"),
          "page_hscroll_closed": pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"),
          "plane_rect": pg.evaluate("() => { const r = document.getElementById('net-toggle').getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; }")}
    open_consent_via_plane(pg)
    h8["dialog"] = pg.evaluate("""() => { const d = document.getElementById('net-consent'); const r = d.getBoundingClientRect();
        const b = document.getElementById('net-consent-body');
        const ok = document.getElementById('net-consent-ok').getBoundingClientRect();
        const ca = document.getElementById('net-consent-cancel').getBoundingClientRect();
        return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, vw: innerWidth, vh: innerHeight,
                dlg_hscroll: d.scrollWidth - d.clientWidth, body_scrollH: b.scrollHeight, body_clientH: b.clientHeight,
                ok: {l: ok.left, r: ok.right, t: ok.top, b: ok.bottom}, cancel: {l: ca.left, r: ca.right, t: ca.top, b: ca.bottom}}; }""")
    h8["page_hscroll_open"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    h8["clipped_lane_text"] = pg.evaluate("""() => [...document.querySelectorAll('#net-consent-lanes div, #net-consent-body > .hint, #net-consent h3')]
        .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent.trim().slice(0, 50))""")
    pg.screenshot(path=f"{OUT}/H-H8-en-375.png")
    # scroll ONLY the middle part to its end, with the mouse wheel over it
    b = pg.locator("#net-consent-body").bounding_box()
    pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    for _ in range(8):
        pg.mouse.wheel(0, 400)
        pg.wait_for_timeout(120)
    pg.wait_for_timeout(400)
    h8["after_wheel"] = pg.evaluate("""() => { const b = document.getElementById('net-consent-body');
        const vh = innerHeight; return {scrollTop: b.scrollTop, max: b.scrollHeight - b.clientHeight,
        page_scrollY: scrollY,
        caveats: [...document.querySelectorAll('#net-consent-body > .hint')].map(h => { const r = h.getBoundingClientRect();
          const br = b.getBoundingClientRect();
          return {top: r.top, bottom: r.bottom, visible: r.top >= br.top - 1 && r.bottom <= br.bottom + 1 && r.bottom <= vh}; })}; }""")
    pg.screenshot(path=f"{OUT}/H-H8-en-375-scrolled.png")
    rec.scan_junk(pg, "consent-375", "#net-consent")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(500)
    h8["after_cancel"] = {"open": pg.evaluate("() => document.getElementById('net-consent').open"),
                          "plane_fill": pg.get_attribute("#net-plane", "fill")}
    rep["H8"] = h8
    ctx.close()
    br.close()

rep["page_errors"], rep["console_errors"], rep["http_errors"], rep["junk"] = (
    rec.page_errors, rec.console_errors, rec.http_errors, rec.junk)
dump(rep, "part3.json")
print("done")
