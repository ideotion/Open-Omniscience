# -*- coding: utf-8 -*-
"""Row U main walk on the unlocked encrypted seeded instance (8850): U3, U5, U6, U7, U9."""
import sys, traceback, re
from playwright.sync_api import sync_playwright
from common import *

BASE = "http://127.0.0.1:8850"
STEPS = sys.argv[1:] or ["U3", "U5", "U6", "U7", "U9"]
rec = Rec("main_" + "_".join(STEPS))
ALL12 = ["en", "fr", "es", "de", "zh", "hi", "ar", "bn", "ru", "pt", "id", "ja"]
NNBSP = " "


def dismiss_coach(pg):
    try:
        if pg.is_visible("#net-coach-dismiss"):
            pg.click("#net-coach-dismiss", timeout=3000)   # 'Not now' -- stays offline
            pg.wait_for_timeout(300)
            rec.obs.setdefault("coach_dismissed", 0)
            rec.obs["coach_dismissed"] += 1
    except Exception:
        pass


def goto_settings(pg, sub):
    dismiss_coach(pg)
    pg.click(".sb-foot button[onclick=\"showTab('settings')\"]")
    pg.wait_for_timeout(600)
    pg.click(f"#set-subtabs [data-tab='{sub}']")
    pg.wait_for_timeout(600)


def open_adv(pg, key):
    goto_settings(pg, "advanced")
    sel = f"#set-advanced details.adv-sec[data-adv='{key}']"
    if not pg.evaluate(f"() => document.querySelector(\"{sel}\").open"):
        pg.click(f"{sel} > summary")
        pg.wait_for_timeout(900)
    return sel


def nav(pg, tab):
    dismiss_coach(pg)
    pg.click(f"#navGroups .nav-item[data-tab='{tab}']")
    pg.wait_for_timeout(900)


def tip_text(pg, sel):
    """Hover a titled element and read the ONE shared bubble (#oo-tip) plus the raw title."""
    pg.hover(sel)
    pg.wait_for_timeout(900)
    tip = pg.evaluate("() => { const t = document.getElementById('oo-tip'); return t ? {vis: !!(t.offsetParent || t.getClientRects().length) && getComputedStyle(t).visibility !== 'hidden' && getComputedStyle(t).opacity !== '0', text: t.textContent} : null; }")
    title = pg.evaluate(f"() => {{ const e = document.querySelector({sel!r}); return e ? (e.getAttribute('title') || e.getAttribute('data-oo-title') || e.dataset.ooTip || '') : null; }}")
    pg.mouse.move(5, 900)
    pg.wait_for_timeout(200)
    return {"tip": tip, "title": title}


def ascii_words(s):
    return re.findall(r"\b[A-Za-z]{4,}\b", s)


