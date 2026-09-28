# -*- coding: utf-8 -*-
import json, re
from pathlib import Path
OUT = Path("/tmp/claude-0/walk/U-recheck")
SHOTS = OUT / "shots"; SHOTS.mkdir(parents=True, exist_ok=True)
CHROMIUM = "/opt/pw-browsers/chromium"

class Rec:
    def __init__(self, name):
        self.name = name; self.page_errors = []; self.console_errors = []; self.http = []; self.obs = {}; self.dialogs = []
    def attach(self, pg):
        pg.on("pageerror", lambda e: self.page_errors.append(f"{pg.url} :: {e}"))
        pg.on("console", lambda m: self.console_errors.append(m.text[:300]) if m.type == "error" else None)
        pg.on("response", lambda r: self.http.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)
        pg.on("dialog", self._dlg)
    def _dlg(self, d):
        self.dialogs.append({"type": d.type, "message": d.message})
        try: d.accept()
        except Exception: pass
    def note(self, k, v):
        self.obs[k] = v; print(f"[{k}] {json.dumps(v, ensure_ascii=False)[:1200]}", flush=True)
    def save(self):
        (OUT / f"{self.name}.json").write_text(json.dumps({"obs": self.obs, "page_errors": self.page_errors,
            "console_errors": self.console_errors, "http_errors": self.http, "dialogs": self.dialogs}, ensure_ascii=False, indent=1))

def switch_lang(pg, code):
    pg.click("#lang-switch", timeout=15000)
    pg.wait_for_selector(f"#lang-menu [data-lang='{code}']", state="visible", timeout=10000)
    pg.click(f"#lang-menu [data-lang='{code}']", timeout=15000)
    pg.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=15000)
    pg.wait_for_timeout(800)

def hscroll(pg):
    return pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")

def shot(pg, name, full=False):
    p = SHOTS / f"{name}.png"; pg.screenshot(path=str(p), full_page=full); return str(p)

def vis(pg, sel):
    return pg.evaluate("s => { const e = document.querySelector(s); return !!(e && !e.classList.contains('hidden') && (e.offsetParent || e.getClientRects().length)); }", sel)

def unlock(pg, base, pw="walk-pass-2026"):
    pg.goto(base + "/", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(2000)
    if "/unlock" in pg.url:
        pg.wait_for_selector("#view-unlock:not(.hidden)", timeout=30000)
        pg.fill("#pw", pw); pg.click("#btn-unlock")
        pg.wait_for_url("**/#home", timeout=120000)
    pg.wait_for_timeout(2500)

def close_unrelated(pg):
    for sel in ["#wiki-wizard-cancel", "#net-coach-dismiss"]:
        try:
            if pg.is_visible(sel): pg.click(sel, timeout=2000); pg.wait_for_timeout(200)
        except Exception: pass
    pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
