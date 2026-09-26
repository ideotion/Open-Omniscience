"""Shared harness for the row-L walk (scratch only)."""
import json
import os
import re
import time
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

BASE = os.environ.get("WALK_BASE", "http://127.0.0.1:8824")
OUT = "/tmp/claude-0/walk/L-recheck"
PASS = "walk-pass-2026"
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")


class Rec:
    def __init__(self, name):
        self.name = name
        self.page_errors, self.console_errors, self.http_errors = [], [], []
        self.junk, self.notes, self.obs = [], [], {}

    def attach(self, page):
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:400]))
        page.on("console", lambda m: self.console_errors.append(m.text[:400]) if m.type == "error" else None)
        page.on("response", lambda r: self.http_errors.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

    def save(self):
        with open(f"{OUT}/res-{self.name}.json", "w") as f:
            json.dump({"page_errors": self.page_errors, "console_errors": self.console_errors,
                       "http_errors": self.http_errors, "junk": self.junk, "notes": self.notes,
                       "obs": self.obs}, f, indent=1, ensure_ascii=False)


@contextmanager
def session(name, width=1440, height=950, lang=None):
    rec = Rec(name)
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
                               if os.path.exists("/opt/pw-browsers/chromium-1194/chrome-linux/chrome") else None)
        ctx = br.new_context(viewport={"width": width, "height": height}, accept_downloads=True,
                             locale="en-US")
        if lang:
            ctx.add_init_script(f"try{{localStorage.setItem('oo.lang','{lang}')}}catch(e){{}}")
        page = ctx.new_page()
        rec.attach(page)
        try:
            enter(page, rec)
            yield page, rec
        finally:
            rec.save()
            ctx.close()
            br.close()


def enter(page, rec):
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if page.locator("#view-unlock").count() and page.locator("#view-unlock").is_visible():
        page.fill("#pw", PASS)
        page.click("#btn-unlock")
        rec.notes.append("unlocked via #pw/#btn-unlock")
    page.wait_for_function("() => location.hash.startsWith('#home') || !!document.querySelector('#navGroups')",
                           timeout=120000)
    page.wait_for_selector("#navGroups .nav-item", timeout=60000)
    page.wait_for_timeout(1500)
    close_guide(page)


def close_guide(page):
    try:
        b = page.locator("#net-coach-dismiss")
        if b.count() and b.is_visible():
            b.click()
            page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        if page.locator("#guide-wizard[open]").count():
            page.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    except Exception:
        pass
    # any other modal dialog left open (net coach etc.)
    try:
        page.evaluate("""() => document.querySelectorAll('dialog[open]').forEach(d => {
            if (d.id !== 'net-consent') d.close(); })""")
    except Exception:
        pass


def tab(page, t):
    close_guide(page)
    if t == "settings":
        page.click("button[onclick=\"showTab('settings')\"]")
    else:
        page.click(f"#navGroups .nav-item[data-tab='{t}']")
    page.wait_for_timeout(1200)


def sub(page, nav, t):
    close_guide(page)
    page.click(f"#{nav} button[data-tab='{t}']")
    page.wait_for_timeout(1200)


def tip(page, loc, tries=3):
    """Hover a locator, return the #oo-tip bubble text (or None)."""
    for i in range(tries):
        try:
            page.mouse.move(2, 2)
            page.wait_for_timeout(150)
            loc.scroll_into_view_if_needed(timeout=5000)
            loc.hover(timeout=5000)
            page.wait_for_timeout(250 + 250 * i)
            if page.locator("#oo-tip.show").count():
                return page.locator("#oo-tip").inner_text().strip()
        except Exception as e:  # noqa: BLE001
            last = str(e)
    return None


def set_lang(page, code):
    page.click("#lang-switch")
    page.wait_for_selector("#lang-menu:not([hidden])", timeout=5000)
    page.click(f"#lang-menu [data-lang='{code}']")
    page.wait_for_function(f"() => document.documentElement.lang === '{code}'", timeout=15000)
    page.wait_for_timeout(1500)


def junk_scan(page, rec, sel, label):
    try:
        txt = page.locator(sel).first.inner_text(timeout=5000)
    except Exception:
        return
    for m in JUNK.finditer(txt):
        s = txt[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")
        rec.junk.append(f"{label}: …{s}…")


def shot(page, name, full=False):
    page.screenshot(path=f"{OUT}/{name}.png", full_page=full)


def cells(page, sel):
    """For each element: text, title (or data-oo-tip), class."""
    return page.eval_on_selector_all(sel, """els => els.map(e => ({
        text: (e.innerText||'').trim(), title: e.getAttribute('title') || e.dataset.ooTip || null,
        tip: e.classList.contains('oo-tip-target'),
        deco: getComputedStyle(e).textDecorationStyle + ' ' + getComputedStyle(e).textDecorationLine}))""")
