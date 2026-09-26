"""Shared helpers for the row-N walk (Playwright sync)."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

OUT = Path("/tmp/claude-0/walk/N")
SHOTS = OUT / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
URL = os.environ.get("OO_WALK_URL", "http://127.0.0.1:8830")
PASS = "walk-pass-2026"
CHROME = "/opt/pw-browsers/chromium"

JUNK_RE = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")


class Recorder:
    def __init__(self, name: str):
        self.name = name
        self.page_errors: list[str] = []
        self.console_errors: list[str] = []
        self.http_errors: list[str] = []
        self.junk: list[str] = []
        self.data: dict = {}

    def attach(self, page, tag=""):
        page.on("pageerror", lambda e: self.page_errors.append(f"{tag} {page.url} :: {str(e)[:300]}"))
        page.on("console", lambda m: self.console_errors.append(f"{tag} {page.url} :: {m.text[:300]}") if m.type == "error" else None)
        page.on("response", lambda r: self.http_errors.append(f"{tag} {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

    def attach_context(self, ctx, tag=""):
        for p in ctx.pages:
            self.attach(p, tag)
        ctx.on("page", lambda p: self.attach(p, tag + "[popup]"))

    def junk_scan(self, page, selector: str, label: str):
        try:
            txt = page.eval_on_selector(selector, "e => e.innerText") or ""
        except Exception:
            return
        for m in JUNK_RE.finditer(txt):
            s = txt[max(0, m.start() - 60): m.end() + 60].replace("\n", " ")
            self.junk.append(f"{label} [{selector}]: …{s}…")

    def save(self):
        (OUT / f"rec-{self.name}.json").write_text(json.dumps({
            "page_errors": self.page_errors, "console_errors": self.console_errors,
            "http_errors": self.http_errors, "junk": self.junk, "data": self.data,
        }, ensure_ascii=False, indent=1))


def launch(p, headless=True):
    exe = CHROME if os.path.exists(CHROME) else None
    return p.chromium.launch(executable_path=exe, headless=headless)


def shot(page, name, full=False):
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    return str(path)


def unlock_if_locked(page):
    page.goto(URL + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if page.query_selector("#pw") and page.is_visible("#pw"):
        page.fill("#pw", PASS)
        page.click("#btn-unlock")
        page.wait_for_url(re.compile(r".*#home.*|.*/$"), timeout=60000)
        page.wait_for_timeout(4000)
        return True
    return False


def close_dialogs(page):
    """Close unrelated first-run dialogs (guide wizard, terms) without touching state."""
    page.wait_for_timeout(500)
    for _ in range(3):
        closed = page.evaluate("""() => {
          const out = [];
          for (const d of document.querySelectorAll('dialog[open]')) {
            if (d.id === 'guide-wizard') { try { d.close(); out.push(d.id); } catch (e) {} }
          }
          return out; }""")
        if not closed:
            break
    return True


def set_lang(page, code):
    page.click("#lang-switch")
    page.wait_for_selector("#lang-menu:not([hidden])", timeout=5000)
    page.click(f"#lang-menu [data-lang={code}]")
    page.wait_for_function("c => document.documentElement.lang === c", arg=code, timeout=15000)
    page.wait_for_timeout(1200)


def open_palette_type(page, text):
    if not page.evaluate("() => document.getElementById('palette').classList.contains('open')"):
        page.click(".omni")
    page.wait_for_selector("#pal-input", state="visible", timeout=5000)
    page.fill("#pal-input", "")
    page.type("#pal-input", text, delay=30)
    page.wait_for_timeout(900)


def palette_rows(page):
    return page.eval_on_selector_all(".pal-item", "els => els.map(e => e.innerText.trim())")


def click_palette_row(page, starts_with_any):
    rows = page.query_selector_all(".pal-item")
    for r in rows:
        t = r.inner_text().strip()
        for s in starts_with_any:
            if t.startswith(s):
                r.click()
                return t
    return None


def open_analysis_new_tab(ctx, page, term, analysis_label="Analysis"):
    open_palette_type(page, term)
    with ctx.expect_page(timeout=20000) as pinfo:
        row = click_palette_row(page, [f"{analysis_label}: “{term}”", f"{analysis_label} : “{term}”", f"{analysis_label}：“{term}”"])
        if row is None:
            raise RuntimeError(f"no analysis row: {palette_rows(page)}")
    ap = pinfo.value
    ap.wait_for_load_state("domcontentloaded")
    ap.wait_for_timeout(2500)
    dismiss_coach(ap)
    return ap


def dismiss_coach(pg):
    """The airplane-mode coachmark: press its own 'Not now' (it POSTs nothing)."""
    try:
        if pg.is_visible("#net-coach-dismiss"):
            pg.click("#net-coach-dismiss")
            pg.wait_for_timeout(300)
            return True
    except Exception:
        pass
    return False


def select_subtab(ap, tab):
    ap.click(f"#an-subtabs [data-tab={tab}]")
    ap.wait_for_timeout(1500)


def wait_art_total(ap, timeout=30000):
    ap.wait_for_selector("#an-art-total b", timeout=timeout)
    ap.wait_for_timeout(600)
    return ap.evaluate("""() => { const h = document.querySelector('#an-art-total b');
      if (!h) return null; const m = h.textContent.replace(/[\\s\\u00a0\\u202f,.\\u066c]/g,'').match(/\\d+/);
      return m ? Number(m[0]) : null; }""")


def text(ap, sel):
    try:
        return ap.eval_on_selector(sel, "e => e.innerText.trim()")
    except Exception:
        return None


RACES = []


def ensure_term(ap, term, lg, where):
    """Detect the stale-render race (another analysis tab's result painted under this
    tab) and recover with a real click on this tab in the strip."""
    ap.click("#an-subtabs [data-tab=articles]")
    ap.wait_for_timeout(1200)
    try:
        wait_art_total(ap)
    except Exception:
        pass
    ap.wait_for_timeout(3500)
    x = (text(ap, "#an-xlang") or "")
    if x.startswith(term) or (not x and term not in ("climate", "climat", "election")):
        return True
    ev = {"lg": lg, "where": where, "term": term, "url": ap.url, "xlang_head": x[:90],
          "query_label": text(ap, "#an-query"), "total": wait_art_total(ap),
          "strip": ap.eval_on_selector_all(".an-tab", "e=>e.map(t=>[t.innerText.trim().split('\\n')[0], t.className])")}
    ev["shot"] = shot(ap, f"N-race-{lg}-{where}")
    tab = ap.locator(".an-tab").filter(has_text=re.compile(r"^\s*" + re.escape(term) + r"\b"))
    if tab.count():
        tab.first.click()
        ap.wait_for_timeout(1500)
        ap.click("#an-subtabs [data-tab=articles]")
        ap.wait_for_timeout(1500)
        wait_art_total(ap)
        ap.wait_for_timeout(2500)
    x2 = text(ap, "#an-xlang") or ""
    ev["after_strip_click_xlang_head"] = x2[:90]
    ev["after_strip_click_url"] = ap.url
    ev["after_strip_click_total"] = wait_art_total(ap)
    RACES.append(ev)
    return x2.startswith(term)


