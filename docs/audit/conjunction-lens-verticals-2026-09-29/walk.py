"""S05-11 S3 click-through: the Conjunction Lens on several verticals, in en and ar, on a
server started from seed.py's data folder.

NOTHING HERE GOES ONLINE, and the walk checks it: before the first page it engages airplane
mode through the app's own endpoint and reads it back, and the browser aborts every request
that is not to this loopback server.

Walked: (1) the analysis window's Keywords subtab, the whole corpus, then its scope switched
to Law and the three panels drawn (where the terms cluster, when, compare); (2) Living sources
→ Law → "Combine keywords in law", and the near search it hands to the Search tab; (3) Living
sources → Wikipedia → "Combine keywords in Wikipedia"; (4) the place card → "Combine keywords in
these articles"; (5) the same in Arabic; (6) 375 px. Every page error, console error and
response of 400 or more is recorded, with an overlap probe over the lens.
"""
import json
import os
import re
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8762")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/s3/out")
PLACE = "node/240037735"
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]|\{[a-z_]+\}")
LATIN = re.compile(r"[A-Za-z]{4,}")
os.makedirs(OUT, exist_ok=True)

OVERLAP_JS = """(sel) => {
  const root = document.querySelector(sel); if (!root) return [];
  const boxes = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement;
    if (!el || !el.checkVisibility || !el.checkVisibility()) continue;
    if (el.closest(".sr-only, .visually-hidden, svg, canvas")) continue;
    // text scrolled out of a scrolling ancestor is not on screen, whatever its box says
    const clips = [];
    for (let a = el.parentElement; a; a = a.parentElement) {
      const o = getComputedStyle(a).overflowY;
      if (o === "auto" || o === "scroll" || o === "hidden") clips.push(a.getBoundingClientRect());
    }
    const r = document.createRange(); r.selectNodeContents(n);
    for (const b of r.getClientRects()) {
      if (b.width <= 1 || b.height <= 1) continue;
      if (clips.some(c => b.bottom <= c.top || b.top >= c.bottom || b.right <= c.left || b.left >= c.right)) continue;
      boxes.push({b, t: n.textContent.trim().slice(0, 40)});
    }
  }
  const hits = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i].b, c = boxes[j].b;
    const ox = Math.min(a.right, c.right) - Math.max(a.left, c.left);
    const oy = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top);
    if (ox > 2 && oy > 2) hits.push([boxes[i].t, boxes[j].t]);
  }
  return hits.slice(0, 10);
}"""


