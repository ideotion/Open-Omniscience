"""Shared helpers for the row-O walk (Playwright sync API). Nothing here calls app functions
to fake a click; page.evaluate is used only to READ the DOM / loopback API, and to close the
unrelated first-run guide."""
import json
import os
import re

OUT = "/tmp/claude-0/walk/O-recheck"
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]")
CHROMIUM = "/opt/pw-browsers/chromium"


class Rec:
    """Records every page error, console error and HTTP >= 400 for the whole run."""

    def __init__(self):
        self.page_errors, self.console_errors, self.http = [], [], []

    def watch(self, pg, tag=""):
        pg.on("pageerror", lambda e: self.page_errors.append(f"[{tag}] {e}"))
        pg.on("console", lambda m: self.console_errors.append(f"[{tag}] {m.text[:300]}")
              if m.type == "error" else None)
        pg.on("response", lambda r: self.http.append(f"[{tag}] {r.status} {r.request.method} {r.url}")
              if r.status >= 400 else None)


def save(name, data):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def shot(pg, name, full=False):
    pg.screenshot(path=os.path.join(OUT, name), full_page=full)


def txt(pg, sel):
    return pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : null; }", sel)


def api(pg, path, method="GET", body=None):
    return pg.evaluate(
        """([p, m, b]) => fetch(p, {method: m, headers: {'Content-Type': 'application/json'},
              body: b === null ? undefined : JSON.stringify(b)}).then(async r => ({status: r.status, body: await r.text()}))""",
        [path, method, body],
    )


def junk(pg, sel):
    body = pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : ''; }", sel) or ""
    return sorted(set(m.group(0) for m in JUNK.finditer(body)))


def close_guide(pg):
    """The first-run guide is not under test: close it with its own x button when open."""
    try:
        if pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }"):
            pg.click("#gw-close", timeout=3000)
            pg.wait_for_timeout(300)
    except Exception:
        pg.evaluate("() => { const d = document.getElementById('guide-wizard'); if (d && d.open) d.close(); }")
    pg.wait_for_timeout(100)


def unlock(pg, base, passphrase, wrong=None):
    """The real unlock page: language/legal steps if shown, then #pw -> #btn-unlock."""
    out = {}
    pg.goto(base + "/", wait_until="domcontentloaded", timeout=60000)
    try:
        pg.wait_for_selector("#view-language:visible, #view-legal:visible, #view-unlock:visible, "
                             "#view-create:visible, #view-open:visible", timeout=15000)
    except Exception as exc:
        out["first_view_error"] = str(exc)[:200]
    pg.wait_for_timeout(400)
    if pg.is_visible("#view-language"):
        out["language_step"] = True
        pg.click(".lang-btn")
        pg.wait_for_timeout(600)
    if pg.is_visible("#view-legal"):
        out["legal_step"] = True
        pg.check("#lg-check")
        pg.click("#lg-accept")
        pg.wait_for_timeout(800)
    if pg.is_visible("#view-datadir"):
        out["datadir_step"] = True
        pg.click("#dl-continue")
        pg.wait_for_timeout(800)
    out["unlock_visible"] = pg.is_visible("#view-unlock")
    if wrong is not None:
        pg.fill("#pw", wrong)
        pg.click("#btn-unlock")
        pg.wait_for_timeout(3500)
        out["wrong_msg"] = txt(pg, "#msg")
        out["wrong_msg_visible"] = pg.is_visible("#msg")
        out["url_after_wrong"] = pg.url
        out["still_unlock_view"] = pg.is_visible("#view-unlock")
        shot(pg, "O-O15-wrong-passphrase-en.png")
    pg.fill("#pw", passphrase)
    pg.click("#btn-unlock")
    pg.wait_for_url(re.compile(r".*/#home.*|.*/(\?.*)?$"), timeout=90000)
    pg.wait_for_load_state("networkidle", timeout=60000)
    pg.wait_for_timeout(1500)
    out["url_after_unlock"] = pg.url
    return out


def switch_lang(pg, loc, rec):
    for attempt in (1, 2, 3):
        close_guide(pg)
        pg.keyboard.press("Escape")
        pg.mouse.move(2, 2)
        pg.wait_for_timeout(500)
        try:
            pg.click("#lang-switch", timeout=6000)
            pg.wait_for_selector(f"#lang-menu [data-lang='{loc}']", state="visible", timeout=6000)
            pg.click(f"#lang-menu [data-lang='{loc}']", timeout=6000)
            pg.wait_for_function("(l) => document.documentElement.lang === l", arg=loc, timeout=8000)
            pg.wait_for_timeout(900)
            return True
        except Exception as exc:
            if attempt == 3:
                rec.console_errors.append(f"[harness] switcher {loc}: {str(exc)[:160]}")
    return False


def tip_of(pg, locator, wait=750):
    """Hover a real element and read the ONE shared bubble (#oo-tip); fall back to the
    attribute only when the bubble did not show, and say which."""
    locator.scroll_into_view_if_needed(timeout=5000)
    locator.hover(timeout=5000)
    pg.wait_for_timeout(wait)
    shown = pg.evaluate("() => { const t = document.getElementById('oo-tip'); "
                        "return t && t.classList.contains('show') ? t.textContent.trim() : null; }")
    if shown:
        return shown
    attr = locator.evaluate("e => e.getAttribute('title') || e.dataset.ooTip || null")
    return f"[attr, bubble not shown] {attr}" if attr else None


