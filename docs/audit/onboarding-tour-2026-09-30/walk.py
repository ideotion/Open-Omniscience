"""S05-11 S5 click-through: the onboarding tour and the signed-evidence review.

NOTHING HERE GOES ONLINE, and the walk checks it: before the first page it engages airplane
mode through the app's own endpoint and reads it back, and the browser aborts every request
that is not to this loopback server.

Walked: (1) the tour from all three entry points (Settings -> General, the command palette,
Help & docs) at Full depth, every step, one "Open <tab>" button; (2) Essentials: the "more"
step names the ten unpinned tabs, its button opens the sidebar's "Show more", the last step's
button lands on the depth setting; (3) the tour changes nothing (depth, localStorage and the
sidebar are read before and after, apart from the button the walk presses); (4) the same tour
in Arabic and at 375 px; (5) the evidence review from the Search tab: numbers, plaintext line,
"no evidence key yet" (and the plan call created none), Save, the download, the done message
with the key, and the key that now exists; (6) the review in Arabic and at 375 px. Every page
error, console error and response of 400 or more is recorded, with an overlap probe.
"""
import json
import os
import re
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8765")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/s5/out")
KEY = os.environ.get("OO_WALK_KEY", "/tmp/claude-0/s5/data/keys/evidence_ed25519.pem")
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


def tour_step(pg):
    return pg.evaluate("""() => {
      const b = document.getElementById('tour-body');
      const q = (s) => (b.querySelector(s) || {}).innerText || null;
      return {
        counter: q('.hint'), title: q('.tour-title'),
        body: [...b.querySelectorAll('p')].map(p => p.innerText).filter(t => t),
        list: [...b.querySelectorAll('.tour-list li')].map(li => li.innerText),
        button: q('[data-tour-act]'),
        next: document.getElementById('tour-next').innerText,
        back_disabled: document.getElementById('tour-back').disabled,
      };
    }""")


def walk_tour(pg, limit=30):
    steps = []
    for _ in range(limit):
        steps.append(tour_step(pg))
        if steps[-1]["next"] != "Next" and not re.search(r"\S", steps[-1]["next"] or ""):
            break
        if not pg.evaluate("() => document.getElementById('tour').open"):
            break
        last = pg.evaluate("() => { const s = document.getElementById('tour-body').querySelector('.hint').innerText;"
                           " const m = s.match(/(\\d+)\\D+(\\d+)/); return m && m[1] === m[2]; }")
        if last:
            break
        pg.click("#tour-next")
        pg.wait_for_timeout(80)
    return steps


def state(pg):
    return pg.evaluate("""() => ({
      depth: (JSON.parse(localStorage.getItem('oo.ui') || '{}').depth) || null,
      ls_keys: Object.keys(localStorage).sort(),
      ls_ui: localStorage.getItem('oo.ui'),
      tabs: [...document.querySelectorAll('#navGroups .nav-item[data-tab]')].map(b => [b.dataset.tab, b.checkVisibility()]),
      more_row: (document.getElementById('nav-more') || {}).innerText || null,
    })""")


