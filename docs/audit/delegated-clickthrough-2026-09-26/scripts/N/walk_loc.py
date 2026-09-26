"""Row N, N11: the same surfaces in fr, ar (RTL), zh, ja; then delete the watch in en."""
import json, re, sys, traceback
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright

LOCS = sys.argv[1:] or ["fr", "ar", "zh", "ja"]
R: dict = {}
rec = Recorder("loc-" + "-".join(LOCS))

EN_PHRASES = [
    "also matched as the concept", "Count each form", "This search matched the concept",
    "Show only the words I typed", "Showing only the words you typed",
    "Search the concept in every language", "denotes several concepts", "Search one of them",
    "which you chose", "Show all senses", "The search was widened", "Search every form",
    "Searching every form", "Limit the search to", "articles in total, counted once each",
    "forms counted", "These figures overlap", "Bands are mention counts", "Interleave by date",
    "Group by language", "Not observed in this corpus", "Across languages", "This watch covers",
    "in every language its ring carries", "By language", "Text size", "Sort by",
    "Relevance / recency", "result(s)", "Open an article to read it", "Apply filter",
    "running total", "mentions", "Previous", "Next", "Page ", "source:", "language:", "View:",
    "Counts", "Indexed", "Map", "Cloud", "Counting", "The concept at the centre",
]


def english_left(s):
    s = s or ""
    return [p for p in EN_PHRASES if re.search(r"(?<![A-Za-z])" + re.escape(p) + r"(?![A-Za-z])", s)]


def num(s):
    m = re.search(r"\d[\d,.\s  ٬]*", s or "")
    return int(re.sub(r"\D", "", m.group(0))) if m else None


def chips(ap):
    return [c for c in ap.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]


def open_analysis_loc(ctx, page, term):
    open_palette_type(page, term)
    rows = page.query_selector_all(".pal-item")
    target = None
    for r in rows:
        t = r.inner_text().strip()
        if f"“{term}”" in t and "↗" in t:
            target = (r, t)
            break
    if not target:
        raise RuntimeError("no analysis row " + str([r.inner_text() for r in rows[:4]]))
    with ctx.expect_page(timeout=20000) as pinfo:
        target[0].click()
    ap = pinfo.value
    ap.wait_for_load_state("domcontentloaded")
    ap.wait_for_timeout(3000)
    dismiss_coach(ap)
    return ap, target[1]


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


def wait_xlang(ap, js_regex_src, timeout=40000):
    ap.wait_for_function("(src) => new RegExp(src).test((document.getElementById('an-xlang')||{}).innerText||'')", arg=js_regex_src, timeout=timeout)
    ap.wait_for_timeout(500)


def wait_forms(ap):
    ap.wait_for_function("""() => { const e = document.querySelector("[id^='an-xforms-']");
        return e && e.querySelector('b'); }""", timeout=60000)
    ap.wait_for_timeout(400)
    return text(ap, "[id^='an-xforms-']")


def overflow(pg):
    return pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


