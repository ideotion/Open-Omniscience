"""Phase G: M7 (Home cards, fr/ar) + M8 surfaces (fr) + 375px en pass."""
import json
import re
import sys

sys.path.insert(0, "/tmp/claude-0/walk/M")
from harness import *  # noqa
from walk_b_lib import tags, open_insights_explore, explore, open_corpus_from_explore  # noqa

BASE = "http://127.0.0.1:8826"
R = {"M8": {}}
DIALOGS = []
CYR = re.compile(r"[Ѐ-ӿ]{3,}|[؀-ۿ]{3,}|\b(registros|semana|votantes|eleitores|software|turnout|election|district)\b")


def on_dialog(d):
    DIALOGS.append({"type": d.type, "message": d.message})
    d.accept() if "draft" in d.message.lower() or "brouillon" in d.message.lower() else d.dismiss()


def surface(page, sel, name):
    info = page.evaluate("""(sel) => { const h=document.querySelector(sel); if(!h) return {missing:true};
      const txt=h.innerText||''; const svgt=[...h.querySelectorAll('svg text')].map(e=>e.textContent).join(' ');
      return {tags: h.querySelectorAll('.kw-tag').length, kwterm: h.querySelectorAll('.kw-term').length,
              sample: (txt + ' ' + svgt).replace(/\\s+/g,' ').slice(0,400), svgtext: svgt.slice(0,300)}; }""", sel)
    if not info.get("missing"):
        foreign = sorted(set(m.group(0) for m in CYR.finditer(info["sample"])))[:8]
        info["foreign_words_seen"] = foreign
        info["verdict"] = ("tag present" if info["tags"] else ("tag absent" if foreign else "no foreign keyword seen"))
        info["junk"] = sorted(set(m.group(0) for m in JUNK_RE.finditer(info["sample"])))
    R["M8"][name] = info
    return info


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    unlock_if_needed(page, BASE)
    close_guide(page)
    if page.evaluate("document.documentElement.lang") != "fr":
        set_lang(page, "fr")
        page.reload(); page.wait_for_timeout(3500); close_guide(page)
    # ---- M7 + M8(a) Home ----
    goto_tab(page, "home")
    page.wait_for_timeout(3000)
    R["M7_card_titles_fr"] = page.evaluate("() => [...document.querySelectorAll('#tab-home h4')].map(e=>e.innerText).slice(0,40)")
    R["M7_rising_cards_fr"] = [t for t in R["M7_card_titles_fr"] if re.search(r"hausse|rising", t)]
    shot(page, "M-M7-home-fr.png")
    surface(page, "#ov-trending", "a_home_trending_now")
    R["M8"]["a_home_trends_panel_hidden"] = page.evaluate("() => { const e=document.getElementById('home-trends'); if(!e) return 'absent'; const p=e.closest('section')||e; return getComputedStyle(p).display==='none' || p.hidden || e.offsetParent===null; }")
    # ---- M8(b) Trends ----
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=trends]")
    page.wait_for_timeout(4000)
    surface(page, "#trd-windows", "b_trends_rising_three_windows")
    surface(page, "#trd-rising", "b_trends_rising_bars")
    surface(page, "#trd-top", "b_trends_top_bars")
    shot(page, "M-M8b-trends-fr.png", selector="#ins-trends")
    # ---- M8(c) Explore: Resolved to + mind-map + word cloud ----
    page.click("#ins-subtabs [data-tab=explore]")
    page.wait_for_timeout(1000)
    explore(page, "избирателей")
    page.wait_for_timeout(2500)
    surface(page, "#ins-trend", "c_explore_resolved_line")
    R["M8"]["c_resolved_line_text"] = page.inner_text("#ins-trend")[:120]
    surface(page, "#mm-kit", "c_explore_mindmap")
    cloud = page.locator("#mm-kit button:has-text('Nuage'), #mm-kit button:has-text('cloud'), #mm-kit [data-view=cloud]").first
    if cloud.count():
        cloud.click(); page.wait_for_timeout(2000)
        surface(page, "#mm-kit", "c_explore_wordcloud")
    shot(page, "M-M8c-explore-mindmap-fr.png", selector="#mm-kit")
    # ---- M8(d) Analysis Mindmap ----
    explore(page, "software")
    open_corpus_from_explore(page)
    page.click("#an-subtabs [data-tab=mindmap]")
    page.wait_for_timeout(3500)
    surface(page, "#an-mindmap", "d_analysis_mindmap")
    shot(page, "M-M8d-an-mindmap-fr.png")
    # ---- M8(g) reader: Articles subtab -> first article ----
    page.click("#an-subtabs [data-tab=articles]")
    page.wait_for_timeout(3000)
    link = page.locator("#an-articles a[href*='/view'], #an-art-list a[href*='/view']").first
    R["M8"]["g_article_link_found"] = link.count() > 0
    if link.count():
        href = link.get_attribute("href")
        rp = ctx.new_page(); attach(rp, "reader")
        rp.goto(BASE + href if href.startswith("/") else href)
        rp.wait_for_timeout(2500)
        kwb = rp.locator("button:has-text('Keywords'), button:has-text('Mots-clés'), [data-tab=keywords]").first
        R["M8"]["g_reader_kw_button"] = kwb.inner_text() if kwb.count() else None
        if kwb.count():
            kwb.click(); rp.wait_for_timeout(2500)
        surface(rp, "body", "g_reader_keywords")
        R["M8"]["g_reader_lang_attr"] = rp.evaluate("document.documentElement.lang")
        R["M8"]["g_reader_kw_head"] = rp.evaluate("() => (document.querySelector('.r-h2')||{}).textContent || null")
        rp.screenshot(path=log_path("M-M8g-reader-keywords-fr.png"))
        rp.close()
    # ---- M8(e) Super-groups ----
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=supergroups]")
    page.wait_for_timeout(3500)
    surface(page, "#sg-list", "e_supergroups")
    R["M8"]["e_sg_sample_html"] = page.evaluate("() => { const e=document.querySelector('#sg-list'); return e ? e.innerHTML.match(/⊕[^<]{0,80}|→[^<]{0,60}/g)?.slice(0,6) : null; }")
    shot(page, "M-M8e-supergroups-fr.png", selector="#ins-supergroups")
    # ---- M8(f) Observatory ----
    goto_tab(page, "observatory")
    page.wait_for_timeout(4000)
    surface(page, "#tab-observatory", "f_observatory")
    R["M8"]["f_sky_table_head"] = page.evaluate("() => (document.getElementById('sky-table')||{}).innerText?.slice(0,300) || null")
    shot(page, "M-M8f-observatory-fr.png")
    # ---- M8(h) Bulletin ----
    open_settings_advanced(page)
    R["M8"]["h_bulletin_nesting"] = page.evaluate("() => { const b=document.querySelector('details[data-adv=bulletin]'); const par=b.parentElement.closest('details'); return {parent_details: par ? par.dataset.adv : null, uninstall_panel_exists: !!document.getElementById('uninstall-panel'), bulletin_visible: b.offsetParent!==null}; }")
    open_adv(page, "uninstall")
    shot(page, "M-M8h-bulletin-inside-uninstall-fr.png", selector="details[data-adv=uninstall]")
    open_adv(page, "bulletin")
    page.wait_for_timeout(2000)
    R["M8"]["h_bulletin_gate"] = page.inner_text("#bulletin-gate")[:300]
    gen = page.locator("#bul-generate")
    if gen.is_visible():
        gen.click()
        page.wait_for_timeout(12000)
        R["M8"]["h_bulletin_status"] = page.inner_text("#bulletin-status")[:300]
        R["M8"]["h_bulletin_list"] = page.inner_text("#bulletin-list")[:400]
        opener = page.locator("#bulletin-list button, #bulletin-list a").first
        if opener.count():
            R["M8"]["h_bulletin_opener"] = opener.inner_text()
            opener.click(); page.wait_for_timeout(3000)
        surface(page, "#bulletin-panel", "h_bulletin")
        shot(page, "M-M8h-bulletin-fr.png", selector="#bulletin-panel")
    R["dialogs"] = DIALOGS
    # ---- M7 ar ----
    set_lang(page, "ar")
    page.reload(); page.wait_for_timeout(3500); close_guide(page)
    goto_tab(page, "home")
    page.wait_for_timeout(3000)
    R["M7_card_titles_ar"] = page.evaluate("() => [...document.querySelectorAll('#tab-home h4')].map(e=>e.innerText).slice(0,30)")
    b.close()
    with open(log_path("walk_g.json"), "w") as f:
        json.dump(R, f, indent=1, ensure_ascii=False)

    # ---- 375px en pass ----
    b, ctx = browser_ctx(p, width=375, height=800)
    page = ctx.new_page(); attach(page, "phone")
    unlock_if_needed(page, BASE)
    close_guide(page)
    set_lang(page, "en")
    page.reload(); page.wait_for_timeout(3500); close_guide(page)
    res = {}
    res["sidebar_visible_at_375"] = page.evaluate("() => { const r=document.querySelector('#navGroups').getBoundingClientRect(); return {left:r.left,right:r.right}; }")
    page.goto(BASE + "/#insights"); page.wait_for_timeout(2500); close_guide(page); dismiss_coach(page)
    page.wait_for_timeout(2500)
    res["insights_hscroll"] = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    page.wait_for_selector("#ins-landscape .ls-chip", timeout=30000)
    res["landscape_clipped_tags"] = sum(x["clipped"] for x in tags(page, "#ins-landscape"))
    page.screenshot(path=log_path("M-375-insights-en.png"), full_page=False)
    explore(page, "software")
    open_corpus_from_explore(page)
    res["an_hscroll"] = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    res["an_clipped_tags"] = sum(x["clipped"] for x in tags(page, "#an-keywords"))
    res["an_chips_wider_than_viewport"] = page.evaluate("() => [...document.querySelectorAll('#an-keywords .chip')].filter(c=>c.getBoundingClientRect().right>window.innerWidth+1).map(c=>c.innerText).slice(0,5)")
    shot(page, "M-375-an-keywords-en.png", selector="#an-keywords")
    page.goto(BASE + "/#settings"); page.wait_for_timeout(2000); dismiss_coach(page)
    page.click("#set-subtabs [data-tab=advanced]"); page.wait_for_timeout(800)
    open_adv(page, "keywords")
    page.locator("#ring-gaps").scroll_into_view_if_needed()
    page.wait_for_timeout(1000)
    res["settings_hscroll"] = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    shot(page, "M-375-ringpanel-en.png", selector="section.panel:has(#ring-gaps)")
    R["phone_375"] = res
    b.close()

with open(log_path("walk_g.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("walk_g_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:9000])