# ------------------------------------------------------------------ U3 ------------
def u3(pg):
    sel = open_adv(pg, "diagnostics")
    rec.note("u3.before_press", {"panel": text_of(pg, "#patterns-gate"), "state": text_of(pg, "#patterns-gate-state"),
                                  "cb_checked": pg.is_checked("#patterns-lens"), "cb_disabled": pg.is_disabled("#patterns-lens")})
    rec.note("u3.check_now_buttons_in_fold", pg.eval_on_selector_all(f"{sel} button", "els => els.filter(b => /Check now/.test(b.textContent)).map(b => b.getAttribute('onclick'))"))
    btn = "#set-advanced button[onclick='loadPatternsGate()']"
    pg.locator(btn).scroll_into_view_if_needed()
    pg.click(btn)
    pg.wait_for_function("() => (document.getElementById('patterns-gate').textContent || '').trim().length > 0", timeout=60000)
    pg.wait_for_timeout(500)
    api = pg.evaluate("async () => (await (await fetch('/api/signals/patterns-gate')).json())")
    rec.note("u3.api", api)
    lines = pg.eval_on_selector_all("#patterns-gate > div", "els => els.map(e => ({text: e.textContent.replace(/\\s+/g,' ').trim(), cls: e.className, color: getComputedStyle(e).color}))")
    pills = pg.eval_on_selector_all("#patterns-gate .pill", "els => els.map(e => ({text: e.textContent, cls: e.className, bg: getComputedStyle(e).backgroundColor, color: getComputedStyle(e).color}))")
    rec.note("u3.en.lines", lines)
    rec.note("u3.en.pills", pills)
    rec.note("u3.en.state", text_of(pg, "#patterns-gate-state"))
    raw = pg.evaluate("() => document.getElementById('patterns-gate').textContent")
    rec.note("u3.en.bar_has_nnbsp_100000", ("100" + NNBSP + "000") in raw)
    rec.note("u3.en.has_100,000", "100,000" in raw)
    rec.note("u3.en.has_5_percent", bool(re.search(r"5\s?%", raw)))
    rec.note("u3.en.fp_shows_zero", bool(re.search(r"False-positive rate:\s*0", raw)))
    rec.note("u3.cb_after", {"checked": pg.is_checked("#patterns-lens"), "disabled": pg.is_disabled("#patterns-lens")})
    try:
        pg.click("#patterns-lens", force=True, timeout=3000)
    except Exception as e:
        rec.note("u3.cb_click_err", str(e)[:200])
    pg.wait_for_timeout(300)
    rec.note("u3.cb_after_click", {"checked": pg.is_checked("#patterns-lens"), "disabled": pg.is_disabled("#patterns-lens")})
    pg.locator("#patterns-gate").scroll_into_view_if_needed()
    shot(pg, "U-U3-patterns-gate-en")
    en_label = None
    per = {}
    for code in ALL12[1:] + ["en"]:
        r = switch_lang(pg, code)
        pg.wait_for_timeout(400)
        raw = pg.evaluate("() => document.getElementById('patterns-gate').textContent")
        label = pg.evaluate("() => { const s = document.querySelector('#patterns-gate > div:first-child > span'); return s ? s.textContent : null; }")
        per[code] = {"dir": r["dir"], "label": label,
                     "text": pg.evaluate("() => document.getElementById('patterns-gate').innerText"),
                     "state": text_of(pg, "#patterns-gate-state"),
                     "nnbsp_100000": ("100" + NNBSP + "000") in raw, "comma": "100,000" in raw,
                     "percent5": bool(re.search(r"5\s?%", raw)),
                     "panel_dir": pg.evaluate("() => getComputedStyle(document.getElementById('patterns-gate')).direction"),
                     "cb_disabled": pg.is_disabled("#patterns-lens")}
        if code in ("fr", "ar", "zh"):
            pg.locator("#patterns-gate").scroll_into_view_if_needed()
            shot(pg, f"U-U3-patterns-gate-{code}")
        rec.junk_scan(pg, "#patterns-gate", f"U3 gate {code}")
    rec.note("u3.per_locale", per)
    # back in English: Session forensics (top of the same fold)
    pg.click("#session-forensics-box button:has-text('Session forensics')")
    pg.wait_for_function("() => { const o = document.getElementById('session-forensics-out'); return o && o.textContent.trim().length > 0 && !/^Loading/.test(o.textContent.trim()); }", timeout=60000)
    pg.wait_for_timeout(500)
    rec.note("u3.forensics", text_of(pg, "#session-forensics-out")[:1500])
    rec.note("u3.forensics_err", pg.evaluate("() => !!document.querySelector('#session-forensics-out .err, #session-forensics-out .note.err')"))
    rec.junk_scan(pg, "#session-forensics-out", "U3 forensics en")
    pg.locator("#session-forensics-out").scroll_into_view_if_needed()
    shot(pg, "U-U3-forensics-en")


