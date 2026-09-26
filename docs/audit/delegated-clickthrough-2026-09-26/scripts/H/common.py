"""Shared helpers for the row-H walk (Playwright sync API, real Chromium)."""
import json
import os
import re

import numpy as np
from PIL import Image

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8810")
OUT = "/tmp/claude-0/walk/H"
PASS = "walk-pass-2026"
JUNK_RX = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")


class Recorder:
    def __init__(self):
        self.page_errors = []
        self.console_errors = []
        self.http_errors = []
        self.junk = []

    def attach(self, pg):
        pg.on("pageerror", lambda e: self.page_errors.append(f"{pg.url} :: {e}"))
        pg.on("console", lambda m: self.console_errors.append(f"{pg.url} :: {m.text[:300]}")
              if m.type == "error" else None)
        pg.on("response", lambda r: self.http_errors.append(f"{r.status} {r.request.method} {r.url}")
              if r.status >= 400 else None)

    def scan_junk(self, pg, where, selector="body"):
        txt = pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : ''; }", selector)
        for m in JUNK_RX.finditer(txt or ""):
            a, b = max(0, m.start() - 60), min(len(txt), m.end() + 60)
            self.junk.append(f"[{where}] ...{txt[a:b]!r}...")


def launch(p, width=1440, height=950):
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium",
                           args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = br.new_context(viewport={"width": width, "height": height})
    return br, ctx


def unlock_and_enter(pg, rec, notes):
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(1500)
    if pg.locator("#pw").count() and pg.locator("#view-unlock").is_visible():
        notes.append("started LOCKED at " + pg.url)
        pg.fill("#pw", PASS)
        pg.click("#btn-unlock")
        pg.wait_for_function("() => location.hash === '#home' || location.pathname === '/' && !!document.getElementById('net-toggle')",
                             timeout=120000)
    else:
        notes.append("no unlock view shown at " + pg.url)
    pg.wait_for_selector("#net-toggle", timeout=60000)
    pg.wait_for_load_state("networkidle", timeout=60000)
    pg.wait_for_timeout(2500)


def close_guide(pg, notes):
    """Close the first-run guide with a REAL click on its X when it is open."""
    if pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
        pg.click("#gw-close")
        pg.wait_for_timeout(400)
        notes.append("guide-wizard was open; closed by clicking #gw-close")


def dismiss_coach(pg, notes):
    loc = pg.locator("#net-coach-dismiss")
    if loc.count() and loc.is_visible():
        loc.click()
        pg.wait_for_timeout(300)
        notes.append("net-coach shown; clicked 'Not now'")


def api(pg, path, method="GET", body=None):
    return pg.evaluate(
        """([p, m, b]) => fetch(p, {method: m, headers: {'Content-Type': 'application/json'},
              body: b === null ? undefined : JSON.stringify(b)}).then(r => r.json())""",
        [path, method, body],
    )


def switch_lang(pg, loc, notes):
    for attempt in (1, 2, 3):
        pg.keyboard.press("Escape")
        pg.mouse.move(2, 2)
        pg.wait_for_timeout(400)
        try:
            pg.click("#lang-switch", timeout=6000)
            pg.wait_for_selector(f"#lang-menu [data-lang='{loc}']", state="visible", timeout=6000)
            pg.click(f"#lang-menu [data-lang='{loc}']", timeout=6000)
            pg.wait_for_function("(l) => document.documentElement.lang === l", arg=loc, timeout=8000)
            pg.wait_for_timeout(800)
            return True
        except Exception as exc:  # noqa: BLE001
            notes.append(f"switch {loc} attempt {attempt}: {str(exc)[:160]}")
    return False


def open_consent_via_plane(pg):
    pg.click("#net-toggle")
    pg.wait_for_function(
        "() => { const d = document.getElementById('net-consent'); return d && d.open && "
        "document.querySelectorAll('#net-consent-lanes span[title], #net-consent-lanes span[data-oo-tip]').length > 3 && "
        "document.getElementById('net-consent-ifaces').textContent.trim() !== '…'; }",
        timeout=15000,
    )
    pg.wait_for_timeout(500)


def consent_snapshot(pg):
    return pg.evaluate("""() => {
      const d = document.getElementById('net-consent');
      const box = document.getElementById('net-consent-lanes');
      const groups = []; let cur = null;
      [...box.children].forEach(ch => {
        if (ch.classList.contains('muted')) { cur = {heading: ch.textContent.trim(), lanes: []}; groups.push(cur); }
        else if (ch.classList.contains('hint')) { /* transport line */ }
        else {
          const s = ch.querySelector('span');
          const n = ch.querySelector('span.muted');
          if (cur && s) cur.lanes.push({label: s.textContent.trim(), n: n ? n.textContent.trim() : null,
                                       hover: s.getAttribute('title') || s.dataset.ooTip || null,
                                       tipTarget: s.classList.contains('oo-tip-target'),
                                       tabindex: s.getAttribute('tabindex')});
        }
      });
      const hint = box.querySelector('.hint');
      const hints = [...d.querySelectorAll('#net-consent-body > .hint')].map(h => {
        const r = h.getBoundingClientRect();
        return {text: h.textContent.replace(/\\s+/g, ' ').trim(), top: r.top, bottom: r.bottom};
      });
      return {
        open: d.open, modal: d.matches(':modal'), dir: getComputedStyle(d).direction,
        title: d.querySelector('h3').textContent.trim(),
        needs: d.querySelector('#net-consent-body .muted').textContent.trim(),
        reason: d.querySelector('#net-consent-reason b').textContent.trim(),
        groups, transport: hint ? hint.textContent.trim() : null,
        ifaces: document.getElementById('net-consent-ifaces').textContent.trim(),
        caveats: hints,
        cancel: document.getElementById('net-consent-cancel').textContent.trim(),
        ok: document.getElementById('net-consent-ok').textContent.trim(),
        innerText: d.innerText,
        rect: (() => { const r = d.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })(),
      };
    }""")


def tip_state(pg):
    return pg.evaluate("""() => {
      const t = document.getElementById('oo-tip');
      if (!t) return null;
      const r = t.getBoundingClientRect(); const cs = getComputedStyle(t);
      return {text: t.textContent, shown: t.classList.contains('show'), opacity: cs.opacity,
              parent: t.parentElement ? t.parentElement.tagName : null,
              inDialog: !!t.closest('dialog'),
              rect: {x: r.x, y: r.y, w: r.width, h: r.height}};
    }""")


def clip_arr(path, rect, vw, vh):
    im = Image.open(path).convert("RGB")
    x0, y0 = max(0, int(rect["x"])), max(0, int(rect["y"]))
    x1, y1 = min(vw, int(rect["x"] + rect["w"])), min(vh, int(rect["y"] + rect["h"]))
    if x1 <= x0 or y1 <= y0:
        return None
    return np.asarray(im.crop((x0, y0, x1, y1))).astype(int)


def pixel_diff(path_on, path_off, rect, vw, vh):
    a, b = clip_arr(path_on, rect, vw, vh), clip_arr(path_off, rect, vw, vh)
    if a is None or b is None:
        return None
    diff = np.abs(a - b).sum(axis=2)
    return {"changed_px": int((diff > 30).sum()), "total_px": int(diff.size),
            "changed_ratio": round(float((diff > 30).sum()) / max(1, diff.size), 4)}


def dump(obj, name):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