def rtl_facts(pg):
    return pg.evaluate("""() => { const sb=document.getElementById('sidebar'); const r=sb?sb.getBoundingClientRect():null;
      const x=document.getElementById('an-xlang'); const cs = x ? getComputedStyle(x) : null;
      return {dir: document.documentElement.dir || getComputedStyle(document.documentElement).direction, lang: document.documentElement.lang,
        sidebar_left: r ? Math.round(r.left) : null, sidebar_right: r ? Math.round(r.right) : null, vw: innerWidth,
        xlang_text_align: cs ? cs.textAlign : null, xlang_direction: cs ? cs.direction : null}; }""")


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    rec.attach_context(ctx, "loc")
    page = ctx.new_page()
    rec.attach(page, "main")
    dialogs = []
    accept = {"on": False}

    def on_dialog(d):
        dialogs.append({"type": d.type, "message": d.message})
        d.accept() if accept["on"] else d.dismiss()
    page.on("dialog", on_dialog)
    ctx.on("page", lambda pg: pg.on("dialog", on_dialog))

    page.goto(URL + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    close_dialogs(page)
    dismiss_coach(page)

    for lg in LOCS:
        r = R.setdefault(lg, {})
        try:
            page.bring_to_front()
            set_lang(page, lg)
            r["html_lang"] = page.evaluate("() => document.documentElement.lang")
            term = "climat" if lg == "fr" else "climate"
            ap, row = open_analysis_loc(ctx, page, term)
            r["palette_row"] = row
            r["analysis_url"] = ap.url
            r["analysis_lang"] = ap.evaluate("() => document.documentElement.lang")
            r["term_ok"] = ensure_term(ap, term, lg, "concept")
            r["total"] = wait_art_total(ap)
            r["url_when_measured"] = ap.url
            ap.wait_for_timeout(1500)
            r["xlang"] = text(ap, "#an-xlang")
            r["chips"] = chips(ap)
            r["total_line"] = text(ap, "#an-art-total")
            r["headers"] = ap.eval_on_selector_all("#an-art-list table tr:first-child th", "e=>e.map(x=>x.innerText.trim())")
            r["group_buttons"] = ap.eval_on_selector_all("#an-articles button[onclick^='_anSetGroupByLang']", "e=>e.map(x=>x.innerText.trim())")
            r["rtl"] = rtl_facts(ap)
            r["overflow_articles"] = overflow(ap)
            shot(ap, f"N-N11-articles-{lg}")
            # Count each form
            ap.click("#an-xlang button[onclick^='_anFormCounts']")
            r["forms"] = wait_forms(ap)
            # group by language
            ap.click("#an-articles button[onclick='_anSetGroupByLang(true)']")
            ap.wait_for_timeout(1500)
            r["group_headings"] = ap.eval_on_selector_all("#an-art-list tr.an-lang-group", "e=>e.map(x=>x.innerText.trim())")
            ap.click("#an-articles button[onclick='_anSetGroupByLang(false)']")
            ap.wait_for_timeout(800)
            r["english_left_articles"] = english_left(text(ap, "#an-articles")) if lg != "en" else []
            r["pager_text"] = ap.evaluate("() => { const e=[...document.querySelectorAll('#an-articles *')].find(x=>x.children.length<6 && /\\(\\d/.test(x.textContent) && /1/.test(x.textContent) && x.querySelector && x.textContent.length<80); return e ? e.textContent.trim() : null; }")
            r["facet_labels"] = ap.eval_on_selector_all("#an-art-facets span.muted", "e=>e.map(x=>x.textContent.trim()).filter(x=>x.endsWith(':'))")
            rec.junk_scan(ap, "#an-articles", f"N11 articles {lg}")
            # literal toggle
            ap.click("#an-xlang button[onclick='_anSetExpand(false)']")
            ap.wait_for_function("() => /expand=0/.test(location.search)", timeout=20000)
            ap.wait_for_timeout(2500)
            r["literal_total"] = wait_art_total(ap)
            r["literal_xlang"] = text(ap, "#an-xlang")
            r["literal_url"] = ap.url
            shot(ap, f"N-N11-literal-{lg}")
            ap.click("#an-xlang button[onclick='_anSetExpand(true)']")
            ap.wait_for_function("() => !/expand=0/.test(location.search)", timeout=20000)
            ap.wait_for_timeout(2500)
            r["restored_total"] = wait_art_total(ap)
            # Trend by language
            ap.click("#an-subtabs [data-tab=trend]")
            ap.wait_for_timeout(2500)
            r["trend_modes"] = ap.evaluate("() => [...document.querySelectorAll('#an-trend button')].filter(b => /anTrendSetMode/.test(b.getAttribute('onclick')||'')).map(b => b.textContent.trim())")
            bl = ap.locator("#an-trend button[onclick=\"anTrendSetMode('bylang')\"]")
            if bl.count():
                bl.first.click()
                ap.wait_for_selector("#an-trend-chart canvas", timeout=30000)
                ap.wait_for_timeout(1000)
                r["trend_totals"] = ap.evaluate("() => { const e = document.querySelector('#an-trend-chart + .hint'); return e ? e.textContent.trim() : ''; }")
                r["trend_caveat"] = ap.evaluate("() => { const e = document.querySelector('#an-trend-chart ~ .card-caveat'); return e ? e.textContent.trim() : ''; }")
                r["trend_refusal"] = ap.evaluate("() => { const e=document.getElementById('an-trend-refusal'); return e ? e.textContent.trim() : null; }")
                box = ap.evaluate("() => { const r=document.querySelector('#an-trend-chart canvas').getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}; }")
                ap.mouse.move(box["x"] + box["w"] * 0.525, box["y"] + box["h"] * 0.25)
                ap.wait_for_timeout(300)
                r["trend_hover"] = ap.evaluate("() => { const hs=document.querySelectorAll('#an-trend-chart .hint'); return hs.length ? hs[hs.length-1].textContent.trim() : ''; }")
                r["english_left_trend"] = english_left(text(ap, "#an-trend"))
                shot(ap, f"N-N11-trend-{lg}")
            # Mindmap concept (all locales; the brief asks it for ar)
            ap.click("#an-subtabs [data-tab=mindmap]")
            ap.wait_for_timeout(2500)
            r["mm_buttons"] = ap.eval_on_selector_all("#an-mindmap button", "e=>e.map(b=>b.innerText.trim())")
            cb = ap.locator("#an-mindmap button[onclick*='concept:true']")
            if cb.count():
                cb.first.click()
                ap.wait_for_timeout(2500)
                r["mm_missing"] = ap.evaluate("() => { const e=[...document.querySelectorAll('#an-mindmap .hint')][0]; return e ? e.textContent.trim() : null; }")
                r["mm_hints"] = ap.eval_on_selector_all("#an-mindmap .hint", "e=>e.map(x=>x.textContent.trim().slice(0,200))")
                r["mm_arm_titles"] = ap.evaluate("() => [...document.querySelectorAll('#an-mindmap svg title')].map(t=>t.textContent.trim())")
                r["mm_clipped"] = ap.evaluate("""() => { const out=[]; for (const svg of document.querySelectorAll('#an-mindmap svg')) { const sr=svg.getBoundingClientRect();
                    for (const t of svg.querySelectorAll('text')) { const q=t.getBoundingClientRect(); if (!q.width) continue;
                      if (q.left < sr.left-1 || q.right > sr.right+1 || q.top < sr.top-1 || q.bottom > sr.bottom+1) out.push(t.textContent.trim()); } } return out; }""")
                r["english_left_mindmap"] = english_left(text(ap, "#an-mindmap"))
                shot(ap, f"N-N11-concept-{lg}")
            r["overflow_end"] = overflow(ap)
            ap.close()

            # election: sense picker + cap switch in this locale
            page.bring_to_front()
            ep, erow = open_analysis_loc(ctx, page, "election")
            r["el_term_ok"] = ensure_term(ep, "election", lg, "election")
            r["el_url0"] = ep.url
            r["el_xlang0"] = text(ep, "#an-xlang")
            r["el_total0"] = wait_art_total(ep)
            pick = ep.locator("#an-xlang button[onclick*='_anPickSense']").filter(has_text="public election")
            if not pick.count():
                # the sense is already pinned in this tab (leaked lens): use the visible
                # "Show all senses" link first, as a reader would
                r["el_sense_already_pinned"] = True
                ep.click("#an-xlang button[onclick^='_anClearSense']")
                ep.wait_for_function("() => !/sense=/.test(location.search)", timeout=20000)
                ep.wait_for_timeout(2500)
                r["el_xlang_after_clear"] = text(ep, "#an-xlang")
                r["el_total_after_clear"] = wait_art_total(ep)
            pick.first.click()
            ep.wait_for_function("() => /sense=/.test(location.search)", timeout=20000)
            ep.wait_for_timeout(3000)
            r["el_total_pick"] = wait_art_total(ep)
            r["el_xlang_pick"] = text(ep, "#an-xlang")
            r["el_url_pick"] = ep.url
            ep.click("#an-xlang button[onclick^='_anFormCounts']")
            r["el_forms_capped_tail"] = (wait_forms(ep) or "")[-260:]
            shot(ep, f"N-N11-sense-{lg}")
            ep.click("#an-xlang button[onclick='_anSetCap(false)']")
            ep.wait_for_function("() => /cap=0/.test(location.search)", timeout=20000)
            ep.wait_for_timeout(3000)
            r["el_total_cap0"] = wait_art_total(ep)
            r["el_xlang_cap0"] = text(ep, "#an-xlang")
            r["english_left_election"] = english_left(text(ep, "#an-articles"))
            r["el_overflow"] = overflow(ep)
            ep.click("#an-xlang button[onclick='_anSetCap(true)']")
            ep.wait_for_function("() => !/cap=0/.test(location.search)", timeout=20000)
            ep.wait_for_timeout(1500)
            ep.close()

            if lg == "ar":
                page.bring_to_front()
                page.click("#navGroups button[data-tab=insights]")
                page.wait_for_selector("#ins-subtabs button[data-tab=trends]", state="visible", timeout=30000)
                page.click("#ins-subtabs button[data-tab=trends]")
                page.wait_for_selector("#trd-rising a.tb-label, #trd-top a.tb-label", timeout=60000)
                page.wait_for_timeout(1500)
                loc = page.locator("#trd-rising a.tb-label, #trd-top a.tb-label").filter(has_text=re.compile(r"^climate$"))
                if loc.count():
                    el = loc.first
                    el.scroll_into_view_if_needed(); el.hover(); page.wait_for_timeout(3000)
                    r["ins_hover"] = page.evaluate("() => { const e=document.getElementById('oo-tip'); return e && e.classList.contains('show') ? e.textContent.trim() : ''; }")
                    shot(page, "N-N11-insights-hover-ar")
                page.mouse.move(700, 900)
                page.click("#ins-subtabs button[data-tab=watches]")
                page.wait_for_timeout(2500)
                r["watch_list"] = text(page, "#wt-list")
                r["english_left_watch"] = english_left(r["watch_list"])
                r["rtl_page"] = rtl_facts(page)
                r["overflow_insights"] = overflow(page)
                shot(page, "N-N11-watch-ar")
        except Exception as e:  # noqa: BLE001
            r["exception"] = f"{type(e).__name__}: {str(e)[:500]}"
            r["trace"] = traceback.format_exc()[-1200:]
            print(lg, "EXC", e)

    if "--delete-watch" in sys.argv or True:
        try:
            page.bring_to_front()
            set_lang(page, "en")
            page.click("#navGroups button[data-tab=insights]")
            page.wait_for_selector("#ins-subtabs button[data-tab=watches]", state="visible", timeout=30000)
            page.click("#ins-subtabs button[data-tab=watches]")
            page.wait_for_timeout(2000)
            before = text(page, "#wt-list")
            card = page.locator("#wt-list .card").filter(has_text="Climate")
            R["delete_watch"] = {"cards_before": card.count(), "list_before": (before or "")[:200]}
            if card.count():
                accept["on"] = True
                card.first.locator("button", has_text="Delete").click()
                page.wait_for_timeout(2500)
                accept["on"] = False
            R["delete_watch"]["list_after"] = text(page, "#wt-list")
            R["delete_watch"]["dialogs"] = dialogs[-1:] if dialogs else []
        except Exception as e:  # noqa: BLE001
            R["delete_watch_exception"] = str(e)[:400]
    R["dialogs"] = dialogs
    R["races"] = RACES
    b.close()

rec.data = R
rec.save()
(OUT / f"R-loc-{'-'.join(LOCS)}.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1)[:30000])
print("PAGE ERRORS", rec.page_errors)
print("CONSOLE ERRORS", rec.console_errors)
print("HTTP", rec.http_errors)
print("JUNK", rec.junk)