report = {}
api("/api/system/network", {"online": False})
report["airplane_before_walk"] = api("/api/system/network").get("online") is False
report["key_before_walk"] = os.path.exists(KEY)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    ctx = browser.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True)
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

    # 0. it never starts by itself
    report["tour_open_at_boot"] = pg.evaluate("() => document.getElementById('tour').open")

    # 1. FULL depth: the three entry points.
    pg.evaluate("() => setDepth('full')")
    # the tour itself, walked end to end with NO button pressed: nothing may be stored
    # the app's own first-run network coachmark records that it was shown, a little after boot;
    # let it settle so the tour is measured alone (it is not the tour's write)
    pg.wait_for_timeout(4000)
    pg.evaluate("() => openTour()")
    pg.wait_for_selector("#tour[open]")
    quiet_before = state(pg)
    walk_tour(pg)
    quiet_after = state(pg)
    report["quiet_walk_changed_nothing"] = quiet_before == quiet_after
    if quiet_before != quiet_after:
        report["quiet_walk_diff"] = {k: [quiet_before[k], quiet_after[k]] for k in quiet_before if quiet_before[k] != quiet_after[k]}
    pg.click("#tour-skip")
    before = state(pg)
    entry = {}
    pg.evaluate("() => { showTab('settings'); (_setSubtabs || {select: showSetCat}).select('general'); }")
    pg.wait_for_timeout(300)
    pg.click("#tab-settings button[data-on-click='openTour()']")
    pg.wait_for_selector("#tour[open]", timeout=5000)
    entry["settings"] = tour_step(pg)["title"]
    pg.click("#tour-skip")
    entry["skip_closes"] = not pg.evaluate("() => document.getElementById('tour').open")

    pg.evaluate("() => showTab('help')")
    pg.click("#tab-help button[data-on-click='openTour()']")
    pg.wait_for_selector("#tour[open]", timeout=5000)
    entry["help"] = tour_step(pg)["title"]
    pg.keyboard.press("Escape")
    entry["escape_closes"] = not pg.evaluate("() => document.getElementById('tour').open")

    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(300)
    pg.keyboard.type("tour")
    pg.wait_for_timeout(300)
    pg.locator("#palette .pal-item").filter(has_text=re.compile(r"^\s*Take the tourHelp\s*$")).first.click()
    pg.wait_for_selector("#tour[open]", timeout=5000)
    entry["palette"] = tour_step(pg)["title"]
    report["entry_points"] = entry

    steps = walk_tour(pg)
    report["full_steps"] = [(s["counter"], s["title"], s["button"]) for s in steps]
    report["full_first_text"] = steps[0]
    report["full_last"] = steps[-1]
    report["full_overlaps"] = pg.evaluate(OVERLAP_JS, "#tour")
    pg.locator("#tour").screenshot(path=f"{OUT}/1-tour-full-last-en.png")
    # an "Open <tab>" button opens the tab and closes the tour
    pg.click("#tour-skip")
    pg.evaluate("() => openTour()")
    pg.wait_for_selector("#tour[open]")
    pg.click("#tour-next"); pg.click("#tour-next"); pg.click("#tour-next")   # chrome -> home -> feed -> explore
    step = tour_step(pg)
    pg.click("[data-tour-act]")
    pg.wait_for_timeout(300)
    report["open_button"] = {"step": step["title"], "button": step["button"],
                             "tour_closed": not pg.evaluate("() => document.getElementById('tour').open"),
                             "tab_active": pg.evaluate("() => document.querySelector('.nav-item.active').dataset.tab")}
    after = state(pg)
    report["full_changed_nothing"] = {"depth_same": before["depth"] == after["depth"],
                                      "ls_ui_same": before["ls_ui"] == after["ls_ui"],
                                      "ls_keys_added_by_the_pressed_tab_button": sorted(set(after["ls_keys"]) - set(before["ls_keys"]))}

    # 2. ESSENTIALS
    pg.evaluate("() => setDepth('essentials')")
    pg.evaluate("() => showTab('home')")
    before = state(pg)
    report["essentials_sidebar"] = before
    pg.evaluate("() => openTour()")
    pg.wait_for_selector("#tour[open]")
    ess = walk_tour(pg)
    report["essentials_steps"] = [(s["counter"], s["title"], s["button"]) for s in ess]
    more = next(s for s in ess if s["list"])
    report["essentials_more"] = more
    report["ess_overlaps"] = pg.evaluate(OVERLAP_JS, "#tour")
    # go to the "more" step and press its button
    pg.click("#tour-skip")
    pg.evaluate("() => openTour()")
    pg.wait_for_selector("#tour[open]")
    for _ in range(3):
        pg.click("#tour-next")
    pg.locator("#tour").screenshot(path=f"{OUT}/2-tour-more-essentials-en.png")
    pg.click("[data-tour-act]")
    pg.wait_for_timeout(400)
    mid = state(pg)
    report["more_button"] = {"tour_closed": not pg.evaluate("() => document.getElementById('tour').open"),
                             "visible_tabs": [t for t, v in mid["tabs"] if v], "more_row": mid["more_row"]}
    # the depth step's button
    pg.evaluate("() => openTour()")
    pg.wait_for_selector("#tour[open]")
    for _ in range(4):
        pg.click("#tour-next")
    last = tour_step(pg)
    pg.click("[data-tour-act]")
    pg.wait_for_timeout(400)
    report["depth_button"] = {"step": last["title"], "button": last["button"], "next": last["next"],
                              "settings_visible": pg.evaluate("() => document.getElementById('tab-settings').classList.contains('active')"),
                              "depth_control_visible": pg.evaluate("() => document.getElementById('set-depth').checkVisibility()")}
    after = state(pg)
    report["essentials_changed_nothing"] = {"depth_same": before["depth"] == after["depth"],
                                            "ls_keys_same": before["ls_keys"] == after["ls_keys"]}

    # 4. Arabic, and 375 px
    pg.evaluate("() => setDepth('essentials')")
    switch(pg, "ar", errors)
    report["ar_dir"] = pg.evaluate("() => document.documentElement.dir")
    pg.evaluate("() => openTour()")
    pg.wait_for_selector("#tour[open]")
    ar = walk_tour(pg)
    report["ar_steps"] = [(s["counter"], s["title"], s["button"]) for s in ar]
    all_ar = " ".join(" ".join(s["body"]) + " " + s["title"] + " " + " ".join(s["list"]) for s in ar)
    report["ar_junk"] = sorted(set(m.group(0) for m in JUNK.finditer(all_ar)))
    report["ar_latin_left"] = sorted(set(LATIN.findall(re.sub(r"Ctrl|Ed25519|Merkle|SHA|JSON", " ", all_ar))))
    report["ar_overlaps"] = pg.evaluate(OVERLAP_JS, "#tour")
    pg.click("#tour-skip")
    pg.evaluate("() => openTour()")
    pg.wait_for_selector("#tour[open]")
    for _ in range(3):
        pg.click("#tour-next")
    pg.locator("#tour").screenshot(path=f"{OUT}/3-tour-more-essentials-ar.png")
    pg.set_viewport_size({"width": 375, "height": 800})
    pg.wait_for_timeout(500)
    report["ar_375_overflow_px"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    report["ar_375_dialog_overflow_px"] = pg.evaluate("() => document.getElementById('tour').getBoundingClientRect().right - window.innerWidth")
    report["ar_375_overlaps"] = pg.evaluate(OVERLAP_JS, "#tour")
    pg.screenshot(path=f"{OUT}/4-tour-375-ar.png")
    pg.click("#tour-skip")
    pg.set_viewport_size({"width": 1366, "height": 900})
    switch(pg, "en", errors)

    # 5. The evidence review from the Search tab.
    pg.evaluate("() => setDepth('full')")
    pg.evaluate("() => showTab('explore')")
    pg.wait_for_selector("#q", state="visible")
    pg.click("#tab-search button[data-on-click='exportEvidence()']")
    pg.wait_for_timeout(500)
    report["no_query_refusal"] = {"dialog_open": pg.evaluate("() => document.getElementById('evidence-review').open"),
                                  "toast": pg.evaluate("() => (document.querySelector('.toast, #toast') || {}).innerText || null")}
    pg.fill("#q", "glacier")
    pg.click("#tab-search button[data-on-click='doSearch()']")
    pg.wait_for_timeout(1500)
    pg.click("#tab-search button[data-on-click='exportEvidence()']")
    pg.wait_for_selector("#evidence-review[open] .card-caveat", timeout=8000)
    rv = pg.evaluate("""() => ({
      title: document.querySelector('#evidence-review h3').innerText,
      text: document.getElementById('evidence-body').innerText,
      save_visible: document.getElementById('evidence-save').checkVisibility(),
      close: document.getElementById('evidence-close').innerText,
      caveats_visible: [...document.querySelectorAll('#evidence-body .card-caveat')].map(c => c.checkVisibility()),
    })""")
    report["review"] = rv
    report["review_overlaps"] = pg.evaluate(OVERLAP_JS, "#evidence-review")
    report["key_after_review"] = os.path.exists(KEY)
    pg.locator("#evidence-review").screenshot(path=f"{OUT}/5-evidence-review-en.png")
    with pg.expect_download() as dl:
        pg.click("#evidence-save")
    d = dl.value
    saved = d.path()
    bundle = json.load(open(saved, encoding="utf-8"))
    pg.wait_for_selector("#evidence-body .claim-key", timeout=8000)
    report["download"] = {"name": d.suggested_filename, "items": bundle["manifest"]["item_count"],
                          "algorithm": bundle.get("algorithm")}
    done = pg.evaluate("""() => ({
      text: document.getElementById('evidence-body').innerText,
      key_shown: (document.querySelector('#evidence-body .claim-key') || {}).innerText || null,
      save_hidden: document.getElementById('evidence-save').hidden,
      close: document.getElementById('evidence-close').innerText,
    })""")
    report["done"] = done
    report["done_key_matches_bundle"] = done["key_shown"] == bundle["public_key"]
    report["key_after_save"] = os.path.exists(KEY)
    report["done_overlaps"] = pg.evaluate(OVERLAP_JS, "#evidence-review")
    pg.locator("#evidence-review").screenshot(path=f"{OUT}/6-evidence-done-en.png")
    pg.click("#evidence-close")
    # second open: a key exists now
    pg.click("#tab-search button[data-on-click='exportEvidence()']")
    pg.wait_for_selector("#evidence-review[open] .card-caveat", timeout=8000)
    report["review_with_key"] = pg.evaluate("() => document.getElementById('evidence-body').innerText")
    # Arabic + 375: switch with the dialog closed (the switcher's own Escape would close it),
    # reopen, and prove a language change while it is OPEN redraws it.
    pg.click("#evidence-close")
    switch(pg, "ar", errors)
    report["ar_q_value"] = pg.evaluate("() => document.getElementById('q').value")
    report["ar_toasts_before_open"] = pg.evaluate("() => [...document.querySelectorAll('.toast, #toast, .note')].filter(e => e.checkVisibility()).map(e => e.innerText)")
    pg.click("#tab-search button[data-on-click='exportEvidence()']")
    pg.wait_for_selector("#evidence-review[open] .card-caveat", timeout=8000)
    pg.wait_for_timeout(300)
    ar_text = pg.evaluate("() => document.getElementById('evidence-review').innerText")
    report["ev_ar_dir"] = pg.evaluate("() => getComputedStyle(document.getElementById('evidence-review')).direction")
    report["ev_ar_junk"] = sorted(set(m.group(0) for m in JUNK.finditer(ar_text)))
    report["ev_ar_latin_left"] = sorted(set(LATIN.findall(re.sub(r"Ed25519|Merkle|SHA|JSON|manifest|items|signature|public_key|evidence|bundle|verify|scripts|python|Glacier|glacier|canonical_url|content_sha256|published_at|source_id|stored_hash|verify_evidence", " ", ar_text, flags=re.I))))
    report["ev_ar_overlaps"] = pg.evaluate(OVERLAP_JS, "#evidence-review")
    pg.locator("#evidence-review").screenshot(path=f"{OUT}/7-evidence-review-ar.png")
    pg.set_viewport_size({"width": 375, "height": 800})
    pg.wait_for_timeout(500)
    report["ev_375_overflow_px"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    report["ev_375_dialog_overflow_px"] = pg.evaluate("() => document.getElementById('evidence-review').getBoundingClientRect().right - window.innerWidth")
    report["ev_375_overlaps"] = pg.evaluate(OVERLAP_JS, "#evidence-review")
    pg.screenshot(path=f"{OUT}/8-evidence-375-ar.png")
    pg.set_viewport_size({"width": 1366, "height": 900})
    en_before = pg.evaluate("() => document.getElementById('evidence-body').innerText")
    pg.evaluate("() => OOI18N.setLang('en')")
    pg.wait_for_timeout(600)
    en_after = pg.evaluate("() => document.getElementById('evidence-body').innerText")
    report["review_redraws_on_language_change"] = {"open_still": pg.evaluate("() => document.getElementById('evidence-review').open"),
                                                   "changed": en_before != en_after,
                                                   "english_now": "Plaintext" in en_after}

    report["errors"] = errors
    report["bad_responses"] = bad
    report["blocked_non_loopback"] = blocked
    browser.close()

report["airplane_after_walk"] = api("/api/system/network").get("online") is False
with open(f"{OUT}/report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False, indent=1)[:12000])
