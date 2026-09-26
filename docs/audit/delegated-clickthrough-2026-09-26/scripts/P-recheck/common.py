"""Shared helpers for the Row P recheck (Playwright sync API)."""
from __future__ import annotations

import json

OUT = "/tmp/claude-0/walk/P-recheck"
PASS = "walk-pass-2026"
EXE = "/opt/pw-browsers/chromium"
ARGS = ["--no-sandbox", "--disable-background-networking", "--disable-component-update",
        "--no-proxy-server"]


class Rec:
    def __init__(self, tag):
        self.tag = tag
        self.page_errors, self.console_errors, self.http, self.dialogs = [], [], [], []

    def attach(self, page, dialog_policy="dismiss"):
        tag = self.tag
        page.on("pageerror", lambda e: self.page_errors.append(f"[{tag}] {e}"))
        page.on("console", lambda m: self.console_errors.append(f"[{tag}] {m.text[:300]}") if m.type == "error" else None)
        page.on("response", lambda r: self.http.append(f"[{tag}] {r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

        def _dlg(d):
            self.dialogs.append({"tag": tag, "type": d.type, "message": d.message})
            d.dismiss()
        page.on("dialog", _dlg)

    def dump(self):
        return {"page_errors": self.page_errors, "console_errors": self.console_errors,
                "http": self.http, "dialogs": self.dialogs}


def save(name, data):
    with open(f"{OUT}/{name}", "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def shot(page, name, clip_sel=None):
    path = f"{OUT}/P-{name}.png"
    if clip_sel:
        el = page.query_selector(clip_sel)
        b = el.bounding_box() if el else None
        if b:
            vw = page.viewport_size["width"]
            page.screenshot(path=path, clip={"x": max(0, b["x"] - 6), "y": max(0, b["y"] - 6),
                                             "width": min(b["width"] + 12, vw), "height": b["height"] + 12})
            return path
    page.screenshot(path=path)
    return path


TIPSTATE = """() => { const t = document.getElementById('oo-tip'); const r = t.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const pe = t.style.pointerEvents; t.style.pointerEvents = 'auto';
  const top = t.classList.contains('show') ? document.elementFromPoint(cx, cy) : null;
  t.style.pointerEvents = pe;
  return {show: t.classList.contains('show'), opacity: getComputedStyle(t).opacity, text: t.textContent,
          rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)],
          topmost_at_tip_centre: top ? (top.id ? '#' + top.id : top.tagName) + (top.closest('dialog') ? ' (inside dialog#' + top.closest('dialog').id + ')' : '') : null,
          tip_is_topmost: top === t || (top && t.contains(top))}; }"""


def tipstate(page):
    return page.evaluate(TIPSTATE)


def close_guide(page):
    for _ in range(3):
        if not page.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
            return
        try:
            page.click("#gw-close", timeout=3000)
        except Exception:
            page.keyboard.press("Escape")
        page.wait_for_timeout(400)


def dismiss_coach(page):
    try:
        if page.is_visible("#net-coach-dismiss"):
            page.click("#net-coach-dismiss")
            page.wait_for_timeout(300)
    except Exception:
        pass


def switch_lang(page, loc):
    for attempt in (1, 2, 3):
        page.keyboard.press("Escape")
        page.mouse.move(2, 400)
        page.wait_for_timeout(400)
        try:
            page.click("#lang-switch", timeout=6000)
            page.wait_for_selector(f"#lang-menu [data-lang='{loc}']", state="visible", timeout=6000)
            page.click(f"#lang-menu [data-lang='{loc}']", timeout=6000)
            page.wait_for_function("(l) => document.documentElement.lang === l", arg=loc, timeout=8000)
            page.wait_for_timeout(1200)
            return True
        except Exception:
            if attempt == 3:
                raise
    return False


TOAST_INIT = """
window.__toasts = [];
document.addEventListener('DOMContentLoaded', () => {
  const box = document.getElementById('toast');
  if (!box) return;
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
    if (n.nodeType === 1) window.__toasts.push(n.textContent);
  }))).observe(box, {childList: true});
});
"""


def wread(page):
    return page.evaluate("""() => { const b = document.getElementById('wiki-toggle');
      return {cls: b.className, fill: document.getElementById('wiki-mark').getAttribute('fill'),
              title_attr: b.getAttribute('title'), dataset_ooTip: b.dataset.ooTip || null,
              aria_label: b.getAttribute('aria-label')}; }""")


def centre(page, sel):
    b = page.locator(sel).first.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
