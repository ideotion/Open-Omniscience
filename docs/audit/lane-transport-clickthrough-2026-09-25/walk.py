"""S04-08 S5 click-through: the consent popup's transport lines, the task manager's paused
and failed downloads, and the Wikipedia toggle WAITING behind a dead proxy.

Driven through the real top-bar controls on a server started from `seed.py`'s data folder
(protected mode through socks5h://127.0.0.1:9, where nothing listens), languages switched
through the real switcher. Order matters: everything offline first, then ONE crossing
online through the consent popup's own button, then back to airplane mode.
"""
import json
import os

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8745")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/s5walk")
LANGS = ("en", "fr", "ar")


def close_wizard(pg):
    # A fresh install opens the first-run guide over everything; it is not under test.
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.wait_for_timeout(200)


def switch(pg, loc, errors):
    """The real top-bar switcher. Three tries, because a dialog closing a moment earlier can
    still be animating over the menu, and a hover bubble left open can sit on the button;
    the attempt only counts when the page's own lang attribute says it took. A third
    failure is recorded, and the report's language field says which language each
    capture was really taken in."""
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


def current_lang(pg):
    return pg.evaluate("() => document.documentElement.lang || ''")


def api(pg, path, method="GET", body=None):
    return pg.evaluate(
        """([p, m, b]) => fetch(p, {method: m, headers: {'Content-Type': 'application/json'},
              body: b === null ? undefined : JSON.stringify(b)}).then(r => r.json())""",
        [path, method, body],
    )


def open_consent(pg):
    """The plane button, offline -> the ONE consent popup, lanes rendered."""
    pg.click("#net-toggle")
    pg.wait_for_function(
        "() => document.getElementById('net-consent').open && "
        "document.querySelectorAll('#net-consent-lanes span[title], #net-consent-lanes span[data-oo-tip]').length > 3",
        timeout=15000,
    )
    pg.wait_for_timeout(400)


def lanes(pg):
    return pg.evaluate("""() => {
        const box = document.getElementById('net-consent-lanes');
        const rows = [...box.querySelectorAll('span')].filter(s => s.getAttribute('title') || s.dataset.ooTip)
            .map(s => ({label: s.textContent.trim(), hover: s.getAttribute('title') || s.dataset.ooTip}));
        const hint = box.querySelector('.hint');
        return {rows, hint: hint ? hint.textContent.trim() : null};
    }""")


def hover_shot(pg, selector, path):
    pg.hover(selector)
    pg.wait_for_timeout(700)
    tip = pg.evaluate("() => { const t = document.getElementById('oo-tip'); return t && !t.hidden ? t.textContent.trim() : null; }")
    pg.screenshot(path=path)
    pg.mouse.move(2, 2)
    pg.wait_for_timeout(300)
    return tip


report = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.error: {m.text[:200]}") if m.type == "error" else None)
    pg.goto(BASE, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    close_wizard(pg)
    report["boot_network"] = api(pg, "/api/system/network")
    report["safety_transport"] = api(pg, "/api/safety/settings").get("transport")

    # 1. Two downloads started while offline: the owners pause them, by airplane mode.
    report["start_offline_osm"] = api(pg, "/api/geo/downloads/start", "POST", {"code": "europe"})
    report["start_offline_dump"] = api(pg, "/api/wiki/dumps/start", "POST",
                                       {"wiki": "fr", "kind": "pages-articles-multistream"})

    # 2. The consent popup in protected mode (one proxy), per language, then cancelled.
    for loc in LANGS:
        switch(pg, loc, errors)
        open_consent(pg)
        report[f"consent-protected-{loc}"] = lanes(pg)
        report[f"consent-protected-{loc}"]["lang"] = current_lang(pg)
        report[f"consent-protected-{loc}"]["tip_press"] = hover_shot(
            pg, "#net-consent-lanes div:nth-of-type(2) span", f"{OUT}/consent-protected-{loc}.png")
        pg.click("#net-consent-cancel")
        pg.wait_for_timeout(400)

    # 3. The same popup in transparent mode with the proxy still stored: it must say direct.
    switch(pg, "en", errors)
    api(pg, "/api/safety/settings", "PUT", {"fetch_mode": "transparent"})
    open_consent(pg)
    report["consent-transparent-en"] = lanes(pg)
    pg.screenshot(path=f"{OUT}/consent-transparent-en.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(400)
    api(pg, "/api/safety/settings", "PUT", {"fetch_mode": "protected"})
    report["safety_transport_restored"] = api(pg, "/api/safety/settings").get("transport")

    # 4. ONE crossing online, through the popup's own button. Protected mode sends every
    #    fetch to the dead proxy, so the stream's connections fail and it must WAIT.
    open_consent(pg)
    pg.click("#net-consent-ok")
    pg.wait_for_timeout(2000)
    report["online_network"] = api(pg, "/api/system/network")
    # Resume the dump that airplane mode paused: its first request goes to the dead proxy.
    report["resume_dump"] = api(pg, "/api/jobs/dump:fr:pages-articles-multistream/resume", "POST")
    pg.wait_for_timeout(12000)
    status = api(pg, "/api/scheduler/status")
    wl = status.get("wiki_lane") or {}
    report["wiki_lane_block"] = {k: wl.get(k) for k in ("state", "active", "reason", "waiting_on")}
    report["jobs"] = [{k: j.get(k) for k in ("id", "state", "paused_by", "error")}
                      for j in api(pg, "/api/jobs").get("jobs", [])
                      if j.get("kind") in ("wiki-dump", "osm-map")]

    for loc in LANGS:
        switch(pg, loc, errors)
        pg.evaluate("() => loadWikiLane()")
        pg.wait_for_timeout(800)
        report[f"wiki-toggle-{loc}"] = {
            "title": pg.evaluate("() => { const b = document.getElementById('wiki-toggle'); return b.getAttribute('title') || b.dataset.ooTip; }"),
            "live_class": pg.evaluate("() => document.getElementById('wiki-toggle').classList.contains('wiki-live')"),
            "tip": hover_shot(pg, "#wiki-toggle", f"{OUT}/wiki-waiting-{loc}.png"),
        }
        # The top-bar button opens the task manager as its OWN page (/tasks), which reads
        # the language the app stored; each capture closes it so the next click opens anew.
        with ctx.expect_page() as opened:
            pg.click("#tm-open")
        tm = opened.value
        tm.wait_for_load_state("networkidle")
        tm.wait_for_function("() => document.getElementById('jobs-body').innerText.trim().length > 0",
                             timeout=15000)
        tm.wait_for_timeout(800)
        report[f"task-manager-{loc}"] = {
            "url": tm.url,
            "lang": tm.evaluate("() => (window.OOI18N && OOI18N.current && OOI18N.current()) || ''"),
            "text": tm.evaluate("() => document.getElementById('jobs-body').innerText"),
        }
        tm.screenshot(path=f"{OUT}/task-manager-{loc}.png", full_page=True)
        tm.close()
        pg.bring_to_front()
        pg.wait_for_timeout(300)

    # 5. Back to airplane mode through the same button: the stream must stop.
    switch(pg, "en", errors)
    pg.click("#net-toggle")
    pg.wait_for_timeout(3000)
    report["offline_network"] = api(pg, "/api/system/network")
    wl = (api(pg, "/api/scheduler/status").get("wiki_lane") or {})
    report["wiki_lane_after_offline"] = {k: wl.get(k) for k in ("state", "active", "reason", "waiting_on")}
    report["errors"] = errors
    ctx.close()
    br.close()

with open(f"{OUT}/report.json", "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1)[:9000])
