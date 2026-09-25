"""S04-08 S3 click-through: the scheduler panel after the mode's retirement, driven through
the real language switcher, on an install seeded as if it had been in the retired Markets mode."""
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8743"
OUT = "/tmp/claude-0/walk"

def close_wizard(pg):
    # The seeded install is fresh, so the first-run guide opens over everything; it is not
    # the surface under test. Closed the way its own Skip would, not hidden with CSS.
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.wait_for_timeout(200)

def open_panel(pg):
    close_wizard(pg)
    pg.evaluate("() => showTab('settings')")
    pg.wait_for_timeout(250)
    pg.evaluate("""() => {
        showSetCat('advanced');
        const d = document.querySelector('#set-advanced details.adv-sec[data-adv="collect"]');
        if (d && !d.open) { d.open = true; d.dispatchEvent(new Event('toggle')); }
        document.querySelectorAll('#set-advanced details.adv-collect').forEach(x => x.open = true);
    }""")
    pg.wait_for_timeout(1500)

def state(pg):
    return pg.evaluate("""() => ({
        lang: (window.OOI18N && OOI18N.current && OOI18N.current()) || '?',
        dir: document.documentElement.dir || getComputedStyle(document.body).direction,
        retiredVisible: !document.getElementById('sch-retired').hidden,
        retiredText: document.getElementById('sch-retired-text').textContent.slice(0, 160),
        rulesLabel: document.getElementById('sch-market-rules').parentElement.textContent.trim(),
        rules: document.getElementById('sch-market-rules').checked,
        stats: document.getElementById('sch-stat-refresh').checked,
        crawlFieldsDisplay: getComputedStyle(document.getElementById('crawl-fields')).display,
        modeSelectExists: !!document.getElementById('sch-mode'),
        hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    })""")

report = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage"])
    for width in (1440, 375):
        ctx = br.new_context(viewport={"width": width, "height": 900})
        pg = ctx.new_page(); errors = []
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.on("console", lambda m: errors.append(f"console.error: {m.text[:160]}") if m.type == "error" else None)
        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(1500)
        close_wizard(pg)
        for loc in (["en", "fr", "ar"] if width == 1440 else ["en"]):
            close_wizard(pg)
            try:
                pg.click("#lang-switch", timeout=8000); pg.wait_for_timeout(250)
                pg.click(f"#lang-menu [data-lang='{loc}']", timeout=8000); pg.wait_for_timeout(1200)
            except Exception as exc:
                errors.append(f"switcher: {exc}")
            open_panel(pg)
            st = state(pg)
            report[f"{loc}@{width}"] = st
            pg.locator("#sch-retired").scroll_into_view_if_needed()
            pg.screenshot(path=f"{OUT}/sched-{loc}-{width}.png")
        report[f"errors@{width}"] = errors
        ctx.close()

    # Interaction: Dismiss, uncheck one opt-in, Save, reload, re-read.
    ctx = br.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto(BASE, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(1200)
    open_panel(pg)
    pg.click("#sch-retired button"); pg.wait_for_timeout(800)
    dismissed_hidden = pg.evaluate("document.getElementById('sch-retired').hidden")
    pg.uncheck("#sch-market-rules")
    pg.click("#set-advanced button[onclick='saveScheduler()']"); pg.wait_for_timeout(1200)
    cfg = pg.evaluate("fetch('/api/scheduler/config').then(r => r.json())")
    pg.reload(wait_until="networkidle"); pg.wait_for_timeout(1200)
    open_panel(pg)
    pg.click("#set-advanced button[onclick='previewTargets()']"); pg.wait_for_timeout(900)
    report["interaction"] = {
        "dismiss_hides_line": dismissed_hidden,
        "saved_rules": cfg["auto_run_market_rules"], "saved_stats": cfg["auto_refresh_stat_subscriptions"],
        "saved_retired": cfg["retired"], "mode_in_config": "mode" in cfg,
        "after_reload": state(pg),
        "targets_preview": pg.evaluate("document.getElementById('sched-targets').textContent").strip()[:160],
        "errors": errors,
    }
    ctx.close(); br.close()

json.dump(report, open(f"{OUT}/report.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1)[:4000])
