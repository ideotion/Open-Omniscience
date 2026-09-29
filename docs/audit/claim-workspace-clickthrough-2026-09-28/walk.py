"""S05-11 S1 click-through: the Claim Workspace, opened through the real omnibar (Ctrl-K, the
typed claim, ArrowDown to the "Check as a claim" row, Enter) and through the Search tab's
button, in en and ar, on a server started from seed.py's data folder; then a claim with no
related article, an edited query, a 375 px pass, and a language switch that must redraw the
trail without a fetch.

Nothing here goes online: the app boots in airplane mode and the workspace reads loopback only.
Every response of 400 or more, every page error and every console error is recorded.
"""
import json
import os
import re

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8745")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/walk/out")
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")
CLAIM = "Glacier melt in the Alps has doubled since 2000"
os.makedirs(OUT, exist_ok=True)


def close_wizard(pg):
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.wait_for_timeout(200)


def switch(pg, loc, errors):
    for attempt in (1, 2, 3):
        close_wizard(pg)
        pg.keyboard.press("Escape")
        pg.mouse.move(2, 2)
        pg.wait_for_timeout(500)
        try:
            pg.click("#lang-switch", timeout=6000)
            pg.wait_for_selector(f"#lang-menu [data-lang='{loc}']", state="visible", timeout=6000)
            pg.click(f"#lang-menu [data-lang='{loc}']", timeout=6000)
            pg.wait_for_function("(l) => document.documentElement.lang === l", arg=loc, timeout=6000)
            pg.wait_for_timeout(600)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                errors.append(f"switcher {loc}: {str(exc)[:160]}")
    close_wizard(pg)


def watch(pg, errors, bad, calls):
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.error: {m.text[:200]}") if m.type == "error" else None)
    pg.on("response", lambda r: bad.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
    pg.on("request", lambda r: calls.append(r.url) if "/api/claims/" in r.url else None)


def wait_trail(pg):
    pg.wait_for_function("() => document.querySelectorAll('#claim-body .claim-step').length === 6", timeout=20000)
    pg.wait_for_timeout(500)


def body_text(pg):
    return pg.evaluate("() => document.getElementById('tab-claim').innerText")


report = {}
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    pg = ctx.new_page()
    errors, bad, calls = [], [], []
    watch(pg, errors, bad, calls)
    pg.goto(BASE + "/", wait_until="networkidle")
    close_wizard(pg)

    # 1. The omnibar: Enter stays on Analysis (row 0); the claim row is row 1.
    pg.keyboard.press("Control+k")
    pg.wait_for_selector("#palette.open")
    pg.fill("#pal-input", CLAIM)
    pg.wait_for_timeout(700)
    rows = pg.evaluate("() => [...document.querySelectorAll('#pal-list .pal-item')].slice(0, 3).map(e => e.innerText.replace(/\\s+/g,' '))")
    sel0 = pg.evaluate("() => document.querySelector('#pal-list .pal-item.sel').innerText")
    report["omnibar_first_rows"] = rows
    report["omnibar_enter_row"] = sel0.replace("\n", " ")
    pg.keyboard.press("ArrowDown")
    pg.keyboard.press("Enter")
    wait_trail(pg)
    report["tab_active"] = pg.evaluate("() => document.getElementById('tab-claim').classList.contains('active')")
    txt = body_text(pg)
    report["en_text_excerpt"] = txt[:3000]
    report["en_junk"] = sorted(set(m.group(0) for m in JUNK.finditer(txt)))
    report["en_counts"] = pg.evaluate("""() => ({
      steps: document.querySelectorAll('#claim-body .claim-step').length,
      methods: document.querySelectorAll('#claim-body .claim-method').length,
      later: document.querySelectorAll('#claim-body .claim-later').length,
      related: document.querySelectorAll('#claim-body .claim-list li').length,
      paths: document.querySelectorAll('#claim-body .claim-path').length,
      timeline_rows: document.querySelectorAll('#claim-body .claim-timeline tbody tr').length,
      external_links: [...document.querySelectorAll('#claim-body a')].filter(a => !a.getAttribute('href').startsWith('/')).length,
    })""")
    pg.screenshot(path=f"{OUT}/workspace-en.png", full_page=True)

    # 2. A language switch redraws the trail from what it holds: no new fetch.
    before = len(calls)
    switch(pg, "ar", errors)
    pg.wait_for_timeout(800)
    report["ar_refetched"] = len(calls) - before
    ar = body_text(pg)
    report["ar_text_excerpt"] = ar[:1500]
    report["ar_junk"] = sorted(set(m.group(0) for m in JUNK.finditer(ar)))
    report["ar_dir"] = pg.evaluate("() => document.documentElement.dir")
    report["ar_english_left"] = [s for s in ["Related articles in your corpus", "Grouped by independence",
                                             "Who said what, when", "What's missing", "Not built yet.", "The claim states figures", "Paths joining several articles"] if s in ar]
    pg.screenshot(path=f"{OUT}/workspace-ar.png", full_page=True)

    # 3. The Search tab's button, in Arabic: the search box's text becomes the claim.
    pg.evaluate("() => showTab('search')")
    pg.fill("#q", "ذوبان الأنهار الجليدية في جبال الألب")
    pg.click("#claim-from-search")
    wait_trail(pg)
    report["search_button_claim"] = pg.input_value("#claim-text")
    report["search_button_related"] = pg.evaluate("() => document.querySelectorAll('#claim-body .claim-list li').length")
    pg.screenshot(path=f"{OUT}/search-button-ar.png", full_page=True)
    switch(pg, "en", errors)

    # 4. No related article: every step still drawn, ⑤ says what WOULD be needed.
    pg.fill("#claim-text", "Penguins migrate to the Sahara every winter")
    pg.fill("#claim-query", "")
    pg.click("#claim-run")
    pg.wait_for_function("() => /No article in your corpus matches/.test(document.getElementById('claim-body').innerText)", timeout=20000)
    report["empty_text"] = body_text(pg)[-1200:]
    pg.screenshot(path=f"{OUT}/empty-en.png", full_page=True)

    # 5. The reader's own words: a single-source trail, and a query the grammar rejects.
    pg.fill("#claim-text", CLAIM)
    pg.fill("#claim-query", '"Tokyo"')
    pg.press("#claim-query", "Enter")
    pg.wait_for_function("() => /as you typed them/.test(document.getElementById('claim-body').innerText)", timeout=20000)
    pg.wait_for_timeout(400)
    report["own_words_text"] = body_text(pg)[:1500]
    pg.fill("#claim-query", "(glacier OR")
    pg.click("#claim-run")
    pg.wait_for_function("() => /could not be walked/.test(document.getElementById('claim-status').innerText)", timeout=20000)
    report["bad_query_status"] = pg.inner_text("#claim-status")

    # 6. 375 px: no horizontal page scroll.
    pg.fill("#claim-query", "")
    pg.click("#claim-run")
    wait_trail(pg)
    pg.set_viewport_size({"width": 375, "height": 800})
    pg.wait_for_timeout(600)
    report["narrow_overflow_px"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    pg.screenshot(path=f"{OUT}/workspace-375-en.png", full_page=True)

    report["errors"] = errors
    report["bad_responses"] = [b for b in bad if "/api/claims/" not in b or "glacier+OR" not in b]
    report["claims_calls"] = len(calls)
    browser.close()

with open(f"{OUT}/report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in report.items() if "excerpt" not in k and k not in ("empty_text", "own_words_text")}, ensure_ascii=False, indent=1))
