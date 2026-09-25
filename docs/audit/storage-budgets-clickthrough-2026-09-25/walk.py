"""S04-08 S4 click-through: Settings -> Data & backup -> Storage, driven through the real
language switcher, on a plaintext install seeded with a real wiki lane file and lane size
history (19 days for the corpus, so a rate is measured; 2 days for the wiki lane, so the
refusal shows)."""
import json
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8744")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/walk")

def close_wizard(pg):
    # The seeded install is fresh, so the first-run guide opens over everything; it is not
    # the surface under test. Closed the way its own Skip would, not hidden with CSS.
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.wait_for_timeout(200)

def open_panel(pg):
    close_wizard(pg)
    pg.evaluate("() => showTab('settings')")
    pg.wait_for_timeout(250)
    # The real subtab button, so the walk takes the operator's path (ooSubtabs -> showSetCat
    # -> loadLaneStorage) and the nav shows the subtab that is open.
    pg.click("#set-subtabs [data-tab='data']")
    pg.wait_for_function("() => document.querySelectorAll('#storage-lanes tr').length > 1", timeout=15000)
    pg.wait_for_timeout(400)

def state(pg):
    return pg.evaluate("""() => {
        const rows = [...document.querySelectorAll('#storage-lanes tbody tr')].map(tr =>
            [...tr.children].map(td => td.innerText.replace(/\\s+/g, ' ').trim()));
        return {
            lang: (window.OOI18N && OOI18N.current && OOI18N.current()) || '?',
            dir: document.documentElement.dir || getComputedStyle(document.body).direction,
            heading: document.querySelector('#storage-panel h2').textContent.trim(),
            headers: [...document.querySelectorAll('#storage-lanes thead th')].map(th => th.textContent.trim()),
            rows,
            reading: document.getElementById('storage-reading').innerText.trim(),
            disk: document.getElementById('storage-disk').innerText.trim(),
            caveat: document.querySelector('#storage-panel .card-caveat').textContent.trim(),
            caveatTitle: (document.querySelector('#storage-panel .card-caveat').getAttribute('title') || '').slice(0, 80),
            budgetInput: !!document.getElementById('storage-budget-wiki'),
            hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
        };
    }""")

def save_budget(pg, value):
    pg.fill("#storage-budget-wiki", str(value))
    pg.click("#storage-panel button.secondary")
    pg.wait_for_timeout(1200)
    return pg.evaluate("""() => ({
        msg: (document.getElementById('storage-budget-msg-wiki') || {}).textContent || '',
        cell: [...document.querySelectorAll('#storage-lanes tbody tr')][1].children[2].innerText.replace(/\\s+/g, ' ').trim(),
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
            report[f"{loc}@{width}"] = state(pg)
            pg.locator("#storage-panel").scroll_into_view_if_needed()
            pg.locator("#storage-panel").screenshot(path=f"{OUT}/storage-{loc}-{width}.png")
        report[f"errors@{width}"] = errors
        ctx.close()

    # Interaction (en): raise the wiki budget, then two refusals, then back to the default.
    ctx = br.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page(); errors = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.goto(BASE, wait_until="networkidle", timeout=60000); pg.wait_for_timeout(1200)
    open_panel(pg)
    raised = save_budget(pg, 35)
    cfg = pg.evaluate("fetch('/api/scheduler/config').then(r => r.json())")
    pg.locator("#storage-panel").screenshot(path=f"{OUT}/storage-en-1440-raised.png")
    fraction = save_budget(pg, "1.5")
    too_big = save_budget(pg, 5000)
    cfg_after_refusals = pg.evaluate("fetch('/api/scheduler/config').then(r => r.json())")
    back = save_budget(pg, 20)
    report["interaction"] = {
        "raised_to_35": raised, "saved_setting": cfg.get("wiki_lane_budget_gb"),
        "fraction_1_5": fraction, "over_max_5000": too_big,
        "setting_after_refusals": cfg_after_refusals.get("wiki_lane_budget_gb"),
        "back_to_20": back, "errors": errors,
    }
    ctx.close(); br.close()

json.dump(report, open(f"{OUT}/report.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(report, ensure_ascii=False, indent=1)[:6000])
