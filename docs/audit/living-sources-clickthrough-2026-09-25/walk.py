"""S04-08 S6 click-through: the Living sources tab, driven through the real sidebar, subtabs,
diff buttons and tracked-page buttons, in en / fr / ar, on a server started from
`seed.py`'s data folder; then the reader's deep link, a 375 px pass, and a FRESH folder
where nothing has run (a second server started on an empty data folder).

Nothing here goes online: the app boots in airplane mode and the view reads loopback only.
Every response of 400 or more, every page error and every console error is recorded.
"""
import json
import os
import re

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8745")
FRESH = os.environ.get("OO_WALK_FRESH", "http://127.0.0.1:8746")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/s6walk")
LANGS = ("en", "fr", "ar")
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")


def close_wizard(pg):
    # A fresh install opens the first-run guide over everything; it is not under test.
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.wait_for_timeout(200)


def switch(pg, loc, errors):
    """The real top-bar switcher, three tries; the attempt counts only when the page's own
    lang attribute says it took (the S5 walk's harness, unchanged)."""
    for attempt in (1, 2, 3):
        close_wizard(pg)
        pg.keyboard.press("Escape")
        pg.mouse.move(2, 2)
        pg.wait_for_timeout(600)
        try:
            pg.click("#lang-switch", timeout=6000)
            pg.wait_for_selector(f"#lang-menu [data-lang='{loc}']", state="visible", timeout=6000)
            pg.click(f"#lang-menu [data-lang='{loc}']", timeout=6000)
            pg.wait_for_function("(l) => document.documentElement.lang === l", arg=loc, timeout=6000)
            pg.wait_for_timeout(600)
            break
        except Exception as exc:  # noqa: BLE001 - recorded, not hidden
            if attempt == 3:
                errors.append(f"switcher {loc}: {str(exc)[:160]}")
    close_wizard(pg)


def text_of(pg, sel):
    return pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : null; }", sel)


def subtab(pg, kind):
    pg.click(f"#living-subtabs button[data-tab='{kind}']")
    pg.wait_for_function("(k) => { const e = document.getElementById('living-' + k); "
                         "return e && e.style.display !== 'none'; }", arg=kind, timeout=8000)
    pg.wait_for_timeout(900)


def open_tab(pg):
    pg.click(".nav-item[data-tab='living']")
    pg.wait_for_function("() => (document.getElementById('living-wiki-facts') || {}).innerText", timeout=15000)
    pg.wait_for_function("() => document.querySelectorAll('#living-stream .living-row').length > 0 "
                         "|| /\\S/.test((document.getElementById('living-stream') || {}).innerText || '')",
                         timeout=15000)
    pg.wait_for_timeout(900)


def watch(pg, errors, bad):
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.error: {m.text[:200]}") if m.type == "error" else None)
    pg.on("response", lambda r: bad.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)


def junk_in(pg):
    body = pg.evaluate("() => document.getElementById('tab-living').innerText")
    return sorted(set(m.group(0) for m in JUNK.finditer(body)))