# ------------------------------------------------------------------ U5 ------------
def read_u5(pg, code):
    out = {}
    # (f) Home -> By channel: select it BEFORE switching (done by caller); read here too
    # (a) collection
    sel = open_adv(pg, "collect")
    out["a_hint"] = text_of(pg, f"{sel} section.panel > p.hint")
    inner = f"{sel} details.adv-collect"
    if not pg.evaluate(f"() => document.querySelector(\"{inner}\").open"):
        pg.click(f"{inner} > summary"); pg.wait_for_timeout(500)
    out["a_speed"] = text_of(pg, "#sch-speed-val")
    out["a_hscroll"] = hscroll(pg)
    if code == "ar":
        pg.locator("#sch-speed-val").scroll_into_view_if_needed(); shot(pg, "U-U5a-collect-ar")
    # (b) sources csv
    open_adv(pg, "sources")
    out["b_csv"] = text_of(pg, "#src-csv-hint")
    out["b_hscroll"] = hscroll(pg)
    # (c) keywords stoplist
    open_adv(pg, "keywords")
    pg.wait_for_timeout(800)
    out["c_stoplist"] = text_of(pg, "#kf-builtin-view > summary")
    out["c_stoplist_raw"] = pg.evaluate("() => document.getElementById('kf-builtin-count').textContent")
    out["c_hscroll"] = hscroll(pg)
    # (d) Governments -> Law
    nav(pg, "law")
    pg.click("#gov-subtabs [data-tab='law']"); pg.wait_for_timeout(700)
    out["d_law"] = text_of(pg, "#gov-law p.hint")
    out["d_hscroll"] = hscroll(pg)
    if code in ("ar",):
        shot(pg, "U-U5d-law-ar")
    # (e) Help
    pg.click("button.icon-btn[onclick=\"showTab('help')\"]"); pg.wait_for_timeout(900)
    out["e_help"] = text_of(pg, "#tab-help section.panel p.muted")
    out["e_hscroll"] = hscroll(pg)
    return out


def goto_channels(pg):
    nav(pg, "home")
    pg.wait_for_timeout(1500)
    has_tab = pg.evaluate("() => !!document.querySelector('#home-fam-subtabs button[data-tab=\"__channels\"]')")
    if has_tab:
        pg.click("#home-fam-subtabs button[data-tab='__channels']"); pg.wait_for_timeout(600)
    return has_tab


def u5(pg):
    res = {}
    for code in ["en", "fr", "ar", "zh"]:
        has_tab = goto_channels(pg)
        before = text_of(pg, "#home-channels .hint") if pg.query_selector("#home-channels .hint") else "(no line)"
        if code != "en":
            r = switch_lang(pg, code)   # wait inside is ~1.2 s, no reload
        else:
            r = {"lang": "en", "dir": "ltr"}
        f_line = text_of(pg, "#home-channels .hint") if pg.query_selector("#home-channels .hint") else "(no line)"
        f = {"has_subtab": has_tab, "before_switch": before, "after_switch": f_line,
             "panel_hidden": pg.evaluate("() => document.getElementById('home-channels-panel').hidden"),
             "url": pg.url, "hscroll": hscroll(pg)}
        if code in ("en", "ar"):
            shot(pg, f"U-U5f-channels-{code}")
        rec.junk_scan(pg, "#home-channels-panel", f"U5f {code}")
        out = read_u5(pg, code)
        out["f"] = f
        out["dir"] = r["dir"]
        res[code] = out
        rec.note(f"u5.{code}", out)
    rec.obs["u5"] = res


# ------------------------------------------------------------------ U6 ------------
def overlay_measure(pg):
    return pg.evaluate("""() => {
      const svg = document.querySelector('#an-price svg'); if (!svg) return {svg: false, html: (document.getElementById('an-price')||{}).innerText};
      const rects = [...svg.querySelectorAll('rect')];
      const accentBars = rects.filter(r => r.getAttribute('fill') === 'var(--accent)' && r.getAttribute('fill-opacity') === '0.55');
      const caps = rects.filter(r => r.getAttribute('fill') === 'var(--accent)' && r.getAttribute('height') === '2' && !r.getAttribute('fill-opacity'));
      const cov = rects.filter(r => r.getAttribute('fill') === 'var(--muted)');
      const baseY = svg.viewBox.baseVal.height - 28;
      const bars = accentBars.map(r => ({y: +r.getAttribute('y'), h: +r.getAttribute('height'), bottom: +r.getAttribute('y') + +r.getAttribute('height'), w: +r.getAttribute('width')}));
      const texts = [...svg.querySelectorAll('text')].map(t => ({t: t.textContent, fill: t.getAttribute('fill'), anchor: t.getAttribute('text-anchor')}));
      return {svg: true, accentBars: bars.length, caps: caps.length, coverageBars: cov.length,
              polylines: svg.querySelectorAll('polyline').length, dots: svg.querySelectorAll('circle').length,
              bars, baseY, minBarH: bars.length ? Math.min(...bars.map(b => b.h)) : null,
              allBottomsAtBase: bars.every(b => Math.abs(b.bottom - baseY) < 0.2), texts,
              head: (document.querySelector('#an-price .hint') || {}).textContent,
              note: [...document.querySelectorAll('#an-price > div')].map(d => d.textContent).slice(-1)[0]};
    }""")


