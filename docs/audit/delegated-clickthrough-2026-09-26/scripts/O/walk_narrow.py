"""Row O walk, instance A: O10 at 375 px (en)."""
from playwright.sync_api import sync_playwright

import lib
from lib import (Rec, close_guide, clear_coach_if_blocking, living_sub, save, shot, storage_ready, txt)

BASE = "http://127.0.0.1:8834"
rec = Rec()
R = {}

OVERFLOW_JS = """(root) => {
  const r = document.querySelector(root); if (!r) return null;
  const W = document.documentElement.clientWidth; const out = [];
  for (const el of r.querySelectorAll('*')) {
    const b = el.getBoundingClientRect(); if (!b.width || !b.height) continue;
    if (b.right <= W + 1 && b.left >= -1) continue;
    // inside a box that scrolls on its own? then it is not a page overflow
    let p = el.parentElement, inScroller = false;
    while (p && p !== document.body) { const s = getComputedStyle(p);
      if (/(auto|scroll)/.test(s.overflowX) && p.scrollWidth > p.clientWidth) { inScroller = true; break; } p = p.parentElement; }
    if (!inScroller) out.push((el.tagName + '#' + el.id + '.' + el.className).slice(0, 60) + ' ' + Math.round(b.left) + '..' + Math.round(b.right));
  }
  return out.slice(0, 15);
}"""

CLIP_JS = """(root) => { const r = document.querySelector(root); if (!r) return null; const out = [];
  for (const el of r.querySelectorAll('*')) { const s = getComputedStyle(el);
    if (!el.children.length && el.innerText && el.innerText.trim() && (s.overflow === 'hidden' || s.textOverflow === 'ellipsis')
        && (el.scrollWidth > el.clientWidth + 1)) out.push(el.innerText.trim().slice(0, 50)); }
  return out.slice(0, 15); }"""


def page_x(pg):
    return pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking",
                                 "--disable-component-update", "--no-proxy-server"])
    ctx = br.new_context(viewport={"width": 375, "height": 800}, is_mobile=False, has_touch=False)
    pg = ctx.new_page()
    rec.watch(pg, "A-375")
    import traceback
    try:
        pg.goto(BASE + "/", wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(1500)
        close_guide(pg)
        R["lang"] = pg.evaluate("() => document.documentElement.lang")
        R["hamburger_visible"] = pg.is_visible("#hamburger")
        R["sidebar_item_rect_before_menu"] = pg.evaluate("() => { const r = document.querySelector(\".nav-item[data-tab='living']\").getBoundingClientRect(); return [r.left, r.right].map(Math.round); }")
        clear_coach_if_blocking(pg, "#hamburger", "375 menu")
        pg.click("#hamburger")
        pg.wait_for_timeout(700)
        R["sidebar_item_rect_after_menu"] = pg.evaluate("() => { const r = document.querySelector(\".nav-item[data-tab='living']\").getBoundingClientRect(); return [r.left, r.right].map(Math.round); }")
        shot(pg, "O-O10-menu-open-375-en.png")
        pg.click(".nav-item[data-tab='living']")
        pg.wait_for_timeout(600)
        # the sidebar overlay may stay open; close it with the Menu button if it covers the tab
        if pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger")
            pg.wait_for_timeout(500)
        pg.wait_for_function("() => /\\S/.test((document.getElementById('living-wiki-facts') || {}).innerText || '')", timeout=20000)
        pg.wait_for_timeout(1200)
        for kind in ("wiki", "law", "osm"):
            if kind != "wiki":
                living_sub(pg, kind)
            o = R[kind] = {}
            o["page_scroll_x"] = page_x(pg)
            o["fact_lefts"] = pg.evaluate(f"() => [...new Set([...document.querySelectorAll('#living-{kind} .living-fact')].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().left)))]")
            o["overflowing"] = pg.evaluate(OVERFLOW_JS, "#tab-living")
            o["clipped"] = pg.evaluate(CLIP_JS, "#tab-living")
            o["junk"] = lib.junk(pg, f"#living-{kind}")
            shot(pg, f"O-O10-living-{kind}-375-en.png", full=True)
        # Storage
        lib.settings_sub(pg, "data")
        if pg.evaluate("() => document.body.classList.contains('nav-open')"):
            pg.click("#hamburger")
            pg.wait_for_timeout(500)
        storage_ready(pg)
        o = R["storage"] = {}
        o["page_scroll_x"] = page_x(pg)
        o["table_box_scrolls"] = pg.evaluate("() => { const b = document.getElementById('storage-lanes'); return {scrollW: b.scrollWidth, clientW: b.clientWidth, overflowX: getComputedStyle(b).overflowX}; }")
        o["subtab_strip"] = pg.evaluate("() => { const n = document.getElementById('set-subtabs'); return {scrollW: n.scrollWidth, clientW: n.clientWidth, overflowX: getComputedStyle(n).overflowX}; }")
        o["overflowing"] = pg.evaluate(OVERFLOW_JS, "#set-data")
        o["clipped"] = pg.evaluate(CLIP_JS, "#storage-panel")
        pg.locator("#storage-panel").scroll_into_view_if_needed()
        shot(pg, "O-O10-storage-375-en.png", full=True)
        # Popup
        lib.open_consent(pg)
        o = R["popup"] = {}
        o["page_scroll_x"] = page_x(pg)
        o["body_scroll"] = pg.evaluate("() => { const b = document.getElementById('net-consent-body'); return {scrollH: b.scrollHeight, clientH: b.clientHeight, overflowY: getComputedStyle(b).overflowY}; }")
        o["dialog_rect"] = pg.evaluate("() => { const r = document.getElementById('net-consent').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(Math.round); }")
        shot(pg, "O-O10-popup-375-en.png")
        pg.hover("#net-consent-body")
        pg.mouse.wheel(0, 3000)
        pg.wait_for_timeout(600)
        o["after_scroll_list"] = pg.evaluate("() => document.getElementById('net-consent-body').scrollTop")
        o["buttons_in_view"] = pg.evaluate("""() => ['net-consent-cancel', 'net-consent-ok'].map(id => { const r = document.getElementById(id).getBoundingClientRect();
            return {id, top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right),
                    in_view: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth}; })""")
        o["window_scroll_y"] = pg.evaluate("() => window.scrollY")
        shot(pg, "O-O10-popup-scrolled-375-en.png")
        pg.click("#net-consent-cancel")
        pg.wait_for_timeout(800)
        o["closed"] = not pg.evaluate("() => document.getElementById('net-consent').open")
        o["network"] = lib.api(pg, "/api/system/network")["body"]
    except Exception:
        R["_exception"] = traceback.format_exc()[-3000:]
        print(R["_exception"])
        try:
            shot(pg, "_fail-narrow.png")
        except Exception:
            pass
    save("raw-narrow.json", {"R": R, "coach_blocks": lib.COACH_BLOCKS, "page_errors": rec.page_errors,
                             "console_errors": rec.console_errors, "http": rec.http})
    br.close()
print("done narrow")
