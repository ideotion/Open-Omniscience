"""Recheck phase 3 (fr): sense-button click effect with request log; bare surfaces
(Home Trending now, Trends windows, reader Keywords, analysis Mindmap, Super-groups)."""
import json
import re
import sys

sys.path.insert(0, "/tmp/claude-0/walk/M-recheck")
from harness import *  # noqa

BASE = "http://127.0.0.1:8828"
R = {}
FOREIGN = re.compile(r"[Ѐ-ӿ؀-ۿ一-鿿]|\b(registros|semana|eleitores|observadores|confirmaron|software|district|regional)\b")


def on_dialog(d):
    d.dismiss()


def explore(page, term):
    page.fill("#ins-term", term)
    page.press("#ins-term", "Enter")
    page.wait_for_timeout(2500)


def open_an(page, sub):
    page.locator("button:has-text('⊞')").first.click()
    page.wait_for_timeout(3000)
    page.click(f"#an-subtabs [data-tab={sub}]")
    page.wait_for_timeout(3000)


with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page()
    attach(page, "main")
    page.on("dialog", on_dialog)
    unlock_if_needed(page, BASE)
    close_guide(page)
    if page.evaluate("document.documentElement.lang") != "fr":
        set_lang(page, "fr")
        page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(3000); close_guide(page)
    R["lang"] = page.evaluate("document.documentElement.lang")
    # ---- senses click with request log ----
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=explore]"); page.wait_for_timeout(1000)
    explore(page, "election")
    open_an(page, "keywords")
    page.wait_for_selector("#an-keywords .kw-sense", timeout=20000)
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/api/" in r.url else None)
    before_txt = page.inner_text("#an-keywords")
    before_q = page.evaluate("() => (document.getElementById('an-query')||{}).textContent || ''")
    page.locator("#an-keywords .kw-sense").first.click()
    page.wait_for_timeout(2500)
    R["senses_click"] = {"api_requests_after_click": reqs[:], "text_changed": before_txt != page.inner_text("#an-keywords"),
                         "query_before": before_q[:80], "query_after": page.evaluate("() => (document.getElementById('an-query')||{}).textContent || ''")[:80],
                         "tabs": page.evaluate("() => [...document.querySelectorAll('#an-tabs [data-an-tab], .an-tab, #an-tabstrip button')].map(x=>x.textContent.trim()).slice(0,8)")}
    # ---- analysis Mindmap on 'election' ----
    page.click("#an-subtabs [data-tab=mindmap]"); page.wait_for_timeout(3500)
    mm = page.evaluate("() => { const h=document.getElementById('an-mindmap') || document.querySelector('#tab-analyze [id*=mindmap]'); return h ? {id: h.id, text: h.innerText.slice(0,400), tags: h.querySelectorAll('.kw-tag').length, svgText: [...h.querySelectorAll('svg text')].map(t=>t.textContent).slice(0,20)} : null; }")
    R["mindmap"] = mm
    shot(page, "Mr-D7-an-mindmap-fr.png")
    # ---- Home Trending now ----
    goto_tab(page, "home")
    page.wait_for_timeout(3000)
    R["home_trending"] = page.evaluate("() => { const h=document.getElementById('ov-trending'); return h ? {text: h.innerText.slice(0,400), tags: h.querySelectorAll('.kw-tag').length, chips: [...h.querySelectorAll('a.chip')].map(a=>a.innerText.replace(/\\s+/g,' '))} : null; }")
    if page.locator("#ov-trending").count():
        page.locator("#ov-trending").scroll_into_view_if_needed()
        shot(page, "Mr-D7-home-trending-fr.png", selector="#ov-trending")
    # ---- Trends windows ----
    goto_tab(page, "insights")
    page.click("#ins-subtabs [data-tab=trends]"); page.wait_for_timeout(4000)
    R["trd_windows"] = page.evaluate("() => { const h=document.getElementById('trd-windows'); return h ? {tags: h.querySelectorAll('.kw-tag').length, links: [...h.querySelectorAll('a')].map(a=>a.innerText).slice(0,18)} : null; }")
    R["trends_top_rising"] = page.evaluate("() => [...document.querySelectorAll('#tab-insights .term-bars, #ins-top, #ins-rising')].map(h => ({id: h.id || h.className, tags: h.querySelectorAll('.kw-tag').length, sample: h.innerText.slice(0,200)}))")
    shot(page, "Mr-D7-trends-fr.png", selector="#trd-windows")
    # ---- Super-groups ----
    page.click("#ins-subtabs [data-tab=supergroups]"); page.wait_for_timeout(3500)
    R["supergroups"] = page.evaluate("() => { const h=document.querySelector('#sg-list'); return h ? {id: h.id, tags: h.querySelectorAll('.kw-tag').length, text: h.innerText.slice(0,300)} : null; }")
    # ---- reader Keywords ----
    aid = page.evaluate("async () => { const r = await (await fetch('/api/insights/trend?term=semana')).json(); return r; }")
    # find an article id through the corpus-facet or search API
    ids = page.evaluate("async () => { try { const r = await (await fetch('/api/articles?limit=5')).json(); return (r.results||r.articles||r.items||[]).slice(0,3).map(a=>a.id); } catch(e) { return String(e); } }")
    R["reader_ids"] = ids
    if isinstance(ids, list) and ids:
        rp = ctx.new_page(); attach(rp, "reader")
        rp.goto(f"{BASE}/api/articles/{ids[0]}/view", wait_until="domcontentloaded")
        rp.wait_for_timeout(2500)
        kwtab = rp.locator("[data-tab=keywords], button:has-text('Mots-clés'), button:has-text('Keywords')").first
        if kwtab.count():
            kwtab.click(); rp.wait_for_timeout(2500)
        R["reader_kw"] = rp.evaluate("() => { const p=document.querySelector('#r-pane-keywords, [data-pane=keywords], .r-pane.active, #pane-keywords'); const h = p || document.body; return {sel: p ? (p.id||p.className) : 'body', tags: h.querySelectorAll('.kw-tag').length, text: h.innerText.slice(0,300), lang: document.documentElement.lang}; }")
        rp.screenshot(path=log_path("Mr-D7-reader-keywords-fr.png"))
        rp.close()
    b.close()

with open(log_path("r3.json"), "w") as f:
    json.dump(R, f, indent=1, ensure_ascii=False)
dump_log("r3_log.json")
print(json.dumps(R, indent=1, ensure_ascii=False)[:9000])
