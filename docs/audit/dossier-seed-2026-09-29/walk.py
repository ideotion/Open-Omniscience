"""S05-11 S4 click-through: the dossier seed, in en and ar, on a server
started from seed.py's data folder.

NOTHING HERE GOES ONLINE, and the walk checks it: before the first page it engages airplane
mode through the app's own endpoint and reads it back, and the browser aborts every request
that is not to this loopback server.

Walked: (1) the place card -> "Open the dossier"; the passport line, the three routes, the five
joined rails and the three named as not joined; (2) the Places rail's chip back to the place card;
(3) the analysis window's When/Where/Who subtab, where the Who chip on the item carries the
dossier button and the name two items share carries none; (4) "Open these 4 articles in the
analysis window"; (5) the same dossier in Arabic; (6) 375 px. Every page error, console error and
response of 400 or more is recorded, with an overlap probe over the dialog.
"""
import json
import os
import re
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8763")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/s4/out")
PLACE = "node/240037735"
QID = "Q999999101"
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


def dossier_state(pg):
    return pg.evaluate("""() => {
      const b = document.getElementById('dossier-body');
      return {
        title: document.getElementById('dossier-title').innerText,
        qid: document.getElementById('dossier-qid').innerText,
        passport: (b.querySelector('.dossier-passport') || {}).innerText || null,
        passport_visible: !!(b.querySelector('.dossier-passport') || {checkVisibility(){return false}}).checkVisibility(),
        rails: [...b.querySelectorAll('.dossier-rails tr')].map(r => [r.querySelector('th').innerText, r.querySelector('td').innerText]),
        not_joined: [...b.querySelectorAll('.dossier-list li strong')].map(s => s.innerText),
        caveat_visible: !!(b.querySelector('.card-caveat') || {checkVisibility(){return false}}).checkVisibility(),
        open_button: (b.querySelector('.dossier-open') || {}).innerText || null,
      };
    }""")


def open_dossier_from_place_card(pg):
    pg.evaluate("(id) => openPlaceCard(id)", PLACE)
    pg.wait_for_selector("#place-card[open] .pc-dossier", timeout=10000)
    label = pg.inner_text("#place-card .pc-dossier")
    pg.click("#place-card .pc-dossier")
    pg.wait_for_selector("#dossier[open] .dossier-passport", timeout=10000)
    return label


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

    # 1. The place card -> "Open the dossier".
    report["place_card_button"] = open_dossier_from_place_card(pg)
    report["place_card_closed"] = not pg.evaluate("() => document.getElementById('place-card').open")
    report["en"] = dossier_state(pg)
    report["en_text"] = pg.inner_text("#dossier-body")
    report["en_overlaps"] = pg.evaluate(OVERLAP_JS, "#dossier")
    pg.locator("#dossier").screenshot(path=f"{OUT}/1-dossier-en.png")

    # 2. The Places rail's chip opens the place card again.
    pg.click("#dossier .dossier-place")
    pg.wait_for_selector("#place-card[open] #pc-body table", timeout=8000)
    report["places_chip_opens_card"] = pg.inner_text("#pc-title")
    report["dossier_closed_by_chip"] = not pg.evaluate("() => document.getElementById('dossier').open")
    pg.evaluate("() => document.getElementById('place-card').close()")

    # 3. The analysis window's When/Where/Who: the Who chip on the item carries the button.
    ids = api("/api/entities/dossier?qid=" + QID)["article_ids"]
    every = ids + [ids[-1] + 1]  # and the article that names only "Matter"
    pg.evaluate("(ids) => openAnalysisForIds(ids, 'walk: the dossier articles')", every)
    pg.wait_for_selector("#an-subtabs [data-tab='www']", state="visible", timeout=15000)
    pg.click("#an-subtabs [data-tab='www']")
    pg.wait_for_selector("#an-www .an-facet", timeout=15000)
    pg.wait_for_timeout(500)
    report["who_chips"] = pg.evaluate("""() => [...document.querySelectorAll('#an-www .an-facet[data-on-click^="branchByFacet(\\'who\\'"]')]
        .map(c => [c.innerText, !!(c.nextElementSibling && c.nextElementSibling.classList.contains('an-dossier'))])""")
    pg.locator("#an-www").screenshot(path=f"{OUT}/2-who-facet-en.png")
    pg.click("#an-www .an-dossier")
    pg.wait_for_selector("#dossier[open] .dossier-passport", timeout=10000)
    report["who_opens"] = dossier_state(pg)["qid"]

    # 4. "Open these 4 articles in the analysis window".
    pg.click("#dossier .dossier-open")
    pg.wait_for_timeout(1500)
    report["open_articles_label"] = pg.inner_text("#an-query")
    report["dossier_closed_by_open"] = not pg.evaluate("() => document.getElementById('dossier').open")

    # 5. Arabic.
    switch(pg, "ar", errors)
    report["ar_dir"] = pg.evaluate("() => document.documentElement.dir")
    report["ar_place_card_button"] = open_dossier_from_place_card(pg)
    report["ar"] = dossier_state(pg)
    ar_all = pg.inner_text("#dossier")
    strip = lambda s: re.sub(r"Zermatt|zermatt|OpenStreetMap|Wikidata|Wikipedia|Q\d+|n\d+|node/\d+|CHE|"
                             r"Ordinance[^\n]*|Tourism[^\n]*|fr:p\d+", " ", s)
    report["ar_latin_left"] = sorted(set(LATIN.findall(strip(ar_all))))
    report["ar_junk"] = sorted(set(m.group(0) for m in JUNK.finditer(ar_all)))
    report["ar_overlaps"] = pg.evaluate(OVERLAP_JS, "#dossier")
    pg.locator("#dossier").screenshot(path=f"{OUT}/3-dossier-ar.png")

    # 6. 375 px, ar: the dialog fits, no horizontal page scroll.
    pg.set_viewport_size({"width": 375, "height": 800})
    pg.wait_for_timeout(600)
    report["narrow_overflow_px"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    report["narrow_dialog_overflow_px"] = pg.evaluate(
        "() => { const d = document.getElementById('dossier'); return d.getBoundingClientRect().right - window.innerWidth; }")
    report["narrow_overlaps"] = pg.evaluate(OVERLAP_JS, "#dossier")
    pg.screenshot(path=f"{OUT}/4-dossier-375-ar.png")

    report["errors"] = errors
    report["bad_responses"] = bad
    report["blocked_non_loopback"] = blocked
    browser.close()

report["airplane_after_walk"] = api("/api/system/network").get("online") is False
with open(f"{OUT}/report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False, indent=1)[:9000])
