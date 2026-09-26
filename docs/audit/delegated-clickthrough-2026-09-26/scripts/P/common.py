"""Shared helpers for the Row P walk (Playwright sync API)."""
from __future__ import annotations

import json
import re
import time

OUT = "/tmp/claude-0/walk/P"
PASS = "walk-pass-2026"
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")
EXE = "/opt/pw-browsers/chromium"


class Rec:
    def __init__(self, tag):
        self.tag = tag
        self.page_errors: list[str] = []
        self.console_errors: list[str] = []
        self.http: list[str] = []
        self.dialogs: list[str] = []
        self.toasts: list[str] = []

    def attach(self, page, dialog_policy="dismiss"):
        tag = self.tag
        page.on("pageerror", lambda e: self.page_errors.append(f"[{tag}] {page.url} :: {e}"))
        page.on("console", lambda m: self.console_errors.append(f"[{tag}] {m.text[:300]}") if m.type == "error" else None)
        page.on("response", lambda r: self.http.append(f"[{tag}] {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

        def _dlg(d):
            self.dialogs.append(f"[{tag}] {d.type}: {d.message[:400]}")
            if dialog_policy == "accept":
                d.accept()
            else:
                d.dismiss()
        page.on("dialog", _dlg)

    def dump(self):
        return {"page_errors": self.page_errors, "console_errors": self.console_errors,
                "http": self.http, "dialogs": self.dialogs}


def junk_in(text: str | None):
    if not text:
        return []
    return sorted(set(m.group(0) for m in JUNK.finditer(text)))


def shot(page, name, full=False, clip_sel=None):
    path = f"{OUT}/P-{name}.png"
    if clip_sel:
        el = page.query_selector(clip_sel)
        b = el.bounding_box() if el else None
        if b:
            page.screenshot(path=path, clip={"x": max(0, b["x"] - 6), "y": max(0, b["y"] - 6),
                                             "width": min(b["width"] + 12, page.viewport_size["width"]),
                                             "height": b["height"] + 12})
            return path
    page.screenshot(path=path, full_page=full)
    return path


def text(page, sel):
    return page.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : null; }", sel)


def attr(page, sel, a):
    return page.evaluate("([s, a]) => { const e = document.querySelector(s); return e ? e.getAttribute(a) : null; }", [sel, a])


def tip(page, sel, wait=500, locator=None):
    """Hover an element for real and read the shared #oo-tip bubble."""
    page.mouse.move(2, 400)
    page.wait_for_timeout(150)
    if locator is not None:
        locator.hover()
    else:
        page.hover(sel)
    page.wait_for_timeout(wait)
    return page.evaluate("""() => { const t = document.getElementById('oo-tip');
        if (!t) return {shown:false, text:null};
        const r = t.getBoundingClientRect();
        let top = null;
        if (t.classList.contains('show')) {
          const e = document.elementFromPoint(r.left + Math.min(20, r.width/2), r.top + Math.min(10, r.height/2));
          top = e ? (e.id || e.tagName) + (e.closest('dialog') ? ' in dialog#' + e.closest('dialog').id : '') : null;
        }
        return {shown: t.classList.contains('show'), text: t.textContent,
                rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
                topmost_at_tip: top}; }""")


def boxes(page, sels):
    out = {}
    for s in sels:
        el = page.query_selector(s)
        b = el.bounding_box() if el else None
        out[s] = [round(b["x"], 1), round(b["y"], 1), round(b["width"], 1), round(b["height"], 1)] if b else None
    return out


TOPBAR = ["#rate-toggle", "#wiki-toggle", "#net-toggle", "#lang-switch",
          "button[onclick=\"showTab('help')\"]", "#app-shutdown"]


def wstate(page):
    return page.evaluate("""() => { const b = document.getElementById('wiki-toggle');
      const m = document.getElementById('wiki-mark'); const cs = getComputedStyle(b);
      const ms = getComputedStyle(m);
      return {cls: b.className, fill: m.getAttribute('fill'), aria_pressed: b.getAttribute('aria-pressed'),
              aria_label: b.getAttribute('aria-label'), title: b.getAttribute('title') || b.dataset.ooTip,
              title_attr: b.getAttribute('title'), ooTip: b.dataset.ooTip || null,
              color: cs.color, opacity: cs.opacity, box_shadow: cs.boxShadow, animation: cs.animationName + ' ' + cs.animationDuration,
              mark_transition: ms.transition, mark_fill_computed: ms.fill,
              w: b.getBoundingClientRect().width, h: b.getBoundingClientRect().height}; }""")


def plane_filled(page):
    return attr(page, "#net-plane", "fill") == "currentColor"


def close_guide(page):
    for _ in range(3):
        is_open = page.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }")
        if not is_open:
            return
        try:
            page.click("#gw-close", timeout=3000)
        except Exception:
            page.keyboard.press("Escape")
        page.wait_for_timeout(400)


def dismiss_coach(page):
    try:
        vis = page.is_visible("#net-coach-dismiss")
    except Exception:
        vis = False
    if vis:
        page.click("#net-coach-dismiss")
        page.wait_for_timeout(300)
        return True
    return False


TOAST_INIT = """
window.__toasts = [];
document.addEventListener('DOMContentLoaded', () => {
  const box = document.getElementById('toast');
  if (!box) return;
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
    if (n.nodeType === 1) window.__toasts.push({t: Date.now(), cls: n.className, text: n.textContent});
  }))).observe(box, {childList: true});
});
"""


def toasts_since(page, t0):
    return page.evaluate("(t0) => (window.__toasts || []).filter(x => x.t >= t0).map(x => x.cls + ' :: ' + x.text)", t0)


def jsnow(page):
    return page.evaluate("() => Date.now()")


def switch_lang(page, loc, rec):
    for attempt in (1, 2, 3):
        page.keyboard.press("Escape")
        page.mouse.move(2, 400)
        page.wait_for_timeout(400)
        try:
            page.click("#lang-switch", timeout=6000)
            page.wait_for_selector(f"#lang-menu [data-lang='{loc}']", state="visible", timeout=6000)
            page.click(f"#lang-menu [data-lang='{loc}']", timeout=6000)
            page.wait_for_function("(l) => document.documentElement.lang === l", arg=loc, timeout=8000)
            page.wait_for_timeout(900)
            return True
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                rec.console_errors.append(f"HARNESS switcher {loc}: {str(exc)[:160]}")
    return False


def settings_sub(page, tab):
    page.click("button[onclick=\"showTab('settings')\"]")
    page.wait_for_timeout(500)
    page.click(f"#set-subtabs button[data-tab='{tab}']")
    page.wait_for_timeout(900)


def save(name, data):
    with open(f"{OUT}/{name}", "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def now():
    return time.strftime("%H:%M:%S")