def u6(pg):
    for sym in ["Dy", "Nd"]:
        nav(pg, "markets")
        pg.wait_for_selector("#mkt-dashboard .fam-member", timeout=30000)
        pg.wait_for_timeout(800)
        if sym == "Dy":
            rec.note("u6.family_heads", pg.eval_on_selector_all("#mkt-dashboard .fam-head", "els => els.map(e => e.textContent.replace(/\\s+/g,' ').trim())"))
            rec.note("u6.members", pg.eval_on_selector_all("#mkt-dashboard .fam-member", "els => els.map(e => e.textContent.replace(/\\s+/g,' ').trim())"))
            rec.note("u6.cat_tabs", pg.evaluate("() => { const n = document.getElementById('mkt-cat-tabs'); return n ? n.innerText : '(no #mkt-cat-tabs)'; }"))
            shot(pg, "U-U6-commodities-en")
        mem = pg.locator("#mkt-dashboard .fam-member", has=pg.locator(".fam-mlabel", has_text=re.compile(rf"^{sym}$")))
        rec.note(f"u6.{sym}.member_count", mem.count())
        b = mem.first.locator("button.fam-mbtn[data-act='0']")
        rec.note(f"u6.{sym}.btn", {"glyph": b.text_content(), "title": b.get_attribute("title")})
        b.click()
        pg.wait_for_timeout(1500)
        price_tab = pg.locator("#an-price-tab")
        rec.note(f"u6.{sym}.price_tab_visible", price_tab.is_visible())
        if price_tab.is_visible() and "active" not in (price_tab.get_attribute("class") or ""):
            price_tab.click()
        pg.wait_for_function("() => { const p = document.getElementById('an-price'); return p && (p.querySelector('svg') || /no data|No corpus|Loading/.test(p.textContent) === false) && !/Loading/.test(p.textContent); }", timeout=30000)
        pg.wait_for_timeout(800)
        m = overlay_measure(pg)
        rec.note(f"u6.{sym}.overlay", m)
        pr = pg.evaluate(f"async () => {{ const s = (await (await fetch('/api/commodities/{sym}/prices')).json()); return {{n: (s.prices||[]).length, prices: (s.prices||[]).map(p => [p.observed_on, p.price])}}; }}")
        rec.note(f"u6.{sym}.api_prices", {"n": pr["n"], "first": pr["prices"][:3], "last": pr["prices"][-2:], "min": min((p[1] for p in pr["prices"]), default=None)})
        pg.locator("#an-price").scroll_into_view_if_needed()
        shot(pg, f"U-U6-price-{sym}-en")
        rec.junk_scan(pg, "#an-price", f"U6 price {sym}")


