"""Row N, English main pass at 1440x950: N1-N10 (N11 locales + 375px are separate)."""
import json, re, sys, traceback, zipfile, io
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright

ONLY = set(sys.argv[1:])  # optional: run a subset, e.g. N2 N3
R: dict = {}
rec = Recorder("en")


def want(k):
    return not ONLY or k in ONLY


def step(k):
    def deco(fn):
        def run(*a, **kw):
            if not want(k):
                return None
            R.setdefault(k, {})
            try:
                return fn(*a, **kw)
            except Exception as e:  # noqa: BLE001
                R[k]["exception"] = f"{type(e).__name__}: {str(e)[:600]}"
                R[k]["trace"] = traceback.format_exc()[-1500:]
                print(k, "EXC", e)
        return run
    return deco


def tip_text(pg):
    return pg.evaluate("() => { const e=document.getElementById('oo-tip'); return e && e.classList.contains('show') ? e.textContent.trim() : ''; }")


def dates_of(ap):
    return ap.eval_on_selector_all("#an-art-list table tr[data-aid]", "rs=>rs.map(r=>{const td=r.querySelectorAll('td'); return [td[2]?td[2].innerText.trim():'', td[3]?td[3].innerText.trim():'']})")


def is_sorted_desc(ds):
    d = [x for x in ds if x]
    return all(d[i] >= d[i + 1] for i in range(len(d) - 1))


def click_xlang_button(ap, label):
    btn = ap.locator("#an-xlang button", has_text=label).first
    btn.click()


def wait_forms(ap):
    ap.wait_for_function("""() => { const e = document.querySelector("[id^='an-xforms-']");
        return e && e.textContent.trim() && !/…\\s*$/.test(e.textContent.trim()); }""", timeout=60000)
    ap.wait_for_timeout(300)
    return text(ap, "[id^='an-xforms-']")


def sentiment_n(ap):
    select_subtab(ap, "sentiment")
    ap.wait_for_function("() => /n=\\d+\\/\\d+/.test((document.getElementById('an-sentiment')||{}).innerText||'')", timeout=30000)
    t = text(ap, "#an-sentiment")
    m = re.search(r"n=(\d+)/(\d+)", t or "")
    return (int(m.group(1)), int(m.group(2))) if m else None, t


