"""S05-11 S2 click-through: the Claim Workspace's step ④ (corroboration offers) and step ⑥ (the
signed export), in en and ar, on a server started from seed.py's data folder.

NOTHING HERE GOES ONLINE, and the walk makes sure of it rather than assuming it: before the
first page it engages airplane mode through the app's own endpoint and reads it back, and the
browser aborts every request that is not to this loopback server. The one offer whose slice is
not held is clicked to show the consent popup and its shadow line, then answered "Stay
offline"; the held slice is served from the local cache.

Step ⑥: the bundle is exported (the download is saved), verified with
scripts/verify_claim_trail.py, checked through the page's own "Check a bundle", then a copy
with one article edited is checked and must fail. Every response of 400 or more, every page
error and every console error is recorded, with an overlap probe over the two new steps.
"""
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8761")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/s2/out")
APP = os.environ.get("OO_WALK_APP", os.getcwd())
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]|\{[a-z_]+\}")
LATIN = re.compile(r"[A-Za-z]{4,}")
CLAIM = "Glacier melt in the Alps has doubled since 2000"
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
    // text a screen reader gets and the eye does not (a chart's data table, clipped to 1 px)
    if (el.closest(".sr-only, .visually-hidden")) continue;
    let clipped = false;
    for (let a = el; a && a !== root; a = a.parentElement) {
      const r = a.getBoundingClientRect(), cs = getComputedStyle(a);
      if ((r.width <= 1 || r.height <= 1) && cs.overflow !== "visible") { clipped = true; break; }
    }
    if (clipped) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const b of r.getClientRects()) if (b.width > 1 && b.height > 1) boxes.push({b, t: n.textContent.trim().slice(0, 40)});
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


def step_text(pg, num):
    return pg.evaluate("""(n) => { const s = [...document.querySelectorAll('#claim-body .claim-step')]
      .find(x => x.querySelector('h3').innerText.includes(n)); return s ? s.innerText : ''; }""", num)


def shot_step(pg, num, path):
    loc = pg.locator("#claim-body .claim-step", has_text=num).first
    loc.screenshot(path=path)