# ------------------------------------------------------------------ U7 ------------
def u7(pg):
    rec.note("u7.summary_before", pg.evaluate("async () => (await (await fetch('/api/newsletters/attach/summary')).json())"))
    goto_settings(pg, "data")
    pg.locator("#nl-files").scroll_into_view_if_needed()
    files = sorted(str(p) for p in (OUT / "eml").glob("*.eml"))
    pg.set_input_files("#nl-files", files)
    pg.click("#nl-import-btn")
    pg.wait_for_function("() => /imported/.test(document.getElementById('nl-result').textContent)", timeout=60000)
    pg.wait_for_function("() => document.getElementById('nl-attach').style.display !== 'none'", timeout=20000)
    pg.wait_for_timeout(600)
    rec.note("u7.files", files)
    rec.note("u7.result", text_of(pg, "#nl-result"))
    rec.note("u7.caveat", text_of(pg, "#nl-attach-caveat"))
    rec.note("u7.caveat_style", pg.evaluate("() => { const c = document.getElementById('nl-attach-caveat'); const s = getComputedStyle(c); return {color: s.color, display: s.display, visible: !!c.getClientRects().length}; }"))
    rec.note("u7.body", pg.evaluate("() => document.getElementById('nl-attach-body').innerText"))
    rec.note("u7.rows", pg.eval_on_selector_all("#nl-attach-body .vr", "els => els.map(e => ({text: e.innerText.replace(/\\s+/g,' '), title: (e.querySelector('b')||{}).title}))"))
    rec.note("u7.summary_after_import", pg.evaluate("async () => (await (await fetch('/api/newsletters/attach/summary')).json())"))
    pg.locator("#nl-attach").scroll_into_view_if_needed()
    shot(pg, "U-U7-attach-en")
    rec.note("u7.hover_caveat", tip_text(pg, "#nl-attach-caveat"))
    if pg.query_selector("#nl-attach-body .vr b"):
        rec.note("u7.hover_count", tip_text(pg, "#nl-attach-body .vr b"))
    rec.junk_scan(pg, "#nl-attach", "U7 attach en")
    rec.junk_scan(pg, "#nl-result", "U7 result en")
    # Arabic
    r = switch_lang(pg, "ar")
    pg.wait_for_timeout(800)
    rec.note("u7.ar.dir", r)
    rec.note("u7.ar.result", text_of(pg, "#nl-result"))
    rec.note("u7.ar.caveat", text_of(pg, "#nl-attach-caveat"))
    rec.note("u7.ar.body", pg.evaluate("() => document.getElementById('nl-attach-body').innerText"))
    rec.note("u7.ar.block_dir", pg.evaluate("() => getComputedStyle(document.getElementById('nl-attach')).direction"))
    rec.note("u7.ar.hover_caveat", tip_text(pg, "#nl-attach-caveat"))
    if pg.query_selector("#nl-attach-body .vr b"):
        rec.note("u7.ar.hover_count", tip_text(pg, "#nl-attach-body .vr b"))
    pg.locator("#nl-attach").scroll_into_view_if_needed()
    shot(pg, "U-U7-attach-ar")
    rec.junk_scan(pg, "#nl-attach", "U7 attach ar")
    pg.set_viewport_size({"width": 375, "height": 800})
    pg.wait_for_timeout(1000)
    pg.locator("#nl-attach").scroll_into_view_if_needed()
    rec.note("u7.ar.375.hscroll", hscroll(pg))
    rec.note("u7.ar.375.block_overflow", pg.evaluate("() => { const e = document.getElementById('nl-attach'); return {sw: e.scrollWidth, cw: e.clientWidth, rect: e.getBoundingClientRect().toJSON()}; }"))
    shot(pg, "U-U7-attach-ar-375")
    pg.set_viewport_size({"width": 1440, "height": 950})
    pg.wait_for_timeout(600)
    switch_lang(pg, "en")
    pg.wait_for_timeout(600)
    n_dialogs = len(rec.dialogs)
    pg.locator("#nl-attach-undo").scroll_into_view_if_needed()
    pg.click("#nl-attach-undo")
    pg.wait_for_function("() => /moved back/.test(document.getElementById('nl-result').textContent)", timeout=30000)
    pg.wait_for_timeout(1200)
    rec.note("u7.undo_confirm", rec.dialogs[n_dialogs:])
    rec.note("u7.undo_result", text_of(pg, "#nl-result"))
    rec.note("u7.attach_hidden_after_undo", pg.evaluate("() => document.getElementById('nl-attach').style.display"))
    rec.note("u7.summary_after_undo", pg.evaluate("async () => (await (await fetch('/api/newsletters/attach/summary')).json())"))
    shot(pg, "U-U7-after-undo-en")