def trend_modes(ap):
    select_subtab(ap, "trend")
    ap.wait_for_timeout(1500)
    return ap.evaluate("""() => [...document.querySelectorAll('#an-trend button')]
      .filter(b => /anTrendSetMode/.test(b.getAttribute('onclick')||'')).map(b => b.textContent.trim())""")


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
    rec.attach_context(ctx, "en")
    page = ctx.new_page()
    rec.attach(page, "main")
    dialogs = []

    def on_dialog(d):
        dialogs.append({"type": d.type, "message": d.message, "url": page.url})
        # accept only the confirms this walk intends (set per step)
        if getattr(on_dialog, "accept", False):
            d.accept()
        else:
            d.dismiss()
    on_dialog.accept = False
    ctx.on("page", lambda pg: pg.on("dialog", on_dialog))
    page.on("dialog", on_dialog)

    # ---------------- N1 ----------------
    @step("N1")
    def n1():
        page.goto(URL + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        R["N1"]["landing_url"] = page.url
        R["N1"]["lock_form_visible"] = bool(page.query_selector("#pw")) and page.is_visible("#pw")
        if R["N1"]["lock_form_visible"]:
            R["N1"]["lock_screen_text"] = (text(page, "body") or "")[:300]
            shot(page, "N-N1-lock-en")
            page.fill("#pw", PASS)
            page.click("#btn-unlock")
            page.wait_for_url(re.compile(r".*#home.*"), timeout=90000)
            page.wait_for_timeout(4000)
        R["N1"]["after_unlock_url"] = page.url
        R["N1"]["dialogs_open"] = page.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d=>d.id)")
        close_dialogs(page)
        R["N1"]["coach_visible"] = page.is_visible("#net-coach-dismiss")
        R["N1"]["coach_text"] = text(page, "#net-coach")
        shot(page, "N-N1-home-en")
        dismiss_coach(page)
        R["N1"]["net_plane_fill"] = page.evaluate("() => { const s=document.getElementById('net-plane'); return s && s.getAttribute('fill'); }")
        R["N1"]["net_title"] = page.evaluate("() => document.getElementById('net-toggle').title")
        R["N1"]["status_api"] = page.evaluate("async () => { try { const r = await fetch('/api/system/network'); return await r.json(); } catch(e) { return String(e); } }")
    n1()
    close_dialogs(page)

    ap = None

    # ---------------- N2 ----------------
    @step("N2")
    def n2():
        global ap
        open_palette_type(page, "climate")
        R["N2"]["palette_rows_first3"] = palette_rows(page)[:3]
        ap = open_analysis_new_tab(ctx, page, "climate")
        R["N2"]["analysis_url"] = ap.url
        R["N2"]["opened_new_tab"] = ap is not page
        R["N2"]["term_ok_first_paint"] = ensure_term(ap, "climate", "en", "N2")
        R["N2"]["total"] = wait_art_total(ap)
        R["N2"]["xlang"] = text(ap, "#an-xlang")
        R["N2"]["xlang_buttons"] = ap.eval_on_selector_all("#an-xlang button", "e=>e.map(b=>b.innerText.trim())")
        R["N2"]["facets"] = text(ap, "#an-art-facets")
        chips = ap.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())")
        R["N2"]["language_chips"] = [c for c in chips if re.match(r"^[a-z]{3} \d+$", c)]
        R["N2"]["language_chip_sum"] = sum(int(c.split()[1]) for c in R["N2"]["language_chips"])
        R["N2"]["total_line"] = text(ap, "#an-art-total")
        R["N2"]["headers"] = ap.eval_on_selector_all("#an-art-list table tr:first-child th", "e=>e.map(x=>x.innerText.trim())")
        R["N2"]["rows_on_page"] = len(ap.query_selector_all("#an-art-list table tr[data-aid]"))
        R["N2"]["rows_with_3letter_code"] = ap.evaluate("""() => [...document.querySelectorAll('#an-art-list table tr[data-aid]')]
            .filter(r => /^[a-z]{3}\\b/.test((r.querySelectorAll('td')[2]||{innerText:''}).innerText.trim())).length""")
        # hover two language cells
        hov = []
        for idx in (0, 3):
            cell = ap.locator("#an-art-list table tr[data-aid]").nth(idx).locator("td").nth(2).locator("[title], span").first
            cell.hover()
            ap.wait_for_timeout(700)
            hov.append({"cell": cell.inner_text().strip(), "title_attr": cell.get_attribute("title") or cell.get_attribute("data-oo-tip"), "oo_tip": tip_text(ap)})
        R["N2"]["language_hover"] = hov
        d0 = dates_of(ap)
        R["N2"]["default_sort_value"] = ap.eval_on_selector("#an-adv-sort", "e=>e.value")
        R["N2"]["default_first12"] = d0[:12]
        R["N2"]["default_is_date_desc"] = is_sorted_desc([x[1] for x in d0])
        R["N2"]["interleave_pressed_by_default"] = ap.evaluate("""() => { const b=[...document.querySelectorAll('#an-art-total ~ * button, #an-articles button')].find(x=>x.textContent.trim()==='Interleave by date'); return b ? b.getAttribute('aria-pressed') : null; }""")
        shot(ap, "N-N2-articles-default-en")
        rec.junk_scan(ap, "#an-articles", "N2 articles en")
        # sort by date
        ap.select_option("#an-adv-sort", "date")
        ap.wait_for_timeout(2500)
        wait_art_total(ap)
        d1 = dates_of(ap)
        R["N2"]["date_sort_first12"] = d1[:12]
        R["N2"]["date_sort_is_desc"] = is_sorted_desc([x[1] for x in d1])
        R["N2"]["date_sort_langs_on_page"] = sorted(set(x[0][:3] for x in d1))
        R["N2"]["date_sort_total"] = wait_art_total(ap)
        # group by language
        ap.locator("#an-articles button", has_text="Group by language").first.click()
        ap.wait_for_timeout(1500)
        heads = ap.eval_on_selector_all("#an-art-list tr.an-lang-group", "e=>e.map(x=>x.innerText.trim())")
        R["N2"]["group_headings"] = heads
        R["N2"]["group_heading_sum"] = sum(int(m.group(1)) for h in heads for m in [re.search(r"(\d+)\s+articles", h)] if m)
        R["N2"]["group_rows"] = len(ap.query_selector_all("#an-art-list table tr[data-aid]"))
        R["N2"]["group_total_line"] = text(ap, "#an-art-total")
        shot(ap, "N-N2-grouped-en")
        ap.locator("#an-articles button", has_text="Interleave by date").first.click()
        ap.wait_for_timeout(1200)
        R["N2"]["after_interleave_group_headings"] = len(ap.query_selector_all("#an-art-list tr.an-lang-group"))
        ap.select_option("#an-adv-sort", "")
        ap.wait_for_timeout(2000)
        R["N2"]["back_to_relevance_total"] = wait_art_total(ap)
    n2()

    # ---------------- N3 ----------------
    @step("N3")
    def n3():
        select_subtab(ap, "articles")
        wait_art_total(ap)
        click_xlang_button(ap, "Count each form")
        R["N3"]["counting_placeholder_seen"] = "Counting" in (text(ap, "[id^='an-xforms-']") or "")
        R["N3"]["readout"] = wait_forms(ap)
        forms = re.findall(r"(\S+) (\d+|—)(?= ·| \d| ·|$)", (R["N3"]["readout"] or "").split(" articles in total")[0])
        R["N3"]["forms_parsed"] = forms
        m = re.search(r"(\d+) articles in total", R["N3"]["readout"] or "")
        R["N3"]["in_total"] = int(m.group(1)) if m else None
        forms = [x for x in forms if x[0] != "·"]; R["N3"]["forms_parsed"] = forms
        nums = [int(n) for _, n in forms if n.isdigit()]
        R["N3"]["form_sum"] = sum(nums)
        R["N3"]["has_N_of_M"] = bool(re.search(r"\d+ of \d+ forms counted", R["N3"]["readout"] or ""))
        R["N3"]["dash_forms"] = [f for f, n in forms if n == "—"]
        shot(ap, "N-N3-formcounts-en")
        # Boolean search in the first tab
        page.bring_to_front()
        open_palette_type(page, "climate")
        row = click_palette_row(page, ["Run the full Boolean search for “climate”"])
        R["N3"]["boolean_row_clicked"] = row
        page.wait_for_function("() => /result/.test((document.getElementById('search-meta')||{}).textContent||'')", timeout=30000)
        page.wait_for_timeout(800)
        R["N3"]["search_meta"] = text(page, "#search-meta")
        R["N3"]["search_url"] = page.url
        R["N3"]["search_tab_visible"] = page.is_visible("#tab-search")
        shot(page, "N-N3-search-en")
    n3()

    # ---------------- N4 ----------------
    @step("N4")
    def n4():
        global ap
        ap.bring_to_front()
        R["N4"]["sentiment_before"], R["N4"]["sentiment_text_before"] = sentiment_n(ap)
        select_subtab(ap, "articles")
        wait_art_total(ap)
        click_xlang_button(ap, "Show only the words I typed")
        ap.wait_for_function("() => /Showing only the words you typed/.test((document.getElementById('an-xlang')||{}).innerText||'')", timeout=30000)
        R["N4"]["url_after_toggle"] = ap.url
        R["N4"]["xlang_after_toggle"] = text(ap, "#an-xlang")
        R["N4"]["total_after_toggle"] = wait_art_total(ap)
        R["N4"]["chips_after_toggle"] = [c for c in ap.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]
        shot(ap, "N-N4-literal-en")
        R["N4"]["trend_modes_literal"] = trend_modes(ap)
        R["N4"]["sentiment_literal"], _ = sentiment_n(ap)
        # F5
        ap.reload(wait_until="domcontentloaded")
        ap.wait_for_timeout(3500)
        R["N4"]["after_reload_url"] = ap.url
        R["N4"]["after_reload_active_subtab"] = ap.evaluate("() => { const b=document.querySelector('#an-subtabs button.active'); return b && b.dataset.tab; }")
        select_subtab(ap, "articles")
        R["N4"]["after_reload_total"] = wait_art_total(ap)
        R["N4"]["after_reload_xlang"] = text(ap, "#an-xlang")
        # pasted into a NEW tab
        url = ap.url
        np_ = ctx.new_page()
        np_.goto(url, wait_until="domcontentloaded")
        np_.wait_for_timeout(3500)
        close_dialogs(np_)
        select_subtab(np_, "articles")
        R["N4"]["pasted_url"] = url
        R["N4"]["pasted_total"] = wait_art_total(np_)
        R["N4"]["pasted_xlang"] = text(np_, "#an-xlang")
        np_.close()
        ap.bring_to_front()
        click_xlang_button(ap, "Search the concept in every language")
        ap.wait_for_function("() => /also matched as the concept/.test((document.getElementById('an-xlang')||{}).innerText||'')", timeout=30000)
        R["N4"]["url_after_restore"] = ap.url
        R["N4"]["total_after_restore"] = wait_art_total(ap)
        R["N4"]["xlang_after_restore_head"] = (text(ap, "#an-xlang") or "")[:160]
    n4()

    # ---------------- N5 ----------------
    @step("N5")
    def n5():
        page.bring_to_front()
        ep = open_analysis_new_tab(ctx, page, "election")
        R["N5"]["url0"] = ep.url
        R["N5"]["term_ok_first_paint"] = ensure_term(ep, "election", "en", "N5")
        R["N5"]["total0"] = wait_art_total(ep)
        R["N5"]["xlang0"] = text(ep, "#an-xlang")
        R["N5"]["buttons0"] = ep.eval_on_selector_all("#an-xlang button", "e=>e.map(b=>b.innerText.trim())")
        R["N5"]["chips0"] = [c for c in ep.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]
        ep.wait_for_timeout(3000)
        R["N5"]["chips0_after3s"] = [c for c in ep.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]
        R["N5"]["total0_after3s"] = wait_art_total(ep)
        R["N5"]["xlang0_after3s_head"] = (text(ep, "#an-xlang") or "")[:120]
        R["N5"]["active_tab_strip"] = ep.eval_on_selector_all(".an-tab", "e=>e.map(x=>[x.innerText.trim().slice(0,20), x.className])")
        shot(ep, "N-N5-declined-en")
        click_xlang_button(ep, "“public election”")
        ep.wait_for_function("() => /which you chose/.test((document.getElementById('an-xlang')||{}).innerText||'')", timeout=30000)
        R["N5"]["url_pick"] = ep.url
        R["N5"]["total_pick"] = wait_art_total(ep)
        R["N5"]["xlang_pick"] = text(ep, "#an-xlang")
        R["N5"]["chips_pick"] = [c for c in ep.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]
        shot(ep, "N-N5-sense-picked-en")
        click_xlang_button(ep, "Count each form")
        R["N5"]["forms_capped"] = wait_forms(ep)
        click_xlang_button(ep, "Search every form")
        ep.wait_for_function("() => /Searching every form of the concept/.test((document.getElementById('an-xlang')||{}).innerText||'')", timeout=60000)
        R["N5"]["url_cap0"] = ep.url
        R["N5"]["total_cap0"] = wait_art_total(ep)
        R["N5"]["xlang_cap0"] = text(ep, "#an-xlang")
        R["N5"]["chips_cap0"] = [c for c in ep.eval_on_selector_all("#an-art-facets .an-facet", "e=>e.map(b=>b.innerText.trim())") if re.match(r"^[a-z]{3} \d+$", c)]
        click_xlang_button(ep, "Count each form")
        R["N5"]["forms_uncapped"] = wait_forms(ep)
        shot(ep, "N-N5-cap-off-en")
        click_xlang_button(ep, "Limit the search to the most-mentioned forms")
        ep.wait_for_function("() => /Search every form/.test((document.getElementById('an-xlang')||{}).innerText||'')", timeout=60000)
        R["N5"]["url_cap_restored"] = ep.url
        R["N5"]["total_cap_restored"] = wait_art_total(ep)
        click_xlang_button(ep, "Show all senses")
        ep.wait_for_function("() => /denotes several concepts/.test((document.getElementById('an-xlang')||{}).innerText||'')", timeout=60000)
        R["N5"]["url_all_senses"] = ep.url
        R["N5"]["xlang_all_senses"] = text(ep, "#an-xlang")
        R["N5"]["total_all_senses"] = wait_art_total(ep)
        rec.junk_scan(ep, "#an-articles", "N5 election en")
        ep.close()
    n5()

    # ---------------- N6 ----------------
    @step("N6")
    def n6():
        ap.bring_to_front()
        select_subtab(ap, "trend")
        ap.wait_for_timeout(1500)
        R["N6"]["modes"] = trend_modes(ap)
        ap.locator("#an-trend button", has_text="By language").first.click()
        ap.wait_for_selector("#an-trend-chart canvas", timeout=30000)
        ap.wait_for_timeout(1000)
        R["N6"]["totals_line"] = ap.evaluate("() => { const e = document.querySelector('#an-trend-chart + .hint'); return e ? e.textContent.trim() : ''; }")
        R["N6"]["caveat"] = ap.evaluate("() => { const e = document.querySelector('#an-trend-chart ~ .card-caveat'); return e ? e.textContent.trim() : ''; }")
        R["N6"]["refusal"] = ap.evaluate("() => { const e=document.getElementById('an-trend-refusal'); return e ? e.textContent.trim() : null; }")
        R["N6"]["legend"] = ap.eval_on_selector_all("#an-trend-chart .fig-leg", "e=>e.map(x=>x.innerText.trim())")
        R["N6"]["pixels"] = ap.evaluate("""() => { const cv = document.querySelector('#an-trend-chart canvas'); const c = cv.getContext('2d');
            const d = c.getImageData(0,0,cv.width,cv.height).data; const seen=new Map();
            for (let y=0;y<cv.height;y+=3) for (let x=0;x<cv.width;x+=3){const i=(y*cv.width+x)*4; if(d[i+3]<24) continue; const k=(d[i]>>4)+','+(d[i+1]>>4)+','+(d[i+2]>>4); seen.set(k,(seen.get(k)||0)+1);}
            return {w:cv.width,h:cv.height,area_colours:[...seen.values()].filter(n=>n>=40).length}; }""")
        box = ap.evaluate("() => { const r=document.querySelector('#an-trend-chart canvas').getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}; }")
        # scan across x to find the tallest column: move at many x positions at a low y and read
        def readout():
            return ap.evaluate("() => { const hs=document.querySelectorAll('#an-trend-chart .hint'); return hs.length ? hs[hs.length-1].textContent.trim() : ''; }")
        best = None
        for fx in [i / 40 for i in range(2, 39)]:
            ap.mouse.move(box["x"] + box["w"] * fx, box["y"] + box["h"] * 0.80)
            ap.wait_for_timeout(60)
            r0 = readout()
            m = re.search(r"running total (\d+)", r0)
            if m:
                v = int(m.group(1))
                if best is None or v > best[0]:
                    best = (v, fx)
        R["N6"]["scan_best"] = best
        fx = best[1] if best else 0.55
        hover = []
        for fy in (0.86, 0.80, 0.70, 0.55, 0.40, 0.25, 0.12):
            ap.mouse.move(box["x"] + box["w"] * fx, box["y"] + box["h"] * fy)
            ap.wait_for_timeout(200)
            hover.append({"fy": fy, "readout": readout()})
        R["N6"]["hover_column"] = hover
        shot(ap, "N-N6-stacked-en")
        # legend chip hide / restore
        n_before = R["N6"]["pixels"]["area_colours"]
        leg = ap.locator("#an-trend-chart .fig-leg").first
        R["N6"]["legend_first"] = leg.inner_text().strip()
        leg.click(); ap.wait_for_timeout(600)
        R["N6"]["legend_after_hide"] = ap.eval_on_selector_all("#an-trend-chart .fig-leg", "e=>e.map(x=>[x.innerText.trim(), x.getAttribute('aria-pressed')])")
        R["N6"]["pixels_after_hide"] = ap.evaluate("""() => { const cv = document.querySelector('#an-trend-chart canvas'); const c = cv.getContext('2d');
            const d = c.getImageData(0,0,cv.width,cv.height).data; const seen=new Map();
            for (let y=0;y<cv.height;y+=3) for (let x=0;x<cv.width;x+=3){const i=(y*cv.width+x)*4; if(d[i+3]<24) continue; const k=(d[i]>>4)+','+(d[i+1]>>4)+','+(d[i+2]>>4); seen.set(k,(seen.get(k)||0)+1);}
            return [...seen.values()].filter(n=>n>=40).length; }""")
        shot(ap, "N-N6-legend-hidden-en")
        R["N6"]["hidden_chip_still_present"] = any(x[0].startswith("eng") for x in R["N6"]["legend_after_hide"])
        # try to bring eng back: there is no eng chip left to click; switch view and back
        ap.locator("#an-trend button", has_text="Counts").first.click(); ap.wait_for_timeout(1200)
        ap.locator("#an-trend button", has_text="By language").first.click(); ap.wait_for_timeout(1500)
        R["N6"]["legend_after_view_switch"] = ap.eval_on_selector_all("#an-trend-chart .fig-leg", "e=>e.map(x=>[x.innerText.trim(), x.getAttribute('aria-pressed')])")
        R["N6"]["pixels_before"] = n_before
    n6()

    # ---------------- N7 ----------------
    @step("N7")
    def n7():
        ap.bring_to_front()
        select_subtab(ap, "mindmap")
        ap.wait_for_timeout(2500)
        R["N7"]["buttons"] = ap.eval_on_selector_all("#an-mindmap button", "e=>e.map(b=>b.innerText.trim())")
        ap.locator("#an-mindmap button", has_text="Concept").first.click()
        ap.wait_for_timeout(2500)
        R["N7"]["missing_line"] = ap.evaluate("() => { const e=[...document.querySelectorAll('#an-mindmap .hint')].find(x=>/Not observed in this corpus/.test(x.textContent)); return e ? e.textContent.trim() : null; }")
        R["N7"]["concept_button_on"] = ap.evaluate("() => { const b=[...document.querySelectorAll('#an-mindmap button')].find(x=>x.textContent.trim()==='Concept'); return b ? b.className : null; }")
        R["N7"]["titles"] = ap.evaluate("""() => [...document.querySelectorAll('#an-mindmap svg title')].map(t=>({t:t.textContent.trim(), txt:(t.parentNode.querySelector('text')||{textContent:''}).textContent.trim()}))""")
        R["N7"]["svg_texts"] = ap.eval_on_selector_all("#an-mindmap svg text", "e=>e.map(x=>x.textContent.trim())")
        # hover centre, an arm, a leaf; read the <title> of the hovered group and the oo-tip
        def hover_text_node(txt):
            loc = ap.locator("#an-mindmap svg text", has_text=txt).first
            loc.hover(force=True)
            ap.wait_for_timeout(500)
            ttl = loc.evaluate("e => { const p=e.parentNode; const t=p.querySelector('title'); return t ? t.textContent.trim() : (e.querySelector('title')||{textContent:''}).textContent.trim(); }")
            return {"text": txt, "svg_title": ttl, "oo_tip": tip_text(ap)}
        hv = []
        texts = R["N7"]["svg_texts"]
        centre = next((x for x in texts if x == "climate"), None)
        if centre:
            hv.append(hover_text_node("climate"))
        arm = next((x for x in texts if re.match(r"^(eng|fra|spa|ita|por|deu)\b", x)), None)
        for a in [x for x in texts if re.match(r"^(eng|spa|ita|por)\b", x)][:3]:
            hv.append(hover_text_node(a))
        leaf = next((x for x in texts if x in ("assembly", "rapport")), None)
        if leaf:
            hv.append(hover_text_node(leaf))
        R["N7"]["hovers"] = hv
        # clipping check: every svg text bbox inside the svg's visible box
        clip_js = """() => { const out=[]; for (const svg of document.querySelectorAll('#an-mindmap svg')) { const sr=svg.getBoundingClientRect();
            for (const t of svg.querySelectorAll('text')) { const r=t.getBoundingClientRect(); if (r.width===0) continue;
              if (r.left < sr.left-1 || r.right > sr.right+1 || r.top < sr.top-1 || r.bottom > sr.bottom+1) out.push({t:t.textContent.trim(), l:Math.round(r.left-sr.left), r:Math.round(sr.right-r.right), top:Math.round(r.top-sr.top), b:Math.round(sr.bottom-r.bottom)}); } } return out; }"""
        R["N7"]["clipped_default"] = ap.evaluate(clip_js)
        shot(ap, "N-N7-concept-en")
        rng = ap.locator("#an-mindmap input[type=range]").first
        R["N7"]["range_attrs"] = rng.evaluate("e => ({min:e.min, max:e.max, value:e.value})")
        mid = R["N7"]["range_attrs"]["value"]
        lab_h = "() => { const t=[...document.querySelectorAll('#an-mindmap svg text')].find(x=>x.textContent.trim()==='climate'); return t ? Math.round(t.getBoundingClientRect().height) : null; }"
        R["N7"]["centre_label_px_default"] = ap.evaluate(lab_h)
        rng.focus(); ap.keyboard.press("End"); ap.wait_for_timeout(1500)
        R["N7"]["range_after_end"] = ap.locator("#an-mindmap input[type=range]").first.evaluate("e => e.value")
        R["N7"]["centre_label_px_max"] = ap.evaluate(lab_h)
        R["N7"]["clipped_max_text"] = ap.evaluate(clip_js)
        shot(ap, "N-N7-concept-maxtext-en")
        rng = ap.locator("#an-mindmap input[type=range]").first
        bb = rng.bounding_box()
        ap.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        ap.wait_for_timeout(1200)
        R["N7"]["range_after_middle_click"] = ap.locator("#an-mindmap input[type=range]").first.evaluate("e => e.value")
        R["N7"]["centre_label_px_middle"] = ap.evaluate(lab_h)
        ap.locator("#an-mindmap button", has_text="⛶").first.click()
        ap.wait_for_timeout(1500)
        R["N7"]["clipped_enlarged"] = ap.evaluate(clip_js)
        R["N7"]["centre_label_px_enlarged"] = ap.evaluate(lab_h)
        R["N7"]["enlarged_svg_size"] = ap.evaluate("() => { const s=document.querySelector('#an-mindmap svg'); if(!s) return null; const r=s.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }")
        shot(ap, "N-N7-concept-enlarged-en")
        ap.locator("#an-mindmap button", has_text="⛶").first.click()
        ap.wait_for_timeout(1000)
        R["N7"]["after_unenlarge_svg_size"] = ap.evaluate("() => { const s=document.querySelector('#an-mindmap svg'); if(!s) return null; const r=s.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }")
        rec.junk_scan(ap, "#an-mindmap", "N7 mindmap en")
    n7()

    # ---------------- N8 ----------------
    @step("N8")
    def n8():
        page.bring_to_front()
        page.click("#navGroups button[data-tab=insights]")
        page.wait_for_selector("#ins-subtabs button[data-tab=trends]", state="visible", timeout=30000)
        page.click("#ins-subtabs button[data-tab=trends]")
        try:
            page.wait_for_selector("#trd-rising a.tb-label, #trd-top a.tb-label", timeout=60000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        labels = page.eval_on_selector_all("#trd-rising a.tb-label, #trd-top a.tb-label", "e=>e.map(a=>a.textContent.trim())")
        R["N8"]["labels_7d"] = labels[:60]
        if "climate" not in labels:
            page.fill("#trd-window", "30")
            page.locator("#ins-trends button", has_text="Refresh").first.click()
            page.wait_for_timeout(4000)
            labels = page.eval_on_selector_all("#trd-rising a.tb-label, #trd-top a.tb-label", "e=>e.map(a=>a.textContent.trim())")
            R["N8"]["labels_30d"] = labels[:60]
            R["N8"]["used_30d"] = True
        loc = page.locator("#trd-rising a.tb-label, #trd-top a.tb-label").filter(has_text=re.compile(r"^climate$"))
        R["N8"]["climate_rows"] = loc.count()
        if loc.count():
            el = loc.first
            el.scroll_into_view_if_needed()
            el.hover()
            page.wait_for_timeout(3000)
            R["N8"]["climate_hover_tip"] = tip_text(page)
            R["N8"]["climate_title_attr"] = el.get_attribute("title")
            R["N8"]["climate_tip_extra"] = el.get_attribute("data-oo-tip-extra")
            shot(page, "N-N8-trends-hover-en")
            # keyboard: move mouse away, press Tab until the label has focus
            page.mouse.move(5, 900)
            page.wait_for_timeout(400)
            page.click("#trd-window")
            focused = False
            for i in range(400):
                page.keyboard.press("Tab")
                if el.evaluate("e => document.activeElement === e"):
                    focused = True
                    R["N8"]["tab_presses"] = i + 1
                    break
            R["N8"]["keyboard_reached"] = focused
            page.wait_for_timeout(1500)
            R["N8"]["climate_focus_tip"] = tip_text(page)
        # a non-concept row
        cand = page.locator("#trd-rising a.tb-label, #trd-top a.tb-label")
        nonc = None
        for i in range(min(cand.count(), 60)):
            h = cand.nth(i)
            if not h.get_attribute("data-oo-tip-extra") and h.inner_text().strip() != "climate":
                nonc = h
                break
        if nonc:
            page.mouse.move(5, 900); page.wait_for_timeout(300)
            nonc.scroll_into_view_if_needed(); nonc.hover(); page.wait_for_timeout(2500)
            R["N8"]["nonconcept_label"] = nonc.inner_text().strip()
            R["N8"]["nonconcept_tip"] = tip_text(page)
        rows_with_extra = page.eval_on_selector_all("#trd-rising a.tb-label, #trd-top a.tb-label", "e=>e.filter(a=>a.getAttribute('data-oo-tip-extra')).map(a=>[a.textContent.trim(), a.getAttribute('data-oo-tip-extra')])")
        R["N8"]["rows_with_breakdown"] = rows_with_extra[:12]
        rec.junk_scan(page, "#ins-trends", "N8 trends en")
        # Watches
        page.click("#ins-subtabs button[data-tab=watches]")
        page.wait_for_selector("#wt-name", state="visible", timeout=20000)
        page.wait_for_timeout(1000)
        R["N8"]["watches_before"] = text(page, "#wt-list")
        page.fill("#wt-name", "Climate")
        page.fill("#wt-query", "climate")
        page.fill("#wt-threshold", "2")
        page.fill("#wt-window", "30")
        page.locator("#ins-watches button", has_text="Add watch").first.click()
        page.wait_for_timeout(2500)
        R["N8"]["wt_msg"] = text(page, "#wt-msg")
        R["N8"]["watch_list"] = text(page, "#wt-list")
        con = page.locator("#wt-list span").filter(has_text=re.compile(r"^the concept")).first
        if con.count():
            con.hover(); page.wait_for_timeout(900)
            R["N8"]["watch_concept_title"] = con.get_attribute("title") or con.get_attribute("data-oo-tip")
            R["N8"]["watch_concept_tip"] = tip_text(page)
        R["N8"]["caveat_occurrences"] = (text(page, "#wt-list") or "").count("This search matched the concept in every language the ring covers")
        shot(page, "N-N8-watch-en")
        rec.junk_scan(page, "#ins-watches", "N8 watches en")
    n8()

    # ---------------- N9 ----------------
    @step("N9")
    def n9():
        words = {"a": "الإقليمية", "b": "الاقليميه", "c": "الإِقْلِيمِيَّة", "d1": "على", "d2": "علي", "zh1": "预算", "zh2": "诊所"}
        out = {}
        for k, w in words.items():
            page.bring_to_front()
            wp = open_analysis_new_tab(ctx, page, w)
            select_subtab(wp, "articles")
            tot = None
            try:
                tot = wait_art_total(wp, timeout=30000)
            except Exception:
                pass
            langs = sorted(set(wp.eval_on_selector_all("#an-art-list table tr[data-aid]", "rs=>rs.map(r=>(r.querySelectorAll('td')[2]||{innerText:''}).innerText.trim().slice(0,3))")))
            out[k] = {"word": w, "total": tot, "langs": langs, "xlang": text(wp, "#an-xlang"),
                      "empty_msg": None if tot else (text(wp, "#an-art-list") or "")[:200]}
            if k in ("a", "zh1"):
                shot(wp, f"N-N9-{k}-en")
            wp.close()
        R["N9"]["words"] = out
        # re-index
        page.bring_to_front()
        page.click("button[onclick=\"showTab('settings')\"]")
        page.wait_for_selector("#set-subtabs button[data-tab=advanced]", state="visible", timeout=20000)
        page.click("#set-subtabs button[data-tab=advanced]")
        page.wait_for_timeout(1000)
        page.click("details[data-adv=diagnostics] > summary")
        page.wait_for_selector("#fts-reindex-btn", state="visible", timeout=20000)
        n_before = len(dialogs)
        on_dialog.accept = True
        page.click("#fts-reindex-btn")
        page.wait_for_timeout(1500)
        on_dialog.accept = False
        R["N9"]["confirm"] = dialogs[n_before:]
        page.wait_for_function("() => /Articles checked: [\\d,]+ ·|not been upgraded|error/.test((document.getElementById('fts-reindex-status')||{}).textContent||'')", timeout=300000)
        page.wait_for_timeout(1000)
        R["N9"]["status_line"] = text(page, "#fts-reindex-status")
        shot(page, "N-N9-reindex-en")
        with ctx.expect_page(timeout=20000) as pinfo:
            page.click("#fts-reindex-report")
        rp = pinfo.value
        rp.wait_for_load_state("domcontentloaded")
        rp.wait_for_timeout(1000)
        R["N9"]["report_url"] = rp.url
        body = rp.evaluate("() => document.body.innerText")
        try:
            R["N9"]["report_json"] = json.loads(body)
        except Exception:
            R["N9"]["report_text"] = body[:1500]
        shot(rp, "N-N9-report-en")
        rp.close()
    n9()

    # ---------------- N10 ----------------
    @step("N10")
    def n10():
        page.bring_to_front()
        page.click("button[onclick=\"showTab('settings')\"]")
        page.click("#set-subtabs button[data-tab=advanced]")
        page.wait_for_timeout(800)
        page.click("details[data-adv=uninstall] > summary")
        page.wait_for_timeout(500)
        page.click("details[data-adv=bulletin] > summary")
        page.wait_for_timeout(3000)
        R["N10"]["gate"] = text(page, "#bulletin-gate")
        R["N10"]["controls_visible"] = page.is_visible("#bulletin-controls")
        R["N10"]["wipe_button_visible_below"] = page.is_visible("button[onclick='panicWipe()']")
        R["N10"]["cadence"] = page.eval_on_selector("#bul-cadence", "e=>e.value") if R["N10"]["controls_visible"] else None
        if not R["N10"]["controls_visible"]:
            shot(page, "N-N10-gate-en")
            return
        page.click("#bul-generate")
        page.wait_for_function("() => /Draft built|Could not build|not saved/.test((document.getElementById('bulletin-status')||{}).textContent||'')", timeout=180000)
        R["N10"]["status"] = text(page, "#bulletin-status")
        page.wait_for_selector("#bulletin-review button", timeout=30000)
        page.wait_for_timeout(800)
        R["N10"]["review_buttons"] = page.eval_on_selector_all("#bulletin-review button", "e=>e.map(b=>b.innerText.trim())")
        downloads = []
        page.on("download", lambda d: downloads.append(d))
        page.locator("#bulletin-review button", has_text="Download report + annexes").first.click()
        page.wait_for_function("() => /Downloaded|Could not download/.test((document.getElementById('bul-pub')||{}).textContent||'')", timeout=120000)
        page.wait_for_timeout(1500)
        R["N10"]["bul_pub"] = text(page, "#bul-pub")
        saved = []
        for d in downloads:
            dest = OUT / "downloads" / d.suggested_filename
            dest.parent.mkdir(exist_ok=True)
            d.save_as(str(dest))
            saved.append(str(dest))
        R["N10"]["downloads"] = saved
        shot(page, "N-N10-bulletin-en")
        for f in saved:
            if f.endswith(".zip"):
                z = zipfile.ZipFile(f)
                names = z.namelist()
                R["N10"]["zip_names_first"] = names[:15]
                R["N10"]["zip_count"] = len(names)
                cc = [n for n in names if n.endswith("CROSS-LANGUAGE-CONCEPTS.md")]
                R["N10"]["concepts_file"] = cc
                if cc:
                    body = z.read(cc[0]).decode("utf-8")
                    R["N10"]["concepts_md_head"] = body[:3000]
                    (OUT / "downloads" / "CROSS-LANGUAGE-CONCEPTS.md").write_text(body)
        # UNDO: delete the edition
        n_before = len(dialogs)
        on_dialog.accept = True
        page.locator("#bulletin-list button", has_text="Delete").first.click()
        page.wait_for_timeout(2500)
        on_dialog.accept = False
        R["N10"]["delete_dialogs"] = dialogs[n_before:]
        R["N10"]["list_after_delete"] = text(page, "#bulletin-list")
    n10()

    R["dialogs_all"] = dialogs
    import lib as _lib
    R["races"] = _lib.RACES
    b.close()

rec.data = R
rec.save()
suffix = "-".join(sorted(ONLY)) if ONLY else "all"
(OUT / f"R-en-{suffix}.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1)[:20000])
print("PAGE ERRORS", rec.page_errors)
print("CONSOLE ERRORS", rec.console_errors)
print("HTTP", rec.http_errors)
print("JUNK", rec.junk)
