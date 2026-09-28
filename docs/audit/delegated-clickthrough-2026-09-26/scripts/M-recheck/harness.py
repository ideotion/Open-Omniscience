"""Shared Playwright harness for the row-M walk (scratch only, never in the repo)."""
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

OUT = "/tmp/claude-0/walk/M-recheck"
JUNK_RE = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")

LOG = {"page_errors": [], "console_errors": [], "http_errors": [], "requests_offhost": []}


def log_path(name):
    return os.path.join(OUT, name)


def attach(page, tag=""):
    page.on("pageerror", lambda e: LOG["page_errors"].append(f"{tag} {page.url} :: {e}"))
    page.on("console", lambda m: LOG["console_errors"].append(f"{tag} {page.url} :: {m.text}")
            if m.type == "error" else None)

    def _resp(r):
        try:
            if r.status >= 400:
                LOG["http_errors"].append(f"{tag} {r.status} {r.request.method} {r.url}")
        except Exception:
            pass
    page.on("response", _resp)

    def _req(r):
        u = r.url
        if not (u.startswith("http://127.0.0.1") or u.startswith("http://localhost")
                or u.startswith("data:") or u.startswith("blob:") or u.startswith("about:")):
            LOG["requests_offhost"].append(f"{tag} {r.method} {u}")
    page.on("request", _req)


def dump_log(name):
    with open(log_path(name), "w") as f:
        json.dump(LOG, f, indent=1, ensure_ascii=False)


def browser_ctx(p, width=1440, height=950):
    b = p.chromium.launch(headless=True, executable_path="/opt/pw-browsers/chromium", args=["--no-proxy-server"])
    ctx = b.new_context(viewport={"width": width, "height": height})
    return b, ctx


def unlock_if_needed(page, base, pw="walk-pass-2026"):
    page.goto(base + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if page.locator("#pw").count() and page.locator("#pw").is_visible():
        page.fill("#pw", pw)
        page.click("#btn-unlock")
        page.wait_for_url(re.compile(r".*#home.*|.*/$"), timeout=60000)
        page.wait_for_timeout(3000)
        return True
    return False


def close_guide(page):
    try:
        page.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    except Exception:
        pass


def set_lang(page, code):
    page.click("#lang-switch")
    page.wait_for_timeout(300)
    page.click(f"#lang-menu [data-lang={code}]")
    page.wait_for_function(f"document.documentElement.lang === '{code}'", timeout=15000)
    page.wait_for_timeout(1500)


def goto_tab(page, tab):
    dismiss_coach(page)
    page.click(f"#navGroups [data-tab={tab}]")
    page.wait_for_timeout(1200)


def open_settings_advanced(page):
    dismiss_coach(page)
    page.click(".sb-foot button.secondary")
    page.wait_for_timeout(500)
    dismiss_coach(page)
    page.wait_for_timeout(800)
    page.click("#set-subtabs [data-tab=advanced]")
    page.wait_for_timeout(800)


def open_adv(page, key):
    s = page.locator(f"details.adv-sec[data-adv={key}] > summary")
    s.scroll_into_view_if_needed()
    is_open = page.evaluate(f"() => document.querySelector('details.adv-sec[data-adv={key}]').open")
    if not is_open:
        s.click()
    page.wait_for_timeout(1200)


def junk_in(page, selector):
    txt = page.evaluate(f"() => {{ const e = document.querySelector({json.dumps(selector)}); return e ? e.innerText : ''; }}")
    return sorted(set(m.group(0) for m in JUNK_RE.finditer(txt or "")))


def shot(page, name, full=False, selector=None):
    path = log_path(name)
    if selector:
        page.locator(selector).first.screenshot(path=path)
    else:
        page.screenshot(path=path, full_page=full)
    return path


def dismiss_coach(page):
    try:
        if page.locator("#net-coach.show").count() and page.locator("#net-coach-dismiss").is_visible():
            page.click("#net-coach-dismiss")
            page.wait_for_timeout(400)
            return True
    except Exception:
        pass
    return False