report = {"seeded": {}, "fresh": {}}
os.makedirs(OUT, exist_ok=True)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage"])

    # 1. The seeded folder, per language, through the real controls.
    ctx = br.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    errors, bad = [], []
    watch(pg, errors, bad)
    pg.goto(BASE, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    close_wizard(pg)
    report["network_at_boot"] = pg.evaluate("() => fetch('/api/system/network').then(r => r.json())")
    first = True
    for loc in LANGS:
        switch(pg, loc, errors)
        if first:
            open_tab(pg)
            first = False
        else:
            subtab(pg, "wiki")
        r = report["seeded"][loc] = {"lang": pg.evaluate("() => document.documentElement.lang")}
        r["status"] = text_of(pg, "#living-status")
        r["caveat"] = text_of(pg, "#living-caveat")
        r["wiki_facts"] = text_of(pg, "#living-wiki-facts")
        r["stream_cap"] = text_of(pg, "#living-stream-cap")
        r["stream"] = text_of(pg, "#living-stream")
        r["subtab_active"] = pg.evaluate(
            "() => [...document.querySelectorAll('#living-subtabs button')].map(b => "
            "[b.dataset.tab, b.getAttribute('aria-selected')])")
        pg.screenshot(path=f"{OUT}/wiki-{loc}.png", full_page=True)
        # The stored diff, through its own button.
        pg.click("#living-stream button.tiny")
        pg.wait_for_selector("#living-stream .living-diff", timeout=8000)
        pg.wait_for_timeout(500)
        r["diff"] = text_of(pg, "#living-stream .living-diff")
        r["diff_note"] = pg.evaluate("() => [...document.querySelectorAll('#living-stream .living-diff ~ .muted')]"
                                     ".map(e => e.innerText)")
        pg.locator("#living-stream .living-diff").first.scroll_into_view_if_needed()
        pg.screenshot(path=f"{OUT}/wiki-diff-{loc}.png")
        pg.click("#living-stream button.tiny")  # hide it again
        # A tracked page's history, through its button.
        pg.click("#living-pages button.living-page")
        pg.wait_for_function("() => /\\S/.test(document.getElementById('wiki-tc-body').innerText) && "
                             "!/Pick a page|Loading/.test(document.getElementById('wiki-tc-body').innerText)",
                             timeout=10000)
        pg.wait_for_timeout(600)
        r["tracked_title"] = text_of(pg, "#wiki-tc-title")
        r["tracked_body"] = text_of(pg, "#wiki-tc-body")
        r["tracked_method"] = text_of(pg, "#wiki-tc-method")
        pg.locator("#wiki-tc").scroll_into_view_if_needed()
        pg.screenshot(path=f"{OUT}/tracked-{loc}.png")
        subtab(pg, "law")
        r["law_facts"] = text_of(pg, "#living-law-facts")
        r["law_changes"] = text_of(pg, "#living-law-changes")
        r["law_links"] = pg.evaluate("() => [...document.querySelectorAll('#living-law-changes a')]"
                                     ".map(a => a.getAttribute('href'))")
        pg.screenshot(path=f"{OUT}/law-{loc}.png", full_page=True)
        subtab(pg, "osm")
        r["maps_facts"] = text_of(pg, "#living-osm-facts")
        r["maps_regions"] = text_of(pg, "#living-osm-regions")
        pg.screenshot(path=f"{OUT}/maps-{loc}.png", full_page=True)
        r["junk_words"] = junk_in(pg)
        # A hover, through the one shared bubble.
        pg.hover("#living-osm-facts .living-fact[title]")
        pg.wait_for_timeout(700)
        r["tip_maps_date"] = pg.evaluate("() => { const t = document.getElementById('oo-tip'); "
                                         "return t && !t.hidden ? t.textContent.trim() : null; }")
        pg.mouse.move(2, 2)
    # 2. The reader's deep link lands in the tab on the page it names.
    switch(pg, "en", errors)
    page_id = pg.evaluate("() => fetch('/api/wiki/pages').then(r => r.json()).then(d => d.pages[0].id)")
    pg.goto(f"{BASE}/?wikitc={page_id}", wait_until="networkidle", timeout=60000)
    pg.wait_for_function("() => !/Pick a page|Loading/.test((document.getElementById('wiki-tc-body') || {}).innerText || 'Pick a page')",
                         timeout=15000)
    pg.wait_for_timeout(800)
    report["deep_link"] = {
        "active_tab": pg.evaluate("() => (document.querySelector('.nav-item.active') || {}).dataset?.tab || null"),
        "title": text_of(pg, "#wiki-tc-title"),
        "body_head": (text_of(pg, "#wiki-tc-body") or "")[:200],
        "dialog_left": pg.evaluate("() => !!document.querySelector('dialog#wiki-tc')"),
    }
    pg.screenshot(path=f"{OUT}/deep-link-en.png")
    report["seeded_errors"], report["seeded_bad_responses"] = errors, bad
    ctx.close()

    # 3. 375 px: the tab must stay readable without a horizontal page scroll.
    ctx = br.new_context(viewport={"width": 375, "height": 800})
    pg = ctx.new_page()
    errors, bad = [], []
    watch(pg, errors, bad)
    pg.goto(BASE, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1200)
    close_wizard(pg)
    pg.evaluate("() => showTab('living')")
    pg.wait_for_function("() => (document.getElementById('living-wiki-facts') || {}).innerText", timeout=15000)
    pg.wait_for_timeout(900)
    report["narrow"] = {
        "page_scroll_x": pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"),
        "errors": errors, "bad": bad,
    }
    pg.screenshot(path=f"{OUT}/wiki-375-en.png", full_page=True)
    ctx.close()

    # 4. A FRESH folder: nothing has run, so nothing may read as a zero.
    ctx = br.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    errors, bad = [], []
    watch(pg, errors, bad)
    pg.goto(FRESH, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    close_wizard(pg)
    open_tab(pg)
    f = report["fresh"]
    f["wiki_facts"] = text_of(pg, "#living-wiki-facts")
    f["stream"] = text_of(pg, "#living-stream")
    f["pages"] = text_of(pg, "#living-pages")
    pg.screenshot(path=f"{OUT}/fresh-wiki-en.png", full_page=True)
    subtab(pg, "law")
    f["law_facts"] = text_of(pg, "#living-law-facts")
    f["law_changes"] = text_of(pg, "#living-law-changes")
    subtab(pg, "osm")
    f["maps_facts"] = text_of(pg, "#living-osm-facts")
    f["maps_regions"] = text_of(pg, "#living-osm-regions")
    pg.screenshot(path=f"{OUT}/fresh-maps-en.png", full_page=True)
    f["lane_file_after_reads"] = pg.evaluate("() => fetch('/api/storage/lanes').then(r => r.json())"
                                             ".then(d => (d.lanes || []).filter(l => l.kind === 'wiki')"
                                             ".map(l => l.size_state))")
    f["junk_words"] = junk_in(pg)
    f["errors"], f["bad_responses"] = errors, bad
    ctx.close()
    br.close()

with open(f"{OUT}/report.json", "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1)[:12000])