report = {}
# 0. Airplane mode, engaged and read back, before any page loads.
api("/api/system/network", {"online": False})
report["airplane_before_walk"] = api("/api/system/network").get("online") is False

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
    errors, bad, posts = [], [], []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.error: {m.text[:200]}") if m.type == "error" else None)
    pg.on("response", lambda r: bad.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
    pg.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    pg.goto(BASE + "/", wait_until="networkidle")
    close_wizard(pg)

    pg.evaluate("(c) => openClaimWorkspace(c)", CLAIM)
    pg.wait_for_function("() => document.querySelectorAll('#claim-body .claim-step').length === 6", timeout=20000)
    pg.wait_for_timeout(500)

    # 1. Step ④, en: two offers, the host and the shadow drawn before the button.
    s4 = step_text(pg, "④")
    report["s4_en"] = s4
    report["s4_offers"] = pg.evaluate("() => document.querySelectorAll('#claim-body .claim-offer').length")
    report["s4_buttons"] = pg.evaluate("() => [...document.querySelectorAll('[data-claim-wx]')].map(b => b.innerText)")
    report["s4_links_out"] = pg.evaluate("() => [...document.querySelectorAll('#claim-body .claim-offer a')].map(a => a.href)")
    report["s4_overlaps"] = pg.evaluate(OVERLAP_JS, "#claim-body")
    shot_step(pg, "④", f"{OUT}/step4-en.png")

    # 2. The offer whose slice is not held: the consent popup, with the shadow line, answered no.
    idx_ask = pg.evaluate("() => [...document.querySelectorAll('[data-claim-wx]')].findIndex(b => /^Ask /.test(b.innerText))")
    n_posts = len(posts)
    pg.click(f"[data-claim-wx='{idx_ask}']")
    pg.wait_for_selector("#net-consent[open]", timeout=8000)
    pg.wait_for_function("() => !document.getElementById('net-consent-ok').disabled", timeout=8000)
    report["consent_reason"] = pg.inner_text("#net-consent-reason")
    report["consent_shadow"] = pg.inner_text("#net-consent-shadow")
    report["consent_shadow_visible"] = pg.is_visible("#net-consent-shadow")
    pg.locator("#net-consent").screenshot(path=f"{OUT}/consent-shadow-en.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(600)
    report["declined_posted_weather"] = any("/api/weather/context" in u for u in posts[n_posts:])
    report["declined_posted_network"] = any("/api/system/network" in u for u in posts[n_posts:])

    # 3. The held slice: shown from this machine, no consent asked.
    idx_held = pg.evaluate("() => [...document.querySelectorAll('[data-claim-wx]')].findIndex(b => /held/.test(b.innerText))")
    pg.click(f"[data-claim-wx='{idx_held}']")
    pg.wait_for_selector(f"#claim-wx-{idx_held} .wx-chart svg, #claim-wx-{idx_held} .wx-chart canvas", timeout=10000)
    report["held_asked_consent"] = pg.evaluate("() => document.getElementById('net-consent').open")
    report["held_text"] = pg.inner_text(f"#claim-wx-{idx_held}")
    shot_step(pg, "④", f"{OUT}/step4-held-en.png")

    # 4. Step ⑥, en: the statements, then the export.
    report["s6_en"] = step_text(pg, "⑥")
    shot_step(pg, "⑥", f"{OUT}/step6-en.png")
    with pg.expect_download(timeout=30000) as dl:
        pg.click("#claim-export")
    d = dl.value
    zpath = f"{OUT}/{d.suggested_filename}"
    d.save_as(zpath)
    pg.wait_for_selector("#claim-export-out p", timeout=10000)
    report["export_filename"] = d.suggested_filename
    report["export_done_text"] = pg.inner_text("#claim-export-out")
    shot_step(pg, "⑥", f"{OUT}/step6-done-en.png")
    with zipfile.ZipFile(zpath) as zf:
        report["zip_members"] = sorted(zf.namelist())
        report["zip_attribution"] = zf.read("ATTRIBUTION.md").decode()[:600]
        report["zip_privacy_rows"] = [ln.split("|")[1].strip() + " -> " + ln.split("|")[2].strip()
                                      for ln in zf.read("WHAT-A-READER-CAN-SEE.md").decode().splitlines()
                                      if ln.startswith("| ") and not ln.startswith("| what")]
    v = subprocess.run([sys.executable, "scripts/verify_claim_trail.py", zpath], cwd=APP,
                       capture_output=True, text=True)
    report["script_verify_exit"] = v.returncode
    report["script_verify_out"] = v.stdout

    # 5. "Check a bundle" in the page: the file as saved, then a copy with one article edited.
    pg.set_input_files("#claim-verify-file", zpath)
    pg.wait_for_selector("#claim-verify-out .note", timeout=10000)
    report["page_verify_ok"] = pg.inner_text("#claim-verify-out")
    tampered = f"{OUT}/tampered.zip"
    edited = None
    with zipfile.ZipFile(zpath) as src, zipfile.ZipFile(tampered, "w") as dst:
        for n in src.namelist():
            b = src.read(n)
            if edited is None and n.startswith("articles/") and b"doubled" in b:
                b = b.replace(b"doubled", b"tripled", 1)
                edited = n
            dst.writestr(n, b)
    report["tampered_member"] = edited
    pg.set_input_files("#claim-verify-file", tampered)
    pg.wait_for_function("() => /Not verified/.test(document.getElementById('claim-verify-out').innerText)", timeout=10000)
    report["page_verify_tampered"] = pg.inner_text("#claim-verify-out")
    shot_step(pg, "⑥", f"{OUT}/step6-verify-en.png")
    report["s46_overlaps_en"] = pg.evaluate(OVERLAP_JS, "#claim-body")

    # 6. Arabic: ④ and ⑥ redrawn from what the page holds, the slice and the results kept.
    switch(pg, "ar", errors)
    pg.wait_for_timeout(800)
    ar4, ar6 = step_text(pg, "④"), step_text(pg, "⑥")
    strip = lambda s: re.sub(r"https?://\S+|\S+\.(json|md|zip|py)\b|[0-9a-f]{16,}|archive-api\.open-meteo\.com|scripts/\S+|SHA-256|Ed25519|ZIP|IP|Q823|articles/|corroboration/|precipitation_sum|temperature_2m_max|Zermatt|France|mm", " ", s)
    report["ar_dir"] = pg.evaluate("() => document.documentElement.dir")
    report["ar_latin_left_s4"] = sorted(set(LATIN.findall(strip(ar4))))
    report["ar_latin_left_s6"] = sorted(set(LATIN.findall(strip(ar6))))
    report["ar_junk"] = sorted(set(m.group(0) for m in JUNK.finditer(ar4 + ar6)))
    report["ar_kept_slice"] = pg.evaluate(f"() => !!document.querySelector('#claim-wx-{idx_held} .wx-chart svg, #claim-wx-{idx_held} .wx-chart canvas')")
    report["ar_kept_export"] = bool(pg.inner_text("#claim-export-out").strip())
    report["s46_overlaps_ar"] = pg.evaluate(OVERLAP_JS, "#claim-body")
    shot_step(pg, "④", f"{OUT}/step4-ar.png")
    shot_step(pg, "⑥", f"{OUT}/step6-ar.png")
    # The consent popup's shadow line in Arabic.
    pg.click(f"[data-claim-wx='{idx_ask}']")
    pg.wait_for_selector("#net-consent[open]", timeout=8000)
    pg.wait_for_function("() => !document.getElementById('net-consent-ok').disabled", timeout=8000)
    report["consent_shadow_ar"] = pg.inner_text("#net-consent-shadow")
    pg.locator("#net-consent").screenshot(path=f"{OUT}/consent-shadow-ar.png")
    pg.click("#net-consent-cancel")
    pg.wait_for_timeout(400)

    # 7. 375 px, ar: no horizontal page scroll with ④ and ⑥ drawn.
    pg.set_viewport_size({"width": 375, "height": 800})
    pg.wait_for_timeout(600)
    report["narrow_overflow_px"] = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    report["narrow_overlaps"] = pg.evaluate(OVERLAP_JS, "#claim-body")
    shot_step(pg, "⑥", f"{OUT}/step6-375-ar.png")

    report["errors"] = errors
    report["bad_responses"] = bad
    report["blocked_non_loopback"] = blocked
    browser.close()

report["airplane_after_walk"] = api("/api/system/network").get("online") is False
with open(f"{OUT}/report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in report.items() if k not in ("s4_en", "s6_en", "zip_attribution")},
                 ensure_ascii=False, indent=1)[:6000])