# ------------------------------------------------------------------ U9 ------------
def u9(pg):
    nav(pg, "agenda")
    pg.wait_for_timeout(1500)
    pg.click("#agenda-views [data-tab='month']"); pg.wait_for_timeout(1500)
    moons = pg.eval_on_selector_all(".ag-moon", "els => els.map(e => ({g: e.textContent, title: e.getAttribute('title')}))")
    rec.note("u9.moons", moons)
    rec.note("u9.agenda_categories", pg.evaluate("() => (document.getElementById('agenda-cats')||{}).innerText"))
    if moons:
        rec.note("u9.moon_hover", tip_text(pg, ".ag-moon"))
    shot(pg, "U-U9-agenda-month-en")
    open_adv(pg, "calendars")
    pg.wait_for_function("() => document.querySelectorAll('#feeddir-kind option').length > 1", timeout=30000)
    rec.note("u9.kind_options", pg.eval_on_selector_all("#feeddir-kind option", "els => els.map(e => e.value)"))
    rec.note("u9.agenda_cats", None)
    rec.note("u9.directory_status", text_of(pg, "#feeddir-status"))
    pg.locator("#feeddir-kind").scroll_into_view_if_needed(); shot(pg, "U-U9-directory-kinds-en")
    # also type-filter for the family names the gate expects, in case they sit under another kind
    for q in ["religio", "Christian", "Islam", "Astronomy"]:
        pg.fill("#feeddir-q", q); pg.wait_for_timeout(500)
        rec.note(f"u9.filter_{q}", pg.eval_on_selector_all("#feeddir-list details.cs-row > summary", "els => els.map(e => e.textContent.replace(/\\s+/g,' ').trim())"))
    pg.fill("#feeddir-q", ""); pg.wait_for_timeout(300)
    for kind in ["religion", "science"]:
        opts = pg.eval_on_selector_all("#feeddir-kind option", "els => els.map(e => e.value)")
        if kind not in opts:
            rec.note(f"u9.{kind}", {"n": 0, "rows": [], "note": f"Kind option '{kind}' not offered; options = {opts}"})
            continue
        pg.select_option("#feeddir-kind", kind)
        pg.wait_for_timeout(800)
        rows = pg.eval_on_selector_all("#feeddir-list details.cs-row > summary", "els => els.map(e => e.textContent.replace(/\\s+/g,' ').trim())")
        rec.note(f"u9.{kind}", {"n": len(rows), "rows": rows, "status": text_of(pg, "#feeddir-status")})
        if kind == "religion":
            pg.locator("#feeddir-list").scroll_into_view_if_needed(); shot(pg, "U-U9-religion-en")


if __name__ == "__main__":
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = br.new_context(viewport={"width": 1440, "height": 950})
        pg = ctx.new_page(); rec.attach(pg)
        pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        close_unrelated_dialogs(pg)
        if pg.evaluate("() => !!document.getElementById('guide-wizard').open"):
            pg.click("#gw-close")
        rec.note("plane_fill_start", plane_filled(pg))
        for st in STEPS:
            try:
                {"U3": u3, "U5": u5, "U6": u6, "U7": u7, "U9": u9}[st](pg)
            except Exception as e:
                rec.note(f"{st}.EXCEPTION", traceback.format_exc()[-1500:])
                try:
                    shot(pg, f"U-{st}-exception")
                except Exception:
                    pass
                try:
                    switch_lang(pg, "en")
                except Exception:
                    pass
        rec.note("plane_fill_end", plane_filled(pg))
        rec.note("online_end", pg.evaluate("async () => (await (await fetch('/api/system/network')).json())"))
        rec.save(); br.close()
    print("page_errors", rec.page_errors); print("console_errors", rec.console_errors)
    print("http_errors", rec.http_errors); print("junk", rec.junk); print("dialogs", rec.dialogs)