def unhover(pg):
    pg.mouse.move(2, 2)
    pg.wait_for_timeout(250)


COACH_BLOCKS = []


def clear_coach_if_blocking(pg, sel, where=""):
    """If the offline coach sits over the control a user needs, record it (a finding) and
    dismiss the coach through its own real 'Not now' button, as a user would."""
    hit = pg.evaluate("""(s) => { const b = document.querySelector(s); const c = document.getElementById('net-coach');
        if (!b || !c) return false; const r = b.getBoundingClientRect(); if (!r.width) return false;
        const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return !!h && c.contains(h); }""", sel)
    if hit:
        COACH_BLOCKS.append({"control": sel, "where": where, "lang": pg.evaluate("() => document.documentElement.lang"),
                             "viewport": pg.viewport_size})
        try:
            slug = re.sub(r"[^a-z0-9]+", "-", sel.lower()).strip("-")[:40]
            pg.screenshot(path=f"{OUT}/O-coach-covers-{slug}-{pg.evaluate('() => document.documentElement.lang')}.png")
        except Exception:
            pass
        pg.click("#net-coach-dismiss")
        pg.wait_for_timeout(500)
    return hit


def nav(pg, tab):
    close_guide(pg)
    sel = ".sb-foot button.secondary" if tab == "settings" else f".nav-item[data-tab='{tab}']"
    onscreen = pg.evaluate("(s) => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.left >= 0 && r.right <= innerWidth; }", sel)
    if not onscreen:
        # narrow: the sidebar hides behind the Menu button
        if pg.is_visible("#hamburger"):
            pg.click("#hamburger")
            pg.wait_for_timeout(500)
    clear_coach_if_blocking(pg, sel, "nav")
    pg.click(sel)
    pg.wait_for_timeout(900)


def settings_sub(pg, sub):
    nav(pg, "settings")
    clear_coach_if_blocking(pg, f"#set-subtabs button[data-tab='{sub}']", "settings subtab")
    pg.click(f"#set-subtabs button[data-tab='{sub}']")
    pg.wait_for_function("(s) => { const e = document.getElementById('set-' + s); return e && e.style.display !== 'none'; }",
                         arg=sub, timeout=10000)
    pg.wait_for_timeout(900)


def storage_ready(pg):
    pg.wait_for_function("() => document.querySelectorAll('#storage-lanes tbody tr').length >= 4", timeout=20000)
    pg.wait_for_timeout(500)


def living_open(pg):
    nav(pg, "living")
    pg.wait_for_function("() => /\\S/.test((document.getElementById('living-wiki-facts') || {}).innerText || '')",
                         timeout=20000)
    pg.wait_for_function("() => /\\S/.test((document.getElementById('living-stream') || {}).innerText || '') && "
                         "!/Loading|Chargement|جارٍ|加载/.test(document.getElementById('living-stream').innerText)",
                         timeout=20000)
    pg.wait_for_timeout(700)


def living_sub(pg, kind):
    clear_coach_if_blocking(pg, f"#living-subtabs button[data-tab='{kind}']", "living subtab")
    pg.click(f"#living-subtabs button[data-tab='{kind}']")
    pg.wait_for_function("(k) => { const e = document.getElementById('living-' + k); "
                         "return e && e.style.display !== 'none' && /\\S/.test(e.innerText); }", arg=kind, timeout=10000)
    pg.wait_for_timeout(1200)


def open_consent(pg):
    close_guide(pg)
    clear_coach_if_blocking(pg, "#net-toggle", "plane")
    pg.click("#net-toggle")
    pg.wait_for_function(
        "() => document.getElementById('net-consent').open && "
        "document.querySelectorAll('#net-consent-lanes span[title], #net-consent-lanes span[data-oo-tip]').length > 3",
        timeout=15000)
    pg.wait_for_timeout(500)


def consent_lanes(pg, hover=True, limit=None):
    """Every lane line: heading group, label, and the hover as the bubble shows it."""
    structure = pg.evaluate("""() => {
        const box = document.getElementById('net-consent-lanes');
        const out = []; let head = null;
        for (const el of box.children) {
          if (el.classList.contains('muted')) { head = el.textContent.trim(); continue; }
          if (el.classList.contains('hint')) { out.push({hint: el.textContent.trim()}); continue; }
          const s = el.querySelector('span[title], span[data-oo-tip]');
          if (s) out.push({head, label: s.textContent.trim(), attr: s.getAttribute('title') || s.dataset.ooTip});
        }
        return out;
    }""")
    if hover:
        spans = pg.locator("#net-consent-lanes div > span:first-child")
        n = spans.count()
        idx = 0
        for row in structure:
            if "label" not in row:
                continue
            if limit is not None and idx >= limit:
                break
            if idx < n:
                row["tip"] = tip_of(pg, spans.nth(idx), wait=600)
            idx += 1
        unhover(pg)
    return structure