def api(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


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


def combine(pg, pfx, terms, op="intersection"):
    pg.fill(f"#{pfx}-conj-terms", terms)
    pg.click(f"[data-on-click=\"conjCombine('{pfx}','{op}')\"]")
    pg.wait_for_function(f"() => /Read in|{'|'.join(['مقروء في'])}/.test((document.getElementById('{pfx}-conj-result') || {{}}).innerText || '')",
                         timeout=15000)
    pg.wait_for_timeout(400)
    return pg.inner_text(f"#{pfx}-conj-result")


def lens_state(pg, pfx):
    return pg.evaluate("""(p) => {
      const r = document.getElementById(p + '-conj-result');
      const sel = document.getElementById(p + '-conj-scope');
      return {
        scope_value: sel ? sel.value : null,
        scope_options: sel ? [...sel.options].map(o => o.text) : null,
        chips: [...r.querySelectorAll('.chip')].map(c => c.innerText),
        cluster_links: [...r.querySelectorAll('ol a')].map(a => [a.innerText, a.getAttribute('href')]),
        trend_drawn: !!(document.getElementById(p + '-conj-trend') || {querySelector(){return null}}).querySelector('svg, canvas'),
        near_button: [...r.querySelectorAll('button')].map(b => b.innerText).filter(t => /words|كلمات/.test(t)),
      };
    }""", pfx)


report = {}
api("/api/system/network", {"online": False})
report["airplane_before_walk"] = api("/api/system/network").get("online") is False

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    blocked = []

    def gate(route):
        u = route.request.url
        if u.startswith(BASE) or u.startswith("data:") or u.startswith("blob:"):
            route.continue_()
        else:
            blocked.append(u)
            route.abort()

    ctx.route("**/*", gate)
    pg = ctx.new_page()
    errors, bad = [], []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.error: {m.text[:200]}") if m.type == "error" else None)
    pg.on("response", lambda r: bad.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
    pg.goto(BASE + "/", wait_until="networkidle")
    close_wizard(pg)

    # 1. The analysis window's Keywords subtab: the whole corpus, then Law.
    pg.evaluate("() => openAnalysisForIds([1,2,3,4,5,6,7,8,9,10,11], 'walk: every article')")
    pg.wait_for_selector("#an-subtabs [data-tab='keywords']", state="visible", timeout=15000)
    pg.click("#an-subtabs [data-tab='keywords']")
    pg.wait_for_selector("#an-conj-terms", state="visible", timeout=15000)
    report["an_all_text"] = combine(pg, "an", "drought, hydropower")
    report["an_all"] = lens_state(pg, "an")
    pg.select_option("#an-conj-scope", "law")
    pg.wait_for_function("() => /Law/.test(document.getElementById('an-conj-result').innerText)", timeout=15000)
    pg.wait_for_timeout(400)
    report["an_law_text"] = pg.inner_text("#an-conj-result")
    report["an_law"] = lens_state(pg, "an")
    pg.select_option("#an-conj-scope", "")
    pg.wait_for_function("() => /The whole corpus/.test(document.getElementById('an-conj-result').innerText)", timeout=15000)
    combine(pg, "an", "drought")
    pg.fill("#an-conj-vs", "glacier")
    pg.click("[data-on-click=\"conjContrast('an')\"]")
    pg.wait_for_selector("#an-conj-contrast table", timeout=15000)
    report["an_contrast"] = pg.inner_text("#an-conj-contrast")
    report["an_trend_drawn"] = lens_state(pg, "an")["trend_drawn"]
    report["an_overlaps"] = pg.evaluate(OVERLAP_JS, "#an-conj-result")
    pg.locator(".conj-lens").first.screenshot(path=f"{OUT}/1-analysis-window-en.png")

    # 2. Living sources → Law → "Combine keywords in law", then the near search.
    pg.evaluate("() => showTab('living')")
    pg.click("#living-subtabs [data-tab='law']")
    pg.wait_for_selector("#living-law [data-on-click=\"openConjunctionLensChannel('law')\"]", state="visible")
    pg.click("#living-law [data-on-click=\"openConjunctionLensChannel('law')\"]")
    pg.wait_for_selector("#conj-dialog[open] #cd-conj-terms", timeout=8000)
    report["law_dialog_scope_value"] = pg.eval_on_selector("#cd-conj-scope", "s => s.value")
    report["law_text"] = combine(pg, "cd", "drought, water permit")
    report["law"] = lens_state(pg, "cd")
    report["law_overlaps"] = pg.evaluate(OVERLAP_JS, "#conj-dialog")
    pg.locator("#conj-dialog").screenshot(path=f"{OUT}/2-law-dialog-en.png")
    pg.click("[data-on-click=\"conjSearchNear('cd')\"]")
    pg.wait_for_timeout(1500)
    report["near_dialog_closed"] = not pg.evaluate("() => document.getElementById('conj-dialog').open")
    report["near_search_query"] = pg.input_value("#q")
    report["near_on_search_tab"] = pg.is_visible("#tab-search")

    # 3. Living sources → Wikipedia → "Combine keywords in Wikipedia".
    pg.evaluate("() => showTab('living')")
    pg.click("#living-subtabs [data-tab='wiki']")
    pg.click("#living-wiki [data-on-click=\"openConjunctionLensChannel('wikipedia')\"]")
    pg.wait_for_selector("#conj-dialog[open] #cd-conj-terms", timeout=8000)
    report["wiki_dialog_scope_value"] = pg.eval_on_selector("#cd-conj-scope", "s => s.value")
    report["wiki_text"] = combine(pg, "cd", "glacier, river", "union")
    report["wiki"] = lens_state(pg, "cd")
    pg.locator("#conj-dialog").screenshot(path=f"{OUT}/3-wikipedia-dialog-en.png")
    pg.evaluate("() => document.getElementById('conj-dialog').close()")

    # 4. The place card → "Combine keywords in these articles".
    pg.evaluate("(id) => openPlaceCard(id)", PLACE)
    pg.wait_for_selector("#place-card[open] .pc-conj", timeout=10000)
    pg.click("#place-card .pc-conj")
    pg.wait_for_selector("#conj-dialog[open] #cd-conj-terms", timeout=8000)
    report["place_card_closed"] = not pg.evaluate("() => document.getElementById('place-card').open")
    report["place_text"] = combine(pg, "cd", "drought, reservoir")
    report["place"] = lens_state(pg, "cd")
    pg.locator("#conj-dialog").screenshot(path=f"{OUT}/4-place-dialog-en.png")
    pg.click("[data-on-click=\"conjOpenCombined('cd')\"]")
    pg.wait_for_timeout(1500)
    report["place_open_as_corpus_query"] = pg.inner_text("#an-query")

    # 5. Arabic: the place lens and the analysis window, redrawn from what the page holds.
    switch(pg, "ar", errors)
    report["ar_dir"] = pg.evaluate("() => document.documentElement.dir")
    pg.evaluate("(id) => openPlaceCard(id)", PLACE)
    pg.wait_for_selector("#place-card[open] .pc-conj", timeout=10000)
    report["ar_place_button"] = pg.inner_text("#place-card .pc-conj")
    pg.click("#place-card .pc-conj")
    pg.wait_for_selector("#conj-dialog[open] #cd-conj-terms", timeout=8000)
    ar_place = combine(pg, "cd", "drought, reservoir")
    pg.fill("#cd-conj-vs", "glacier")
    pg.click("[data-on-click=\"conjContrast('cd')\"]")
    pg.wait_for_selector("#cd-conj-contrast table", timeout=15000)
    ar_all = pg.inner_text("#conj-dialog")
    strip = lambda s: re.sub(r"Zermatt|drought|reservoir|hydropower|river|glacier|harvest|tourism|water permit|"
                             r"Walk [A-Za-z ]+|Drought[^\n]*|Glacier[^\n]*|Hydropower[^\n]*|Tourism[^\n]*|"
                             r"n=\d+|NEAR", " ", s)
    report["ar_place_text"] = ar_place
    report["ar_latin_left"] = sorted(set(LATIN.findall(strip(ar_all))))
    report["ar_junk"] = sorted(set(m.group(0) for m in JUNK.finditer(ar_all)))
    report["ar_overlaps"] = pg.evaluate(OVERLAP_JS, "#conj-dialog")
    pg.locator("#conj-dialog").screenshot(path=f"{OUT}/5-place-dialog-ar.png")

    # 6. 375 px, ar: the dialog fits, no horizontal page scroll.
    pg.set_viewport_size({"width": 375, "height": 800})
    pg.wait_for_timeout(600)
    report["narrow_overflow_px"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    report["narrow_dialog_overflow_px"] = pg.evaluate(
        "() => { const d = document.getElementById('conj-dialog'); return d.getBoundingClientRect().right - window.innerWidth; }")
    report["narrow_overlaps"] = pg.evaluate(OVERLAP_JS, "#conj-dialog")
    pg.screenshot(path=f"{OUT}/6-place-dialog-375-ar.png")

    report["errors"] = errors
    report["bad_responses"] = bad
    report["blocked_non_loopback"] = blocked
    browser.close()

report["airplane_after_walk"] = api("/api/system/network").get("online") is False
with open(f"{OUT}/report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False, indent=1)[:9000])
