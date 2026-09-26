# -*- coding: utf-8 -*-
"""Shared harness for the row U walk (Chromium via Playwright, sync API)."""
import json, re, time
from pathlib import Path

OUT = Path("/tmp/claude-0/walk/U")
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
CHROMIUM = "/opt/pw-browsers/chromium"
JUNK_RE = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")


class Rec:
    def __init__(self, name):
        self.name = name
        self.page_errors, self.console_errors, self.http_errors = [], [], []
        self.junk, self.obs = [], {}

    def attach(self, pg):
        pg.on("pageerror", lambda e: self.page_errors.append(f"{pg.url} :: {e}"))
        pg.on("console", lambda m: self.console_errors.append(f"{pg.url} :: {m.text[:300]}")
              if m.type == "error" else None)
        pg.on("response", lambda r: self.http_errors.append(f"{r.status} {r.request.method} {r.url}")
              if r.status >= 400 else None)
        pg.on("dialog", lambda d: self._dialog(d))
        self.dialogs = []

    def _dialog(self, d):
        self.dialogs.append({"type": d.type, "message": d.message})
        try:
            d.accept()
        except Exception:
            pass

    def note(self, key, val):
        self.obs[key] = val
        print(f"[{key}] {json.dumps(val, ensure_ascii=False)[:1500]}")

    def junk_scan(self, pg, sel, label):
        try:
            txt = pg.eval_on_selector(sel, "e => e.innerText || ''")
        except Exception:
            return
        for m in JUNK_RE.finditer(txt):
            s = max(0, m.start() - 60)
            self.junk.append(f"{label}: ...{txt[s:m.end()+60]!r}")

    def save(self):
        (OUT / f"{self.name}.json").write_text(json.dumps({
            "obs": self.obs, "page_errors": self.page_errors,
            "console_errors": self.console_errors, "http_errors": self.http_errors,
            "junk": self.junk, "dialogs": getattr(self, "dialogs", []),
        }, ensure_ascii=False, indent=1), encoding="utf-8")


def text_of(pg, sel):
    """textContent + measured visibility (innerText is empty inside closed <details>)."""
    return pg.eval_on_selector(sel, """e => {
        const vis = !!(e.offsetParent || e.getClientRects().length);
        const t = (e.textContent || '').replace(/\\s+/g, ' ').trim();
        return (vis ? '' : '[hidden] ') + t;
    }""")


def switch_lang(pg, code, rec=None):
    pg.click("#lang-switch", timeout=15000)
    pg.wait_for_selector(f"#lang-menu [data-lang='{code}']", state="visible", timeout=10000)
    pg.click(f"#lang-menu [data-lang='{code}']", timeout=15000)
    pg.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=15000)
    pg.wait_for_timeout(1200)
    return pg.evaluate("() => ({lang: document.documentElement.lang, dir: document.documentElement.dir || getComputedStyle(document.body).direction})")


def plane_filled(pg):
    return pg.evaluate("() => { const p = document.getElementById('net-plane'); return p ? p.getAttribute('fill') : 'MISSING'; }")


def sidebar_side(pg):
    return pg.evaluate("""() => { const s = document.getElementById('sidebar'); if (!s) return null;
        const r = s.getBoundingClientRect(); return {left: Math.round(r.left), right: Math.round(r.right), vw: innerWidth,
        side: (r.left + r.right) / 2 > innerWidth / 2 ? 'right' : 'left'}; }""")


def hscroll(pg):
    return pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


def shot(pg, name, full=False):
    p = SHOTS / f"{name}.png"
    pg.screenshot(path=str(p), full_page=full)
    return str(p)


def close_unrelated_dialogs(pg):
    # Close the first-run guide / wiki wizard / coachmark via their own buttons when visible.
    for sel in ["#wiki-wizard-cancel", "#net-coach-dismiss"]:
        try:
            if pg.is_visible(sel):
                pg.click(sel, timeout=3000)
                pg.wait_for_timeout(300)
        except Exception:
            pass
    try:
        if pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
            pg.evaluate("() => document.getElementById('guide-wizard').close()")
    except Exception:
        pass
